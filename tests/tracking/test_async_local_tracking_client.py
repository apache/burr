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

"""Tests for :py:class:`~burr.tracking.client.AsyncLocalTrackingClient` and its OpenTelemetry
integration.

The scenario throughout is the one the async tracker exists for: an application that serializes
through ``async def`` serializers because it has an
:py:class:`~burr.core.artifacts.AsyncArtifactStore`. Those serializers externalize large payloads
to the store through the :py:class:`~burr.core.serde.SerializationContext`, which means the step
hooks must await them -- the synchronous :py:class:`~burr.tracking.client.LocalTrackingClient`
cannot.

The tests are organized as:

* :py:class:`TestAsyncClientHooks` -- the async client in isolation: the log schema, filtering,
  serialization context propagation, exactly-once behavior, copy semantics.
* :py:class:`TestEndToEnd` -- the full builder path through ``abuild()``/``arun()``: async
  type-based serde, async field-based serde, async persister, resume, memo reuse.
* :py:class:`TestBuilderSelection` -- which client the builder selects, for every combination
  and both builder call orders.
* :py:class:`TestBackwardCompatibility` -- the synchronous client is untouched.
* :py:class:`TestOpenTelemetry` -- the async OpenTelemetry wrapper.
* :py:class:`TestFailures` -- failed steps and cancellation.
"""

import asyncio
import hashlib
import json
import os
from typing import Dict, List, Optional, Tuple

import pytest

from burr.core import ApplicationBuilder, State, action, serde
from burr.core.artifacts import ArtifactStore, AsyncArtifactStore
from burr.core.persistence import AsyncBaseStatePersister
from burr.integrations.opentelemetry import AsyncOpenTelemetryTracker, OpenTelemetryTracker
from burr.lifecycle.internal import LifecycleAdapterSet
from burr.tracking.base import AsyncTrackingClient, SyncTrackingClient
from burr.tracking.client import AsyncLocalTrackingClient, LocalTrackingClient
from burr.tracking.common.models import BeginEntryModel, EndEntryModel

# --- instrumented stores ------------------------------------------------------------------------


class CountingAsyncStore(AsyncArtifactStore):
    """An in-memory async store that records every call, so a test can assert that an unchanged
    payload is uploaded once and then never touched again."""

    def __init__(self):
        self.data: Dict[str, bytes] = {}
        self.put_calls: List[str] = []
        self.get_calls: List[str] = []
        self.exists_calls: List[str] = []

    async def put(self, data: bytes, key: str) -> bool:
        self.put_calls.append(key)
        if key in self.data:
            return False
        self.data[key] = data
        return True

    async def get(self, key: str) -> bytes:
        self.get_calls.append(key)
        if key not in self.data:
            raise FileNotFoundError(key)
        return self.data[key]

    async def exists(self, key: str) -> bool:
        self.exists_calls.append(key)
        return key in self.data


class CountingSyncStore(ArtifactStore):
    """Synchronous counterpart, used to check the sync path is unaffected."""

    def __init__(self):
        self.data: Dict[str, bytes] = {}
        self.put_calls: List[str] = []

    def put(self, data: bytes, key: str) -> bool:
        self.put_calls.append(key)
        if key in self.data:
            return False
        self.data[key] = data
        return True

    def get(self, key: str) -> bytes:
        if key not in self.data:
            raise FileNotFoundError(key)
        return self.data[key]

    def exists(self, key: str) -> bool:
        return key in self.data


# --- an asynchronously serialized user type ------------------------------------------------------


class Pdf:
    """Stands in for a large user payload -- the kind of value that must live in the object store
    rather than inline in the tracking log or the persisted state."""

    MEDIA_TYPE = "application/pdf"

    def __init__(self, content: bytes):
        self.content = content

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def __eq__(self, other):
        return isinstance(other, Pdf) and other.content == self.content

    def __repr__(self):
        return f"Pdf(sha256={self.digest[:12]}, {len(self.content)} bytes)"


@serde.serialize.register(Pdf)
async def _serialize_pdf(value: Pdf, serialization_context: serde.SerializationContext = None):
    """Async serializer that externalizes the payload to the object store.

    The ``await`` is the point of the whole exercise: the sync tracker calls this without
    awaiting and gets a coroutine back, which is why the async tracker is needed.
    """
    store = serialization_context.require_object_store()
    assert isinstance(store, AsyncArtifactStore), type(store)
    memo_key = f"pdf:{value.digest}"
    if memo_key in serialization_context.memo:
        ref = serialization_context.memo[memo_key]
    else:
        ref = await store.put_artifact(value.content, media_type=Pdf.MEDIA_TYPE)
        serialization_context.memo[memo_key] = ref
    return {serde.KEY: "async_pdf", "ref": serde.serialize(ref)}


@serde.deserializer.register("async_pdf")
async def _deserialize_pdf(value: dict, serialization_context: serde.SerializationContext = None):
    """Async deserializer that reads back from the object store and re-seeds the memo, so the
    first persist after a resume costs no upload."""
    store = serialization_context.require_object_store()
    ref = serde.deserialize(value["ref"])
    content = await ref.aread(store)
    pdf = Pdf(content)
    serialization_context.memo[f"pdf:{pdf.digest}"] = ref
    return pdf


# --- actions ------------------------------------------------------------------------------------


@action(reads=["counter"], writes=["counter", "doc"])
async def bump(state: State) -> State:
    """Increments a counter and stores a large payload -- unchanged across steps, so the
    hash-then-skip behavior is observable."""
    return state.update(counter=state["counter"] + 1, doc=Pdf(b"%PDF-1.4 fixed content" * 100))


@action(reads=["counter"], writes=["counter"])
async def bump_only(state: State) -> State:
    """Counter-only step, so the large payload stays untouched (and un-re-serialized)."""
    return state.update(counter=state["counter"] + 1)


@action(reads=[], writes=["counter"])
async def with_tracer_inputs(state: State, __tracer) -> State:
    """Uses the injected tracer, so the step's inputs contain ``__tracer`` -- which the tracker
    has to filter out before serializing."""
    with __tracer("probe"):
        pass
    return state.update(counter=1)


@action(reads=["counter"], writes=["counter"])
def bump_only_sync(state: State) -> State:
    """Synchronous counterpart of :py:func:`bump_only`, for the backwards-compatibility tests --
    a synchronous action cannot run under ``app.run()``."""
    return state.update(counter=state["counter"] + 1)


@action(reads=["counter"], writes=["counter", "doc"])
def bump_sync(state: State) -> State:
    """Synchronous counterpart of :py:func:`bump`, for the tests that run under ``app.run()``."""
    return state.update(counter=state["counter"] + 1, doc=Pdf(b"%PDF-1.4 fixed content" * 100))


@action(reads=["counter"], writes=["counter"])
async def fail_if_three(state: State) -> State:
    if state["counter"] >= 3:
        raise ValueError("boom")
    return state.update(counter=state["counter"] + 1)


# --- helpers ------------------------------------------------------------------------------------


def read_log(storage_dir: str, project: str, app_id: str) -> List[dict]:
    path = os.path.join(storage_dir, project, app_id, LocalTrackingClient.LOG_FILENAME)
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f.readlines() if line.strip()]


def begin_entries(lines: List[dict]) -> List[dict]:
    return [line for line in lines if line["type"] == "begin_entry"]


def end_entries(lines: List[dict]) -> List[dict]:
    return [line for line in lines if line["type"] == "end_entry"]


def action_name(fn) -> str:
    """``@action`` returns the function itself (the action lives on an attribute), so the name
    used by the graph is the function name."""
    return fn.__name__


def build_async_app(
    storage_dir: str,
    store,
    *,
    project: str = "test_project",
    app_id: str = "app-1",
    persister=None,
    initialize_from=None,
    use_otel_tracing: bool = False,
    with_object_store_first: bool = False,
    build_method: str = "abuild",
    actions: Tuple = (bump,),
    extra_kwargs: Optional[dict] = None,
):
    """Builds the primary test application, exercising the builder in either call order."""
    builder = (
        ApplicationBuilder()
        .with_actions(*actions)
        .with_transitions(*[(action_name(actions[0]), action_name(a)) for a in actions[1:]])
        .with_identifiers(app_id=app_id)
    )
    # `initialize_from` rejects a builder that already has state/entrypoint, so the resuming
    # variant of the app has to omit both.
    if initialize_from is None:
        builder = builder.with_state(counter=0).with_entrypoint(action_name(actions[0]))

    def add_tracker():
        builder.with_tracker(
            "local",
            project=project,
            params={"storage_dir": storage_dir, **(extra_kwargs or {})},
            use_otel_tracing=use_otel_tracing,
        )

    def add_store():
        builder.with_object_store(store)

    if with_object_store_first:
        add_store()
        add_tracker()
    else:
        add_tracker()
        add_store()

    if persister is not None:
        builder.with_state_persister(persister)
    if initialize_from is not None:
        builder.initialize_from(
            initialize_from,
            resume_at_next_action=True,
            default_state={"counter": 0},
            default_entrypoint=action_name(actions[0]),
        )
    return builder


async def build_and_run(**kwargs):
    halt_after = kwargs.pop("halt_after", None)
    builder = build_async_app(**kwargs)
    app = await builder.abuild()
    actions = kwargs.get("actions", (bump,))
    await app.arun(halt_after=halt_after or [action_name(actions[-1])])
    return app


# --- the async client in isolation ---------------------------------------------------------------


class TestAsyncClientHooks:
    def test_is_an_async_tracking_client_but_not_a_sync_one(self):
        """The double-dispatch hazard: the class must not register both hook families."""
        client = AsyncLocalTrackingClient("p", "storage_dir")

        assert isinstance(client, AsyncTrackingClient)
        assert not isinstance(client, SyncTrackingClient)

    def test_hooks_are_registered_exactly_once(self):
        """Asynchronous applications dispatch sync *and* async hooks, so each hook must appear in
        exactly one family -- otherwise every step is logged twice."""
        adapter_set = LifecycleAdapterSet(AsyncLocalTrackingClient("p", "storage_dir"))

        # step + stream hooks: async only (they are dispatched to both families)
        for hook in ("pre_run_step", "post_run_step"):
            assert hook not in adapter_set.sync_hooks
            assert len(adapter_set.async_hooks[hook]) == 1
        for hook in ("pre_start_stream", "post_stream_item", "post_end_stream"):
            assert hook not in adapter_set.async_hooks
            assert len(adapter_set.sync_hooks[hook]) == 1
        # everything else: sync only (that is how Burr dispatches it)
        for hook in (
            "post_application_create",
            "pre_start_span",
            "post_end_span",
            "do_log_attributes",
        ):
            assert len(adapter_set.sync_hooks[hook]) == 1
            assert hook not in adapter_set.async_hooks

    async def test_step_hooks_are_coroutines(self):
        client = AsyncLocalTrackingClient("p", "storage_dir")

        assert asyncio.iscoroutinefunction(client.pre_run_step)
        assert asyncio.iscoroutinefunction(client.post_run_step)

    async def test_writes_the_documented_log_schema(self, tmp_path):
        """Same schema as the synchronous client: the tracking UI must not need a new format."""
        app = await build_and_run(
            storage_dir=str(tmp_path), store=CountingAsyncStore(), halt_after=["bump"]
        )
        lines = read_log(str(tmp_path), "test_project", "app-1")
        entries = begin_entries(lines)
        ends = end_entries(lines)

        assert len(entries) == 1
        assert len(ends) == 1
        assert entries[0]["type"] == "begin_entry"
        assert entries[0]["action"] == "bump"
        assert entries[0]["sequence_id"] == ends[0]["sequence_id"]
        assert ends[0]["exception"] is None
        # Pydantic models validate, which is what the UI relies on
        BeginEntryModel.model_validate(entries[0])
        EndEntryModel.model_validate(ends[0])
        assert app.builder.tracker.__class__ is AsyncLocalTrackingClient

    async def test_log_holds_references_not_raw_payloads(self, tmp_path):
        store = CountingAsyncStore()
        await build_and_run(storage_dir=str(tmp_path), store=store, halt_after=["bump"])
        lines = read_log(str(tmp_path), "test_project", "app-1")
        raw = json.dumps(lines)

        # the payload lives in the store, the log only carries a reference
        assert len(store.data) == 1
        ref_payload = next(iter(store.data.values()))
        assert ref_payload not in raw.encode()
        assert "sha256" in raw or "ref" in raw
        assert len(raw) < len(ref_payload) + 4000  # no 100x-blowup from inlined bytes

    async def test_input_filtering_is_preserved(self, tmp_path):
        """``__tracer`` is stripped from inputs before serialization, as the sync client does.

        The action is defined at module scope: inside the test class, ``__tracer`` would be
        name-mangled into ``_TestAsyncClientHooks__tracer`` and Burr would treat it as a required
        input instead of the injected tracer.
        """
        builder = (
            ApplicationBuilder()
            .with_actions(with_tracer_inputs)
            .with_state(counter=0)
            .with_entrypoint("with_tracer_inputs")
            .with_identifiers(app_id="filter-app")
            .with_tracker("local", project="filter-project", params={"storage_dir": str(tmp_path)})
            .with_object_store(CountingAsyncStore())
        )
        app = await builder.abuild()
        await app.arun(halt_after=["with_tracer_inputs"])
        entries = begin_entries(read_log(str(tmp_path), "filter-project", "filter-app"))

        assert entries[0]["inputs"] == {}

    async def test_serialization_context_is_propagated_to_the_tracker(self, tmp_path):
        """The tracker's serializer must see the application's context (i.e. its object store and
        its memo) -- not a fresh one, or the memo would not be shared with the persister."""
        store = CountingAsyncStore()
        await build_and_run(storage_dir=str(tmp_path), store=store, halt_after=["bump"])

        # exactly one upload: the tracker and the persister share the same memo
        assert len(store.put_calls) == 1

    def test_copy_returns_a_fresh_client_with_the_same_config(self):
        client = AsyncLocalTrackingClient(
            "foo", "storage_dir", serde_kwargs={"foo": "bar", "serialization_context": None}
        )
        copied = client.copy()

        assert copied is not client
        assert copied.project_id == client.project_id
        assert copied.storage_dir == client.storage_dir
        assert copied.raw_storage_dir == client.raw_storage_dir
        assert copied.serde_kwargs == client.serde_kwargs
        # fresh per-application state -- no shared file handle, no shared stream state
        assert copied.f is None
        assert copied.stream_state is not client.stream_state

    async def test_copy_does_not_share_the_open_log_handle(self, tmp_path):
        app = await build_and_run(
            storage_dir=str(tmp_path), store=CountingAsyncStore(), halt_after=["bump"]
        )
        tracker = app.builder.tracker
        assert tracker.f is not None

        copied = tracker.copy()
        assert copied.f is None
        assert copied is not tracker

    async def test_list_app_ids_matches_the_sync_client(self):
        client = AsyncLocalTrackingClient("p", "storage_dir")
        sync_client = LocalTrackingClient("p", "storage_dir")

        assert await client.list_app_ids("pk") == sync_client.list_app_ids("pk") == []


# --- end to end ---------------------------------------------------------------------------------


class TestEndToEnd:
    async def test_async_type_based_serde_end_to_end(self, tmp_path):
        """Primary scenario: async store + async type serde + tracker + abuild + arun."""
        store = CountingAsyncStore()
        app = await build_and_run(
            storage_dir=str(tmp_path),
            store=store,
            actions=(bump, bump_only),
            halt_after=["bump_only"],
        )

        lines = read_log(str(tmp_path), "test_project", "app-1")
        assert len(begin_entries(lines)) == 2
        assert len(end_entries(lines)) == 2
        # no coroutine leaked into the log
        assert "coroutine" not in json.dumps(lines)
        # the pdf round-trips through the store
        assert len(store.data) == 1
        # and the run actually completed both steps
        assert app.state["counter"] == 2
        assert isinstance(app.state["doc"], Pdf)

    async def test_async_field_based_serde(self, tmp_path, monkeypatch):
        """Field serde registered as ``async def`` must be awaited by the tracker too."""
        calls = []

        class Wrapped:
            def __init__(self, value: str):
                self.value = value

        def _sync_field_ser(value, **kwargs):
            raise AssertionError("the sync field serializer must not be used by the async client")

        async def _afield_ser(value, serialization_context=None, **kwargs):
            calls.append(("ser", value.value))
            store = serialization_context.require_object_store()
            ref = await store.put_artifact(value.value.encode(), media_type="text/plain")
            return {serde.KEY: "async_field_wrapped", "ref": serde.serialize(ref)}

        async def _afield_de(value, serialization_context=None, **kwargs):
            calls.append(("de", None))
            store = serialization_context.require_object_store()
            content = await serde.deserialize(value["ref"]).aread(store)
            return Wrapped(content.decode())

        from burr.core.state import FIELD_SERIALIZATION

        # Patch the registry entry directly: register_field_serde takes one pair, and we want the
        # sync serializer to be provably unused.
        monkeypatch.setitem(FIELD_SERIALIZATION, "wrapped", (_afield_ser, _afield_de))

        @action(reads=[], writes=["wrapped"])
        async def set_wrapped(state: State) -> State:
            return state.update(wrapped=Wrapped("field payload"))

        store = CountingAsyncStore()
        builder = (
            ApplicationBuilder()
            .with_actions(set_wrapped)
            .with_state(State())
            .with_entrypoint("set_wrapped")
            .with_identifiers(app_id="field-app")
            .with_tracker("local", project="field-project", params={"storage_dir": str(tmp_path)})
            .with_object_store(store)
        )
        app = await builder.abuild()
        await app.arun(halt_after=["set_wrapped"])

        ends = end_entries(read_log(str(tmp_path), "field-project", "field-app"))
        # the async serializer ran (the sync one would have raised), and was awaited
        assert ("ser", "field payload") in calls
        assert ends[0]["state"]["wrapped"][serde.KEY] == "async_field_wrapped"
        assert len(store.data) == 1

    async def test_exactly_once_tracking(self, tmp_path):
        """One begin/end pair per step, in order, no duplicates."""
        store = CountingAsyncStore()
        builder = build_async_app(
            storage_dir=str(tmp_path),
            store=store,
            actions=(bump, bump_only),
            app_id="exactly-once",
        )
        app = await builder.abuild()
        await app.arun(halt_after=["bump_only"])

        lines = read_log(str(tmp_path), "test_project", "exactly-once")
        begins = begin_entries(lines)
        ends = end_entries(lines)

        assert [b["sequence_id"] for b in begins] == [0, 1]
        assert [e["sequence_id"] for e in ends] == [0, 1]
        assert [b["action"] for b in begins] == ["bump", "bump_only"]
        # interleaved begin/end, one pair per step
        assert [line["type"] for line in lines if "entry" in line["type"]] == [
            "begin_entry",
            "end_entry",
            "begin_entry",
            "end_entry",
        ]

    async def test_hash_then_skip(self, tmp_path):
        """An unchanged PDF across N steps is uploaded once, then never touched."""
        store = CountingAsyncStore()
        builder = build_async_app(
            storage_dir=str(tmp_path),
            store=store,
            actions=(bump, bump_only),
            app_id="hash-skip",
        )
        app = await builder.abuild()
        await app.arun(halt_after=["bump_only"])

        assert len(store.put_calls) == 1
        # subsequent steps read nothing back for the unchanged value either
        assert store.get_calls == []

    async def test_resume_through_the_async_tracker(self, tmp_path):
        """Resume via the async loader: the deserializer seeds the memo, so the first persist
        after the resume uploads nothing again."""
        store = CountingAsyncStore()
        storage_dir = str(tmp_path)
        # Two actions, so that resuming at "the next action" still has somewhere to go.
        actions = (bump, bump_only)

        builder = build_async_app(
            storage_dir=storage_dir, store=store, app_id="resume-app", actions=actions
        )
        app = await builder.abuild()
        await app.arun(halt_after=["bump"])
        assert len(store.put_calls) == 1

        # Resume, reusing the same store (as a real deployment would)
        tracker = AsyncLocalTrackingClient("test_project", storage_dir)
        builder2 = build_async_app(
            storage_dir=storage_dir,
            store=store,
            app_id="resume-app",
            actions=actions,
            initialize_from=tracker,
        )
        app2 = await builder2.abuild()
        assert app2.state["counter"] == 1
        assert isinstance(app2.state["doc"], Pdf)
        # the deserializer re-seeded the memo -- no new upload
        assert len(store.put_calls) == 1

        await app2.arun(halt_after=["bump_only"])
        assert app2.state["counter"] == 2
        # still one upload: the value was unchanged
        assert len(store.put_calls) == 1

    async def test_resume_from_a_log_written_by_the_sync_client(self, tmp_path):
        """The two clients share the log format, so either can resume the other's log."""
        storage_dir = str(tmp_path)
        sync_client = LocalTrackingClient("sync_project", storage_dir)

        builder = (
            ApplicationBuilder()
            .with_actions(bump_only_sync)
            .with_state(counter=0)
            .with_entrypoint("bump_only_sync")
            .with_identifiers(app_id="cross-app")
            .with_tracker(sync_client)
        )
        app = builder.build()
        app.run(halt_after=["bump_only_sync"])

        async_tracker = AsyncLocalTrackingClient("sync_project", storage_dir)
        loaded = await async_tracker.load(partition_key=None, app_id="cross-app")

        assert loaded is not None
        # PersistedStateData is a TypedDict, i.e. a plain dict
        assert loaded["state"]["counter"] == 1
        assert loaded["position"] == "bump_only_sync"
        assert loaded["status"] == "completed"

    async def test_async_persister_and_tracker_share_the_memo(self, tmp_path):
        """The persister and the tracker must serialize through the same context -- otherwise the
        same payload is uploaded twice per step."""
        store = CountingAsyncStore()

        class _NullPersister(AsyncBaseStatePersister):
            def __init__(self):
                self.saved = []

            async def save(
                self,
                partition_key,
                app_id,
                sequence_id,
                position,
                state,
                status="completed",
                **kwargs,
            ):
                self.saved.append(
                    (
                        sequence_id,
                        await state.aserialize(**serde.with_serialization_context(kwargs)),
                    )
                )

            async def list_app_ids(self, partition_key, **kwargs):
                return []

            async def load(self, partition_key, app_id, sequence_id=None, **kwargs):
                return None

        persister = _NullPersister()
        builder = build_async_app(
            storage_dir=str(tmp_path),
            store=store,
            app_id="persist-app",
            actions=(bump, bump_only),
            persister=persister,
        )
        app = await builder.abuild()
        await app.arun(halt_after=["bump_only"])

        assert len(persister.saved) == 2
        # one upload total, shared between the tracker's end_entry and the persister's save
        assert len(store.put_calls) == 1


# --- builder selection --------------------------------------------------------------------------


class TestBuilderSelection:
    @pytest.mark.parametrize("store_first", [True, False])
    async def test_async_store_selects_the_async_client(self, tmp_path, store_first):
        builder = build_async_app(
            storage_dir=str(tmp_path),
            store=CountingAsyncStore(),
            with_object_store_first=store_first,
        )
        app = await builder.abuild()

        assert isinstance(app.builder.tracker, AsyncLocalTrackingClient)

    async def test_sync_store_keeps_the_sync_client(self, tmp_path):
        builder = build_async_app(storage_dir=str(tmp_path), store=CountingSyncStore())
        app = builder.build()

        assert type(app.builder.tracker) is LocalTrackingClient

    async def test_no_object_store_keeps_the_sync_client(self, tmp_path):
        builder = build_async_app(storage_dir=str(tmp_path), store=None)
        app = builder.build()

        assert type(app.builder.tracker) is LocalTrackingClient

    async def test_no_object_store_keeps_the_sync_client_on_abuild(self, tmp_path):
        builder = build_async_app(storage_dir=str(tmp_path), store=None)
        app = await builder.abuild()

        assert type(app.builder.tracker) is LocalTrackingClient

    async def test_build_plus_arun_with_an_async_store_uses_the_async_client(self, tmp_path):
        """``build()`` + ``arun()`` is a supported combination (sync persister, async execution),
        and an async store can be attached through ``build()`` -- so the async client must be
        selected here too, or that execution path is silently broken."""
        store = CountingAsyncStore()
        builder = build_async_app(storage_dir=str(tmp_path), store=store)
        app = builder.build()

        assert isinstance(app.builder.tracker, AsyncLocalTrackingClient)

        await app.arun(halt_after=["bump"])
        lines = read_log(str(tmp_path), "test_project", "app-1")
        assert len(end_entries(lines)) == 1
        assert len(store.data) == 1

    async def test_explicit_sync_client_is_not_replaced(self, tmp_path):
        store = CountingAsyncStore()
        explicit = LocalTrackingClient("explicit", str(tmp_path))
        builder = (
            ApplicationBuilder()
            .with_actions(bump)
            .with_state(counter=0)
            .with_entrypoint("bump")
            .with_identifiers(app_id="explicit-app")
            .with_tracker(explicit)
            .with_object_store(store)
        )
        app = await builder.abuild()

        assert app.builder.tracker is explicit

    async def test_explicit_async_client_is_not_replaced(self, tmp_path):
        explicit = AsyncLocalTrackingClient("explicit", str(tmp_path))
        builder = (
            ApplicationBuilder()
            .with_actions(bump)
            .with_state(counter=0)
            .with_entrypoint("bump")
            .with_tracker(explicit)
        )
        app = builder.build()

        assert app.builder.tracker is explicit

    async def test_params_are_rejected_for_explicit_instances(self, tmp_path):
        explicit = LocalTrackingClient("explicit", str(tmp_path))
        builder = ApplicationBuilder().with_actions(bump)

        with pytest.raises(ValueError, match="Params are not supported"):
            builder.with_tracker(explicit, params={"x": 1})

    async def test_unknown_string_tracker_is_rejected(self):
        builder = ApplicationBuilder().with_actions(bump)

        with pytest.raises(ValueError, match="not supported"):
            builder.with_tracker("s3")

    async def test_tracker_is_not_instantiated_until_build(self, tmp_path):
        """The selection has to be deferred -- otherwise ``with_tracker`` before
        ``with_object_store`` could not see the store."""
        builder = build_async_app(storage_dir=str(tmp_path), store=CountingAsyncStore())

        assert builder.tracker is None

    async def test_builder_holds_the_resolved_client_after_build(self, tmp_path):
        builder = build_async_app(storage_dir=str(tmp_path), store=CountingAsyncStore())
        app = await builder.abuild()

        assert builder.tracker is app.builder.tracker
        assert isinstance(builder.tracker, AsyncLocalTrackingClient)

    async def test_building_twice_does_not_duplicate_the_adapter(self, tmp_path):
        builder = build_async_app(storage_dir=str(tmp_path), store=CountingAsyncStore())
        first = await builder.abuild()
        n_adapters = len(first._adapter_set.adapters)
        second = await builder.abuild()

        assert len(second._adapter_set.adapters) == n_adapters


# --- backward compatibility ---------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_sync_client_class_identity_is_unchanged(self):
        assert issubclass(LocalTrackingClient, SyncTrackingClient)
        assert not issubclass(LocalTrackingClient, AsyncTrackingClient)

    def test_sync_client_registers_only_sync_hooks(self, tmp_path):
        adapter_set = LifecycleAdapterSet(LocalTrackingClient("p", str(tmp_path)))

        assert adapter_set.async_hooks == {}
        assert len(adapter_set.sync_hooks["pre_run_step"]) == 1
        assert len(adapter_set.sync_hooks["post_run_step"]) == 1

    def test_sync_application_logs_the_same_schema(self, tmp_path):
        builder = (
            ApplicationBuilder()
            .with_actions(bump_only_sync)
            .with_state(counter=0)
            .with_entrypoint("bump_only_sync")
            .with_identifiers(app_id="sync-app")
            .with_tracker("local", project="sync", params={"storage_dir": str(tmp_path)})
        )
        app = builder.build()
        app.run(halt_after=["bump_only_sync"])

        lines = read_log(str(tmp_path), "sync", "sync-app")
        assert len(begin_entries(lines)) == 1
        assert len(end_entries(lines)) == 1
        assert type(app.builder.tracker) is LocalTrackingClient

    def test_sync_store_serialization_still_works(self, tmp_path, monkeypatch):
        """A synchronous store keeps the sync tracker, and the tracker's serializers see that
        store. This pins that adding the async path did not change the sync one."""
        store = CountingSyncStore()

        def _sync_serialize_pdf(value, serialization_context=None, **kwargs):
            ref = serialization_context.require_object_store().put_artifact(value.content)
            return {serde.KEY: "sync_pdf", "ref": serde.serialize(ref)}

        def _sync_deserialize_pdf(value, serialization_context=None, **kwargs):
            return Pdf(serde.deserialize(value["ref"]).read(serialization_context.object_store))

        # Override the module-level async registration for the duration of this test. The
        # singledispatch registry is a read-only mappingproxy, so we register/unregister rather
        # than patch it.
        from burr.core import serde as serde_module

        serde_module.serialize.register(Pdf, _sync_serialize_pdf)
        monkeypatch.setitem(serde_module.deserializer.func_map, "sync_pdf", _sync_deserialize_pdf)
        serde_module._clear_serialize_cache()
        try:
            builder = (
                ApplicationBuilder()
                .with_actions(bump_sync)
                .with_state(counter=0)
                .with_entrypoint("bump_sync")
                .with_identifiers(app_id="sync-store-app")
                .with_tracker("local", project="sync", params={"storage_dir": str(tmp_path)})
                .with_object_store(store)
            )
            app = builder.build()
            app.run(halt_after=["bump_sync"])

            assert type(app.builder.tracker) is LocalTrackingClient
            assert len(store.put_calls) == 1
            lines = read_log(str(tmp_path), "sync", "sync-store-app")
            ends = end_entries(lines)
            assert ends
            assert ends[0]["state"]["doc"][serde.KEY] == "sync_pdf"
        finally:
            # Restore the module-level async registration the other tests rely on.
            serde_module.serialize.register(Pdf, _serialize_pdf)
            serde_module._clear_serialize_cache()


# --- OpenTelemetry ------------------------------------------------------------------------------


class TestOpenTelemetry:
    async def test_otel_selects_the_async_wrapper(self, tmp_path):
        builder = build_async_app(
            storage_dir=str(tmp_path), store=CountingAsyncStore(), use_otel_tracing=True
        )
        app = await builder.abuild()

        tracker = app.builder.tracker
        assert type(tracker) is AsyncOpenTelemetryTracker
        assert isinstance(tracker.burr_tracker, AsyncLocalTrackingClient)

    async def test_otel_with_sync_store_keeps_the_sync_wrapper(self, tmp_path):
        builder = build_async_app(
            storage_dir=str(tmp_path), store=CountingSyncStore(), use_otel_tracing=True
        )
        app = builder.build()

        tracker = app.builder.tracker
        assert type(tracker) is OpenTelemetryTracker
        assert type(tracker.burr_tracker) is LocalTrackingClient

    async def test_async_wrapper_rejects_a_sync_tracker(self, tmp_path):
        with pytest.raises(ValueError, match="synchronous step hooks"):
            AsyncOpenTelemetryTracker(burr_tracker=LocalTrackingClient("p", str(tmp_path)))

    async def test_full_builder_path_with_otel(self, tmp_path, monkeypatch):
        """Span creation, completion, delegation and cleanup through the real builder path."""
        import logging

        from burr.integrations import opentelemetry as otel_module

        started, ended = [], []
        original_start = otel_module._enter_span_with_token
        original_exit = otel_module._exit_span_direct
        # ``_end_span`` exists only when the optional action_scope boundary is present; in that
        # mode the scope has already restored the context, so the span is ended without a detach.
        original_end = getattr(otel_module, "_end_span", None)

        def spy_start(name, tracer):
            span, token = original_start(name, tracer)
            started.append(name)
            return span, token

        def spy_exit(span, token, exc=None):
            result = original_exit(span, token, exc)
            ended.append(True)
            return result

        def spy_end(span, exc=None):
            result = original_end(span, exc)
            ended.append(True)
            return result

        # The span must be closed exactly once, through whichever helper the strategy uses.
        monkeypatch.setattr(otel_module, "_enter_span_with_token", spy_start)
        monkeypatch.setattr(otel_module, "_exit_span_direct", spy_exit)
        if original_end is not None:
            monkeypatch.setattr(otel_module, "_end_span", spy_end)

        # A failed context detach is logged by OpenTelemetry itself; a passing test must prove
        # there were none, not merely that the span ended.
        detach_errors = []

        class _Capture(logging.Handler):
            def emit(self, record):
                if "Failed to detach context" in record.getMessage():
                    detach_errors.append(record)

        handler = _Capture()
        ctx_logger = logging.getLogger("opentelemetry.context")
        ctx_logger.addHandler(handler)
        ctx_logger.setLevel(logging.DEBUG)
        try:
            store = CountingAsyncStore()
            builder = build_async_app(
                storage_dir=str(tmp_path), store=store, use_otel_tracing=True, app_id="otel-app"
            )
            app = await builder.abuild()
            await app.arun(halt_after=["bump"])
        finally:
            ctx_logger.removeHandler(handler)

        # the step span was opened for the action name and closed again, exactly once
        assert started == ["bump"]
        assert len(ended) == 1
        assert detach_errors == []
        # the tracker context is cleared at the end of the step
        assert otel_module.tracker_context.get() is None
        # and the underlying log was written exactly once
        lines = read_log(str(tmp_path), "test_project", "otel-app")
        assert len(begin_entries(lines)) == 1
        assert len(end_entries(lines)) == 1

    async def test_otel_delegates_to_the_async_tracker(self, tmp_path):
        store = CountingAsyncStore()
        builder = build_async_app(
            storage_dir=str(tmp_path), store=store, use_otel_tracing=True, app_id="otel-delegate"
        )
        app = await builder.abuild()
        tracker = app.builder.tracker
        calls = []

        original = tracker.burr_tracker.pre_run_step

        async def spy(**kwargs):
            calls.append("pre")
            return await original(**kwargs)

        tracker.burr_tracker.pre_run_step = spy
        await app.arun(halt_after=["bump"])

        assert calls == ["pre"]
        assert len(store.data) == 1

    async def test_otel_copy_wraps_an_async_copy(self, tmp_path):
        builder = build_async_app(
            storage_dir=str(tmp_path), store=CountingAsyncStore(), use_otel_tracing=True
        )
        app = await builder.abuild()
        copied = app.builder.tracker.copy()

        assert type(copied) is AsyncOpenTelemetryTracker
        assert isinstance(copied.burr_tracker, AsyncLocalTrackingClient)
        assert copied.burr_tracker is not app.builder.tracker.burr_tracker

    async def test_otel_does_not_double_log(self, tmp_path):
        builder = build_async_app(
            storage_dir=str(tmp_path),
            store=CountingAsyncStore(),
            use_otel_tracing=True,
            actions=(bump, bump_only),
            app_id="otel-once",
        )
        app = await builder.abuild()
        await app.arun(halt_after=["bump_only"])

        lines = read_log(str(tmp_path), "test_project", "otel-once")
        assert len(begin_entries(lines)) == 2
        assert len(end_entries(lines)) == 2


# --- failures and cancellation ------------------------------------------------------------------


class TestFailures:
    async def test_failed_step_is_logged_once_with_the_exception(self, tmp_path):
        store = CountingAsyncStore()
        builder = (
            ApplicationBuilder()
            .with_actions(fail_if_three)
            .with_state(counter=3)
            .with_entrypoint("fail_if_three")
            .with_identifiers(app_id="fail-app")
            .with_tracker("local", project="test_project", params={"storage_dir": str(tmp_path)})
            .with_object_store(store)
        )
        app = await builder.abuild()
        with pytest.raises(ValueError, match="boom"):
            await app.arun(halt_after=["fail_if_three"])

        lines = read_log(str(tmp_path), "test_project", "fail-app")
        ends = end_entries(lines)
        # exactly one step ran, and it produced exactly one begin/end pair carrying the error
        assert len(begin_entries(lines)) == 1, begin_entries(lines)
        assert len(ends) == 1, ends
        assert ends[0]["exception"] is not None
        assert "boom" in ends[0]["exception"]
        assert ends[0]["action"] == "fail_if_three"

    async def test_cancellation_does_not_leak_coroutines(self, tmp_path):
        store = CountingAsyncStore()

        @action(reads=[], writes=["counter"])
        async def slow(state: State) -> State:
            await asyncio.sleep(5)
            return state.update(counter=1)

        builder = (
            ApplicationBuilder()
            .with_actions(slow)
            .with_state(counter=0)
            .with_entrypoint("slow")
            .with_identifiers(app_id="cancel-app")
            .with_tracker("local", project="cancel-project", params={"storage_dir": str(tmp_path)})
            .with_object_store(store)
        )
        app = await builder.abuild()
        task = asyncio.ensure_future(app.arun(halt_after=["slow"]))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # The begin_entry was written before the action started. `post_run_step` runs in a
        # `finally`, so the cancelled step is still closed out -- exactly once -- rather than
        # leaving a dangling begin entry. `CancelledError` is a `BaseException`, so Burr does not
        # record it in `exception` (unchanged upstream behavior); the interesting guarantee here
        # is that logging neither duplicates nor drops the step, and nothing is left un-awaited.
        lines = read_log(str(tmp_path), "cancel-project", "cancel-app")
        begins = begin_entries(lines)
        ends = end_entries(lines)
        assert len(begins) == 1, begins
        assert len(ends) == 1, ends
        assert ends[0]["action"] == "slow"
        assert not any(asyncio.iscoroutine(obj) for obj in vars(app.builder.tracker).values())


# --- MapStates / copy ---------------------------------------------------------------------------


class TestCopyAndParallelism:
    async def test_cascade_copies_the_async_tracker(self, tmp_path):
        """``MapStates(..., tracker="cascade")`` goes through ``_cascade_adapter``, which calls
        ``copy()``. The copy has to be a *new* client with its own file handle, never the parent
        instance -- otherwise parallel sub-apps would interleave writes into one handle.

        Note: running a ``MapStates`` graph whose sub-tasks use an ``AsyncArtifactStore`` is not
        supported (sub-tasks execute through Burr's synchronous step path, which rejects async
        stores), so this pins the ``copy()`` contract the cascade path depends on.
        """
        from burr.core.parallelism import _cascade_adapter

        parent = AsyncLocalTrackingClient("cascade-project", str(tmp_path))
        # Build a real application so `post_application_create` gets a real graph (it writes the
        # graph/metadata files) and opens the log too, as a running application would.
        builder = (
            ApplicationBuilder()
            .with_actions(bump)
            .with_state(counter=0)
            .with_entrypoint("bump")
            .with_identifiers(app_id="cascade-app")
            .with_tracker(parent)
            .with_object_store(CountingAsyncStore())
        )
        await builder.abuild()
        assert parent.f is not None

        child = _cascade_adapter("cascade", parent)
        assert child is not parent
        assert type(child) is AsyncLocalTrackingClient
        assert child.f is None, "the copy must not inherit the parent's open handle"
        assert child._copy_kwargs() == parent._copy_kwargs()

        # The copy opens its own handle when its own application is created.
        child_builder = (
            ApplicationBuilder()
            .with_actions(bump)
            .with_state(counter=0)
            .with_entrypoint("bump")
            .with_identifiers(app_id="cascade-child")
            .with_tracker(child)
            .with_object_store(CountingAsyncStore())
        )
        await child_builder.abuild()
        assert child.f is not None
        assert child.f is not parent.f

        # `None` behavior does not copy at all.
        assert _cascade_adapter(None, parent) is None
