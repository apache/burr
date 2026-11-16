# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Backward compatibility of the serialization context for type-based serde.

``serialization_context`` is injected into every type-based (de)serializer when an application
configures an object store. Nothing has ever required those functions to accept ``**kwargs``, so
injecting it unconditionally breaks serializers that predate the feature. These tests pin the
contract:

* a serializer that accepts neither ``**kwargs`` nor ``serialization_context`` is called exactly
  as before -- the kwarg is dropped, nothing else is;
* a serializer that declares ``serialization_context`` (or ``**kwargs``) receives the context of
  the application being serialized;
* the same holds on the async path, for field serde, and through persistence and resume.

The checks that decide this are cached per function; the tests below exercise the callable shapes
that make signature inspection interesting (partials, bound methods, callable objects, decorated
functions, positional-only parameters, unhashable callables).
"""

import functools
import gc
import inspect
import json
import pathlib
import re
import sqlite3
import threading
import warnings
from typing import Any, Dict, List

import pytest

from burr.core import ApplicationBuilder, Result, State, action, serde
from burr.core.artifacts import AsyncArtifactStore, LocalFileSystemArtifactStore
from burr.core.persistence import SQLitePersister
from burr.core.serde import SerializationContext
from burr.core.state import FIELD_SERIALIZATION, register_field_serde

# --- a legacy (pre-object-store) serde pair ------------------------------------------------------


class LegacyValue:
    """A user type registered the way Burr documented it before object stores existed.

    Neither function accepts ``**kwargs``: that was legal, and is what the docs showed.
    """

    def __init__(self, value: int):
        self.value = value

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, LegacyValue) and other.value == self.value

    def __repr__(self) -> str:
        return f"LegacyValue({self.value!r})"


@serde.serialize.register(LegacyValue)
def serialize_legacy(value):
    return {serde.KEY: "compat_legacy_value", "value": value.value}


@serde.deserializer.register("compat_legacy_value")
def deserialize_legacy(value):
    return LegacyValue(value["value"])


LEGACY_PAYLOAD = {serde.KEY: "compat_legacy_value", "value": 7}


class RecordingStore(LocalFileSystemArtifactStore):
    def __init__(self, root_dir: str):
        super().__init__(root_dir)
        self.puts: List[str] = []

    def put(self, data: bytes, key: str) -> bool:
        self.puts.append(key)
        return super().put(data, key)


class RecordingAsyncStore(AsyncArtifactStore):
    def __init__(self):
        self.data: Dict[str, bytes] = {}
        self.puts: List[str] = []

    async def put(self, data: bytes, key: str) -> bool:
        self.puts.append(key)
        if key in self.data:
            return False
        self.data[key] = data
        return True

    async def get(self, key: str) -> bytes:
        if key not in self.data:
            raise FileNotFoundError(key)
        return self.data[key]

    async def exists(self, key: str) -> bool:
        return key in self.data


@pytest.fixture
def store(tmp_path):
    return RecordingStore(str(tmp_path / "blobs"))


@pytest.fixture
def async_store():
    return RecordingAsyncStore()


def _ctx(store) -> SerializationContext:
    return SerializationContext(object_store=store)


# --- A. type-based, synchronous ------------------------------------------------------------------


def test_legacy_serde_round_trips_without_a_context():
    """The baseline: no store, no context, unchanged behavior."""
    payload = State({"v": LegacyValue(7)}).serialize()

    assert payload == {"v": LEGACY_PAYLOAD}
    assert State.deserialize(payload)["v"] == LegacyValue(7)


def test_legacy_serde_round_trips_with_a_context_in_scope(store):
    """Enabling an object store must not change the payload a legacy serializer produces."""
    with serde.serialization_context(_ctx(store)):
        payload = State({"v": LegacyValue(7)}).serialize()
        restored = State.deserialize(payload)

    assert payload == {"v": LEGACY_PAYLOAD}
    assert restored["v"] == LegacyValue(7)


def test_legacy_serde_round_trips_with_an_explicit_context_kwarg(store):
    payload = State({"v": LegacyValue(7)}).serialize(serialization_context=_ctx(store))

    assert payload == {"v": LEGACY_PAYLOAD}
    assert State.deserialize(payload, serialization_context=_ctx(store))["v"] == LegacyValue(7)


def test_context_aware_serializer_receives_the_application_context(store):
    seen = []

    class Aware:
        pass

    @serde.serialize.register(Aware)
    def _serialize_aware(value, serialization_context=None):
        seen.append(serialization_context)
        return {serde.KEY: "compat_aware"}

    @serde.deserializer.register("compat_aware")
    def _deserialize_aware(value, serialization_context=None):
        seen.append(serialization_context)
        return Aware()

    context = _ctx(store)
    payload = State({"v": Aware()}).serialize(serialization_context=context)
    State.deserialize(payload, serialization_context=context)

    assert seen == [context, context]


def test_star_kwargs_serializer_receives_the_context(store):
    seen = {}

    class Kwargy:
        pass

    @serde.serialize.register(Kwargy)
    def _serialize_kwargy(value, **kwargs):
        seen.update(kwargs)
        return {serde.KEY: "compat_kwargy"}

    context = _ctx(store)
    State({"v": Kwargy()}).serialize(serialization_context=context)

    assert seen == {"serialization_context": context}


def test_other_kwargs_survive_when_the_context_is_dropped(store):
    """Only ``serialization_context`` is removed -- the serializer's own kwargs still arrive."""
    seen = {}

    class Namespaced:
        pass

    @serde.serialize.register(Namespaced)
    def _serialize_namespaced(value, namespace=None):
        seen["namespace"] = namespace
        return {serde.KEY: "compat_namespaced"}

    State({"v": Namespaced()}).serialize(serialization_context=_ctx(store), namespace={"a": 1})

    assert seen == {"namespace": {"a": 1}}


def test_nested_legacy_values_are_filtered_too(store):
    """The filtering happens at dispatch, so it applies at every depth, not just top level."""
    state = State(
        {
            "outer": {
                "inner": [LegacyValue(1), {"deep": LegacyValue(2)}],
            }
        }
    )
    with serde.serialization_context(_ctx(store)):
        payload = state.serialize()
        restored = State.deserialize(payload)

    assert payload["outer"]["inner"][0] == {
        serde.KEY: "compat_legacy_value",
        "value": 1,
    }
    assert restored["outer"]["inner"][1]["deep"] == LegacyValue(2)


def test_no_context_is_passed_when_none_is_configured():
    """Without a store the kwargs must be exactly what the caller passed -- nothing added."""
    seen = {}

    class Spy:
        pass

    @serde.serialize.register(Spy)
    def _serialize_spy(value, **kwargs):
        seen.update(kwargs)
        return {serde.KEY: "compat_spy"}

    State({"v": Spy()}).serialize(only_this=1)

    assert seen == {"only_this": 1}


def test_the_filter_only_ever_removes_the_context():
    """Called directly, the helper must still leave a serializer's own kwargs alone."""

    def _legacy(value):
        return value

    assert serde._drop_unsupported_context(_legacy, {"other": 1}) == {"other": 1}
    assert serde._drop_unsupported_context(_legacy, {"serialization_context": object()}) == {}
    assert serde._drop_unsupported_context(_legacy, {}) == {}


def test_annotation_form_registration_still_works(store):
    """``@serialize.register`` without parentheses is part of the singledispatch surface."""

    class Annotated:
        pass

    @serde.serialize.register
    def _serialize_annotated(value: Annotated) -> dict:
        return {serde.KEY: "compat_annotated"}

    assert serde.serialize.dispatch(Annotated) is _serialize_annotated

    with serde.serialization_context(_ctx(store)):
        payload = State({"v": Annotated()}).serialize()

    assert payload == {"v": {serde.KEY: "compat_annotated"}}


def test_a_legacy_serializer_on_a_base_class_handles_subclasses(store):
    """The filter has to look at the implementation the dispatcher picked, not at the value."""

    class Base:
        pass

    class Child(Base):
        pass

    @serde.serialize.register(Base)
    def _serialize_base(value):
        return {serde.KEY: "compat_base"}

    @serde.deserializer.register("compat_base")
    def _deserialize_base(value):
        return Base()

    context = _ctx(store)
    with serde.serialization_context(context):
        payload = State({"v": Child()}).serialize()
        restored = State.deserialize(payload)

    assert payload == {"v": {serde.KEY: "compat_base"}}
    assert isinstance(restored["v"], Base)


def test_concurrent_serialization_keeps_contexts_separate(store):
    """One context per application also has to hold across threads sharing the signature cache."""
    from concurrent.futures import ThreadPoolExecutor

    seen = []
    lock = threading.Lock()

    class Threaded:
        pass

    @serde.serialize.register(Threaded)
    def _serialize_threaded(value, serialization_context=None):
        with lock:
            seen.append(serialization_context)
        return {serde.KEY: "compat_threaded"}

    contexts = [_ctx(store) for _ in range(8)]

    def _run(context):
        with serde.serialization_context(context):
            return State({"v": Threaded()}).serialize()

    with ThreadPoolExecutor(max_workers=8) as pool:
        payloads = list(pool.map(_run, contexts))

    assert payloads == [{"v": {serde.KEY: "compat_threaded"}}] * 8
    assert sorted(id(c) for c in seen) == sorted(id(c) for c in contexts)


def test_serializer_type_error_propagates_and_runs_once():
    """A ``TypeError`` raised *by* the serializer is not swallowed, and it is not retried."""
    calls = []

    class Explodes:
        pass

    @serde.serialize.register(Explodes)
    def _serialize_explodes(value):
        calls.append(value)
        raise TypeError("boom from the serializer")

    with pytest.raises(ValueError) as exc_info:
        State({"v": Explodes()}).serialize(serialization_context=SerializationContext())

    assert "boom from the serializer" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, TypeError)
    assert len(calls) == 1


def test_positional_only_parameters_do_not_receive_the_context(store):
    """A positional-only parameter cannot be filled by keyword, so it must not be passed."""
    seen = {}

    class Positional:
        pass

    @serde.serialize.register(Positional)
    def _serialize_positional(value, /):
        seen["value"] = value
        return {serde.KEY: "compat_positional"}

    with serde.serialization_context(_ctx(store)):
        assert State({"v": Positional()}).serialize() == {"v": {serde.KEY: "compat_positional"}}
    assert isinstance(seen["value"], Positional)


def test_a_positional_only_parameter_named_like_the_context_is_not_passed(store):
    """The name alone is not enough: a positional-only ``serialization_context`` cannot be a kwarg."""

    class PositionalContext:
        pass

    @serde.serialize.register(PositionalContext)
    def _serialize_positional_context(value, serialization_context=None, /):
        return {
            serde.KEY: "compat_positional_context",
            "context": serialization_context,
        }

    with serde.serialization_context(_ctx(store)):
        payload = State({"v": PositionalContext()}).serialize()

    assert payload == {
        "v": {serde.KEY: "compat_positional_context", "context": None},
    }


def test_the_signature_is_inspected_once_per_function(store, monkeypatch):
    """The check must be cached -- reflecting on every serialization is exactly what we avoided."""
    inspected = []
    original = serde._inspect_accepts_context

    def _counting(func):
        inspected.append(func)
        return original(func)

    monkeypatch.setattr(serde, "_inspect_accepts_context", _counting)

    class Cached:
        pass

    @serde.serialize.register(Cached)
    def _serialize_cached(value):
        return {serde.KEY: "compat_cached"}

    with serde.serialization_context(_ctx(store)):
        for _ in range(5):
            State({"v": Cached()}).serialize()

    assert inspected.count(_serialize_cached) == 1


def test_functools_partial_serializer(store):
    class PartialValue:
        pass

    def _impl(value, prefix):
        return {serde.KEY: "compat_partial", "prefix": prefix}

    serde.serialize.register(PartialValue)(functools.partial(_impl, prefix="p"))

    with serde.serialization_context(_ctx(store)):
        payload = State({"v": PartialValue()}).serialize()

    assert payload == {"v": {serde.KEY: "compat_partial", "prefix": "p"}}


def test_bound_method_serializer(store):
    class BoundValue:
        pass

    class Serializer:
        def __init__(self, tag):
            self.tag = tag
            self.calls = 0

        def serialize(self, value, **kwargs):
            self.calls += 1
            return {serde.KEY: "compat_bound", "tag": self.tag}

    serializer = Serializer("t")
    serde.serialize.register(BoundValue)(serializer.serialize)

    context = _ctx(store)
    payload = State({"v": BoundValue()}).serialize(serialization_context=context)

    assert payload == {"v": {serde.KEY: "compat_bound", "tag": "t"}}
    assert serializer.calls == 1


def test_callable_object_serializer_without_kwargs(store):
    class CallableValue:
        pass

    class Serializer:
        def __call__(self, value):
            return {serde.KEY: "compat_callable"}

    serde.serialize.register(CallableValue)(Serializer())

    with serde.serialization_context(_ctx(store)):
        assert State({"v": CallableValue()}).serialize() == {"v": {serde.KEY: "compat_callable"}}


def test_unhashable_callable_serializer_is_not_cached_but_works(store):
    """An unhashable callable cannot be a cache key; it must still serialize correctly."""

    class UnhashableValue:
        pass

    class UnhashableSerializer:
        __hash__ = None

        def __call__(self, value):
            return {serde.KEY: "compat_unhashable"}

    serde.serialize.register(UnhashableValue)(UnhashableSerializer())

    with serde.serialization_context(_ctx(store)):
        for _ in range(3):
            assert State({"v": UnhashableValue()}).serialize() == {
                "v": {serde.KEY: "compat_unhashable"}
            }


def test_decorated_serializer_follows_the_wrapped_signature(store):
    """``functools.wraps`` describes the effective contract, so the wrapped signature decides."""

    class DecoratedValue:
        pass

    def _legacy(value):
        return {serde.KEY: "compat_decorated"}

    @functools.wraps(_legacy)
    def _wrapper(*args, **kwargs):
        return _legacy(*args, **kwargs)

    serde.serialize.register(DecoratedValue)(_wrapper)

    with serde.serialization_context(_ctx(store)):
        assert State({"v": DecoratedValue()}).serialize() == {"v": {serde.KEY: "compat_decorated"}}


def test_re_registering_a_type_uses_the_new_signature(store):
    """The per-function cache must not leak across re-registration of the same type."""

    class Swapped:
        pass

    @serde.serialize.register(Swapped)
    def _first(value):
        return {serde.KEY: "compat_swapped", "impl": "first"}

    with serde.serialization_context(_ctx(store)):
        assert State({"v": Swapped()}).serialize()["v"]["impl"] == "first"

    seen = {}

    @serde.serialize.register(Swapped)
    def _second(value, serialization_context=None):
        seen["context"] = serialization_context
        return {serde.KEY: "compat_swapped", "impl": "second"}

    context = _ctx(store)
    with serde.serialization_context(context):
        assert State({"v": Swapped()}).serialize()["v"]["impl"] == "second"

    assert seen["context"] is context


# --- B. type-based, asynchronous -----------------------------------------------------------------


class AsyncValue:
    pass


class LegacyAsyncValue:
    pass


@serde.serialize.register(AsyncValue)
async def _serialize_async_value(value, serialization_context=None):
    return {
        serde.KEY: "compat_async_value",
        "has_context": serialization_context is not None,
    }


@serde.deserializer.register("compat_async_value")
async def _deserialize_async_value(value, serialization_context=None):
    return ("async-value", value["has_context"], serialization_context is not None)


@serde.serialize.register(LegacyAsyncValue)
async def _serialize_legacy_async_value(value):
    return {serde.KEY: "compat_legacy_async"}


@serde.deserializer.register("compat_legacy_async")
async def _deserialize_legacy_async_value(value):
    return LegacyAsyncValue()


async def test_async_serializer_receives_the_context(async_store):
    payload = await State({"v": AsyncValue()}).aserialize(serialization_context=_ctx(async_store))

    assert payload == {"v": {serde.KEY: "compat_async_value", "has_context": True}}


async def test_async_deserializer_receives_the_context(async_store):
    restored = await State.adeserialize(
        {"v": {serde.KEY: "compat_async_value", "has_context": True}},
        serialization_context=_ctx(async_store),
    )

    assert restored["v"] == ("async-value", True, True)


async def test_legacy_async_serde_without_kwargs_works_with_a_context(async_store):
    """The filtering has to happen before the call on the async path too."""
    payload = await State({"v": LegacyAsyncValue()}).aserialize(
        serialization_context=_ctx(async_store)
    )
    restored = await State.adeserialize(payload, serialization_context=_ctx(async_store))

    assert payload == {"v": {serde.KEY: "compat_legacy_async"}}
    assert isinstance(restored["v"], LegacyAsyncValue)


async def test_star_kwargs_async_serializer_receives_the_context(async_store):
    seen = {}

    class AsyncKwargy:
        pass

    @serde.serialize.register(AsyncKwargy)
    async def _serialize_async_kwargy(value, **kwargs):
        seen.update(kwargs)
        return {serde.KEY: "compat_async_kwargy"}

    context = _ctx(async_store)
    await State({"v": AsyncKwargy()}).aserialize(serialization_context=context)

    assert seen == {"serialization_context": context}


async def test_aserialize_matches_serialize_for_legacy_serde():
    """Async persisters must write what sync persisters write."""
    sync_payload = State({"v": LegacyValue(7)}).serialize()
    async_payload = await State({"v": LegacyValue(7)}).aserialize()

    assert async_payload == sync_payload


async def test_async_serializer_result_that_is_still_awaitable_raises():
    """``await`` resolves one level; a missing inner await must not leak a coroutine."""

    class NestedCoro:
        pass

    @serde.serialize.register(NestedCoro)
    async def _serialize_nested(value):
        async def _inner():
            return 1

        return _inner()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ValueError, match="never resolved"):
            await State({"v": NestedCoro()}).aserialize()
        gc.collect()

    assert not [w for w in caught if "never awaited" in str(w.message)]


async def test_coroutine_inside_a_returned_payload_fails_loudly_at_json_dumps():
    """Documented boundary: a coroutine nested inside a serializer's own payload is opaque to the
    framework (user payloads are not walked), so it surfaces when the payload is encoded."""

    class NestedInPayload:
        pass

    @serde.serialize.register(NestedInPayload)
    async def _serialize_nested_in_payload(value):
        async def _inner():
            return 1

        return {serde.KEY: "compat_nested_payload", "c": _inner()}

    payload = await State({"v": NestedInPayload()}).aserialize()
    leaked = payload["v"]["c"]
    assert inspect.iscoroutine(leaked)
    leaked.close()  # keep the assertion below about json, not about warnings

    with pytest.raises(TypeError, match="not JSON serializable"):
        json.dumps(payload)


async def test_async_deserializer_result_that_is_still_awaitable_raises():
    class AsyncDeserValue:
        pass

    @serde.deserializer.register("compat_async_deser_awaitable")
    async def _deserialize(value):
        async def _inner():
            return AsyncDeserValue()

        return _inner()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ValueError, match="never resolved"):
            await State.adeserialize({"v": {serde.KEY: "compat_async_deser_awaitable"}})
        gc.collect()

    assert not [w for w in caught if "never awaited" in str(w.message)]


# --- C. field-based serde ------------------------------------------------------------------------


def test_register_field_serde_still_requires_star_kwargs():
    """The field-level contract is unchanged: ``**kwargs`` is mandatory there."""
    with pytest.raises(ValueError, match="must have \\*\\*kwargs"):

        def _serializer(value):
            return {}

        def _deserializer(value):
            return value

        register_field_serde("compat_no_kwargs", _serializer, _deserializer)


def test_field_serde_still_receives_the_context(store):
    field = "compat_field_with_context"
    seen = {}

    def _serialize_field(value, **kwargs):
        seen["context"] = kwargs.get("serialization_context")
        return {"value": value}

    def _deserialize_field(value, **kwargs):
        seen["deserialize_context"] = kwargs.get("serialization_context")
        return value["value"]

    register_field_serde(field, _serialize_field, _deserialize_field)
    try:
        context = _ctx(store)
        payload = State({field: "hello", "v": LegacyValue(1)}).serialize(
            serialization_context=context
        )
        State.deserialize(payload, serialization_context=context)
    finally:
        del FIELD_SERIALIZATION[field]

    assert seen["context"] is context
    assert seen["deserialize_context"] is context
    # a type-based legacy serializer in the same state is unaffected
    assert payload["v"] == {serde.KEY: "compat_legacy_value", "value": 1}


# --- D. persistence and resume -------------------------------------------------------------------


@action(reads=[], writes=["v"])
def produce(state: State) -> State:
    return state.update(v=LegacyValue(42))


@action(reads=["v"], writes=["seen"])
def consume(state: State) -> State:
    return state.update(seen=state["v"].value)


def _build_sync_app(store, persister, app_id, initialize):
    builder = (
        ApplicationBuilder()
        .with_actions(produce, consume, result=Result("seen"))
        .with_transitions(("produce", "consume"), ("consume", "result"))
        .with_identifiers(app_id=app_id, partition_key="pk")
        .with_object_store(store)
        .with_state_persister(persister)
    )
    if initialize:
        builder = builder.initialize_from(
            persister, resume_at_next_action=True, default_state={}, default_entrypoint="produce"
        )
    else:
        builder = builder.with_entrypoint("produce")
    return builder.build()


def test_legacy_serde_survives_sync_persist_and_resume(tmp_path, store):
    """The case the maintainer reported: enabling a store must not break existing serializers."""
    db_path = str(tmp_path / "state.db")
    persister = SQLitePersister.from_values(db_path=db_path, table_name="t")
    persister.initialize()

    app = _build_sync_app(store, persister, "legacy-sync", initialize=False)
    *_, final_state = app.run(halt_after=["result"])
    assert final_state["seen"] == 42

    raw = sqlite3.connect(db_path).execute("SELECT state FROM t ORDER BY sequence_id").fetchall()
    assert "compat_legacy_value" in raw[-1][0]

    resumed = _build_sync_app(store, persister, "legacy-sync", initialize=True)
    assert resumed.state["v"] == LegacyValue(42)

    persister.cleanup()


def test_legacy_serde_survives_tracking(tmp_path, store):
    """Tracking serializes state through the same context, so it has to work there too.

    The review's bar is "persist *and* track exactly the bytes it did before"; the persister path is
    covered above, this is the tracker half.
    """
    from burr.tracking.client import LocalTrackingClient

    tracker = LocalTrackingClient(project="compat", storage_dir=str(tmp_path / "tracking"))
    app = (
        ApplicationBuilder()
        .with_actions(produce, consume, result=Result("seen"))
        .with_transitions(("produce", "consume"), ("consume", "result"))
        .with_identifiers(app_id="legacy-track", partition_key="pk")
        .with_object_store(store)
        .with_tracker(tracker)
        .with_entrypoint("produce")
        .build()
    )
    app.run(halt_after=["result"])

    log_path = tmp_path / "tracking" / "compat" / "legacy-track" / "log.jsonl"
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    end_entries = [entry for entry in entries if entry["type"] == "end_entry"]
    assert end_entries[-1]["state"]["v"] == {
        serde.KEY: "compat_legacy_value",
        "value": 42,
    }

    # the tracker doubles as a state loader -- the legacy deserializer runs through it as well
    with serde.serialization_context(_ctx(store)):
        loaded = tracker.load("pk", "legacy-track")
    assert loaded["state"]["v"] == LegacyValue(42)


class AsyncLegacyValue:
    def __init__(self, value: int):
        self.value = value


@serde.serialize.register(AsyncLegacyValue)
async def _serialize_async_legacy_value(value):
    return {serde.KEY: "compat_async_legacy_persisted", "value": value.value}


@serde.deserializer.register("compat_async_legacy_persisted")
async def _deserialize_async_legacy_value(value):
    return AsyncLegacyValue(value["value"])


@action(reads=[], writes=["v"])
async def aproduce(state: State) -> State:
    return state.update(v=AsyncLegacyValue(42))


@action(reads=["v"], writes=["seen"])
async def aconsume(state: State) -> State:
    return state.update(seen=state["v"].value)


def _build_async_app(store, persister, app_id, initialize):
    builder = (
        ApplicationBuilder()
        .with_actions(aproduce, aconsume, result=Result("seen"))
        .with_transitions(("aproduce", "aconsume"), ("aconsume", "result"))
        .with_identifiers(app_id=app_id, partition_key="pk")
        .with_object_store(store)
        .with_state_persister(persister)
    )
    if initialize:
        builder = builder.initialize_from(
            persister, resume_at_next_action=True, default_state={}, default_entrypoint="aproduce"
        )
    else:
        builder = builder.with_entrypoint("aproduce")
    return builder.abuild()


async def test_legacy_async_serde_survives_async_persist_and_resume(tmp_path, async_store):
    from burr.integrations.persisters.b_aiosqlite import AsyncSQLitePersister

    db_path = str(tmp_path / "async_state.db")
    async with AsyncSQLitePersister.from_values(db_path=db_path, table_name="t") as persister:
        await persister.initialize()

        app = await _build_async_app(async_store, persister, "legacy-async", initialize=False)
        *_, final_state = await app.arun(halt_after=["result"])
        assert final_state["seen"] == 42

        resumed = await _build_async_app(async_store, persister, "legacy-async", initialize=True)
        assert isinstance(resumed.state["v"], AsyncLegacyValue)
        assert resumed.state["v"].value == 42

    raw = sqlite3.connect(db_path).execute("SELECT state FROM t").fetchall()
    assert "compat_async_legacy_persisted" in raw[-1][0]


def test_payloads_are_identical_with_and_without_a_store(store):
    """A golden-file guarantee: opting in must not change what existing serde writes."""
    state = State(
        {
            "v": LegacyValue(7),
            "plain": {"a": [1, 2, {"b": "c"}]},
            "text": "hello",
            "number": 3,
        }
    )

    without_store = state.serialize()
    with serde.serialization_context(_ctx(store)):
        with_store = state.serialize()

    assert with_store == without_store


# --- E. the per-application memo -----------------------------------------------------------------


def test_a_legacy_serializer_does_not_disturb_the_memo(store):
    """The filtering must not clear, replace or copy the context -- the memo is the same object."""
    context = _ctx(store)
    context.memo["seed"] = {"ref": "kept"}

    with serde.serialization_context(context):
        State({"v": LegacyValue(1)}).serialize()

    assert context.memo == {"seed": {"ref": "kept"}}


def _build_bare_app(store, app_id):
    """An application with an object store and no persister -- just enough to install a context."""
    return (
        ApplicationBuilder()
        .with_actions(produce, consume)
        .with_transitions(("produce", "consume"))
        .with_identifiers(app_id=app_id, partition_key="pk")
        .with_object_store(store)
        .with_entrypoint("produce")
        .build()
    )


def test_an_application_keeps_one_context_across_dispatches(store):
    """Two hook dispatches must see the same ``SerializationContext`` (and therefore one memo)."""
    app = _build_bare_app(store, "memo-app")

    factory = app._adapter_set._hook_context
    assert factory is not None

    contexts = []
    for _ in range(2):
        with factory():
            contexts.append(serde.get_serialization_context())

    assert contexts[0] is contexts[1]
    assert contexts[0].memo is contexts[1].memo
    assert contexts[0].object_store is store


def test_two_applications_do_not_share_a_context(store):
    one = _build_bare_app(store, "app-one")
    two = _build_bare_app(store, "app-two")

    with one._adapter_set._hook_context():
        first = serde.get_serialization_context()
    with two._adapter_set._hook_context():
        second = serde.get_serialization_context()

    assert first is not second
    assert first.memo is not second.memo


# --- F. exception behavior on the sync path ------------------------------------------------------


def test_sync_path_rejects_a_legacy_async_serializer_with_the_async_error():
    """Filtering first means the real error surfaces, not a ``TypeError`` about an unexpected kwarg."""
    with pytest.raises(ValueError, match="asynchronous"):
        State({"v": LegacyAsyncValue()}).serialize(serialization_context=SerializationContext())


def test_sync_path_rejects_an_async_serializer_without_leaking_a_coroutine():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ValueError, match="asynchronous"):
            State({"v": AsyncValue()}).serialize(serialization_context=SerializationContext())
        gc.collect()

    assert not [w for w in caught if "never awaited" in str(w.message)]


def test_a_coroutine_in_state_is_rejected_loudly():
    """Rather than persisting ``"<coroutine object ...>"``, which is what the old fallback did."""

    async def _unused():
        return 1

    coroutine = _unused()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(ValueError, match="Cannot serialize a coroutine"):
                State({"v": coroutine}).serialize()
            gc.collect()
    finally:
        if inspect.iscoroutine(coroutine) and coroutine.cr_frame is not None:
            coroutine.close()

    assert not [w for w in caught if "never awaited" in str(w.message)]


# --- G. a golden file captured from main ---------------------------------------------------------

GOLDEN_PAYLOADS = pathlib.Path(__file__).parent / "golden" / "serde_payloads_main.json"


def _normalize_payload(value):
    """Masks the parts of the payload that are the environment's, not Burr's.

    The pandas payload embeds ``<base>/df_<sha256>.parquet``: the separator is platform-specific and
    the hash comes from pandas' own hashing. ``__pydantic_class`` carries the module the model was
    defined in, which is this test file. Both are masked so the golden file pins what Burr is
    responsible for -- the envelope, the naming scheme, and the class name.
    """
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if key == "__pydantic_class" and isinstance(item, str):
                normalized[key] = item.rsplit(".", 1)[-1]
            else:
                normalized[key] = _normalize_payload(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_payload(item) for item in value]
    if isinstance(value, str):
        masked = re.sub(r"df_[0-9a-f]{64}\.parquet", "df_<sha256>.parquet", value)
        return masked.replace("\\", "/")
    return value


def test_payloads_are_byte_identical_to_main(tmp_path, monkeypatch):
    """Golden file captured from apache/burr main (36e3ff30), the commit before #931.

    The bar from the review: an app that never calls ``with_object_store`` must persist and track
    exactly the bytes it did before. This covers the serializers that already existed -- primitives,
    the ``str`` fallback, escaped dicts, pydantic, pandas and field serde -- and fails on any drift,
    not just on an exception.
    """
    import datetime
    import enum

    import pandas as pd
    import pydantic

    class Color(enum.Enum):
        RED = "red"

    class User(pydantic.BaseModel):
        name: str
        age: int
        tags: list = []

    def _serialize_report(value, **kwargs):
        return {"value": value, "kind": "report"}

    def _deserialize_report(value, **kwargs):
        return value["value"]

    register_field_serde("report", _serialize_report, _deserialize_report)
    # the parquet file is written next to the cwd; keep it inside the test's temp dir
    monkeypatch.chdir(tmp_path)
    try:
        state = State(
            {
                "none": None,
                "bool": True,
                "int": 42,
                "float": 3.5,
                "str": "text",
                "bytes": b"raw-bytes",
                "tuple": (1, 2),
                "set": {1, 2, 3},
                "datetime": datetime.datetime(2020, 1, 2, 3, 4, 5),
                "enum": Color.RED,
                "escaped_dict": {serde.KEY: "hello", "n": 1},
                "nested": {"a": [1, {"b": {"c": 2}}]},
                "pydantic": User(name="ada", age=36),
                "report": "the report body",
            }
        )
        payload = state.serialize(pandas_kwargs={"path": "burr_golden_blobs"})
        frame_payload = State(
            {"frame": pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})}
        ).serialize(pandas_kwargs={"path": "burr_golden_blobs"})
    finally:
        del FIELD_SERIALIZATION["report"]

    actual = _normalize_payload({"state": payload, "frame": frame_payload})
    expected = json.loads(GOLDEN_PAYLOADS.read_text(encoding="utf-8"))

    assert actual == expected


# --- H. the dispatcher surface is unchanged ------------------------------------------------------


def test_serialize_still_exposes_the_singledispatch_surface():
    """``serialize`` is still a dispatcher: the registry holds the user's functions, not wrappers."""
    assert serde.serialize.registry[LegacyValue] is serialize_legacy
    assert serde.serialize.dispatch(LegacyValue) is serialize_legacy
    assert callable(serde.serialize._clear_cache)

    class Fresh:
        pass

    @serde.serialize.register(Fresh)
    def _serialize_fresh(value):
        return {serde.KEY: "compat_fresh"}

    assert serde.serialize.registry[Fresh] is _serialize_fresh
    assert serde.serialize(Fresh()) == {serde.KEY: "compat_fresh"}

    # the two-argument form keeps working as well
    def _serialize_fresh_two_arg(value):
        return {serde.KEY: "compat_fresh_two_arg"}

    serde.serialize.register(Fresh, _serialize_fresh_two_arg)
    assert serde.serialize.dispatch(Fresh) is _serialize_fresh_two_arg
