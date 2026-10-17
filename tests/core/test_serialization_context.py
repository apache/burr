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

"""Tests for the serialization context: how the application's object store reaches type-based and
field-based serializers across persistence, resume, tracking, sub-applications, and async."""

import glob
import json
import os
import sqlite3
from typing import Any, Dict, Generator

import pytest

from burr.core import ApplicationBuilder, ApplicationContext, Result, State, action, serde
from burr.core.artifacts import ArtifactRef, AsyncArtifactStore, LocalFileSystemArtifactStore
from burr.core.parallelism import MapStates, RunnableGraph, SubgraphType
from burr.core.persistence import SQLitePersister
from burr.core.serde import SerializationContext
from burr.core.state import FIELD_SERIALIZATION, register_field_serde
from burr.tracking.client import LocalTrackingClient


class Blob:
    """Stands in for a large domain object (a PDF, a dataframe, ...). Its serde externalizes the
    bytes to the object store, and deserializes to a lazy Blob that loads them on first access."""

    def __init__(self, data: bytes = None, ref: ArtifactRef = None, store=None):
        self._data = data
        self.ref = ref
        self._store = store

    @property
    def data(self) -> bytes:
        if self._data is None:
            if self._store is None:
                raise ValueError("Blob was loaded without an object store, so it can't be read.")
            self._data = self.ref.read(self._store)
        return self._data


def _store_or_none(serialization_context: SerializationContext = None):
    return serialization_context.object_store if serialization_context is not None else None


@serde.serialize.register(Blob)
def _serialize_blob(value: Blob, serialization_context: SerializationContext = None, **kwargs):
    if serialization_context is None:
        raise ValueError("Blob requires an object store -- no serialization context was given.")
    # a lazily-loaded Blob already has a ref -- re-saving it must not download it
    ref = value.ref or serialization_context.require_object_store().put_artifact(value.data)
    return {serde.KEY: "test_blob", "ref": serde.serialize(ref)}


@serde.deserializer.register("test_blob")
def _deserialize_blob(
    value: dict, serialization_context: SerializationContext = None, **kwargs
) -> Blob:
    # no store needed to load -- only to read the data later
    return Blob(ref=serde.deserialize(value["ref"]), store=_store_or_none(serialization_context))


class AsyncBlob:
    """Same as Blob, for an AsyncArtifactStore -- reading the data is `await blob.load()`."""

    def __init__(self, data: bytes = None, ref: ArtifactRef = None, store=None):
        self._data = data
        self.ref = ref
        self._store = store

    async def load(self) -> bytes:
        if self._data is None:
            if self._store is None:
                raise ValueError("AsyncBlob was loaded without an object store.")
            self._data = await self.ref.aread(self._store)
        return self._data


@serde.serialize.register(AsyncBlob)
async def _serialize_async_blob(
    value: AsyncBlob, serialization_context: SerializationContext = None, **kwargs
):
    ref = value.ref or await serialization_context.require_object_store().put_artifact(
        await value.load()
    )
    return {serde.KEY: "test_async_blob", "ref": serde.serialize(ref)}


@serde.deserializer.register("test_async_blob")
def _deserialize_async_blob(
    value: dict, serialization_context: SerializationContext = None, **kwargs
) -> AsyncBlob:
    return AsyncBlob(
        ref=serde.deserialize(value["ref"]), store=_store_or_none(serialization_context)
    )


class CountingStore(LocalFileSystemArtifactStore):
    """Local store that records reads, so tests can assert loading state is lazy."""

    def __init__(self, root_dir: str):
        super().__init__(root_dir)
        self.gets = []

    def get(self, key: str) -> bytes:
        self.gets.append(key)
        return super().get(key)


class InMemoryAsyncStore(AsyncArtifactStore):
    def __init__(self):
        self.data: Dict[str, bytes] = {}

    async def put(self, data: bytes, key: str) -> bool:
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


REPORT_FIELD = "externalized_report"


def _serialize_report(value: str, serialization_context: SerializationContext = None, **kwargs):
    store = serialization_context.require_object_store()
    ref = store.put_artifact(value.encode(), media_type="text/plain")
    return {"ref": serde.serialize(ref)}


def _deserialize_report(value: dict, **kwargs) -> ArtifactRef:
    return serde.deserialize(value["ref"])


async def _aserialize_report(
    value: str, serialization_context: SerializationContext = None, **kwargs
):
    store = serialization_context.require_object_store()
    ref = await store.put_artifact(value.encode(), media_type="text/plain")
    return {"ref": serde.serialize(ref)}


async def _adeserialize_report(value: dict, **kwargs) -> ArtifactRef:
    return serde.deserialize(value["ref"])


@pytest.fixture
def report_field_serde():
    register_field_serde(REPORT_FIELD, _serialize_report, _deserialize_report)
    yield
    del FIELD_SERIALIZATION[REPORT_FIELD]


@pytest.fixture
def async_report_field_serde():
    register_field_serde(REPORT_FIELD, _aserialize_report, _adeserialize_report)
    yield
    del FIELD_SERIALIZATION[REPORT_FIELD]


@pytest.fixture
def store(tmp_path):
    return CountingStore(str(tmp_path / "blobs"))


BLOB_BYTES = b"%PDF " + b"x" * 10_000
REPORT_TEXT = "a long report " * 1_000


@action(reads=[], writes=["blob", REPORT_FIELD])
def produce(state: State) -> State:
    # note the action puts the *live values* in state -- serde externalizes them on save.
    return state.update(blob=Blob(BLOB_BYTES), **{REPORT_FIELD: REPORT_TEXT})


@action(reads=["blob"], writes=["blob_size"])
def consume(state: State) -> State:
    return state.update(blob_size=len(state["blob"].data))


def _build_app(store, persister=None, tracker=None, initialize=False, app_id="app"):
    builder = (
        ApplicationBuilder()
        .with_actions(produce, consume, result=Result("blob_size"))
        .with_transitions(("produce", "consume"), ("consume", "result"))
        .with_identifiers(app_id=app_id, partition_key="pk")
        .with_object_store(store)
    )
    if persister is not None:
        builder = builder.with_state_persister(persister)
    if tracker is not None:
        builder = builder.with_tracker(tracker)
    if initialize:
        builder = builder.initialize_from(
            persister,
            resume_at_next_action=True,
            default_state={},
            default_entrypoint="produce",
        )
    else:
        builder = builder.with_entrypoint("produce")
    return builder.build()


# --- unit-level behavior of the context ---


def test_serializers_receive_no_context_when_none_is_configured():
    seen = {}

    class Spy:
        pass

    @serde.serialize.register(Spy)
    def _serialize_spy(value, **kwargs):
        seen.update(kwargs)
        return {serde.KEY: "spy"}

    State({"spy": Spy()}).serialize(other_kwarg=1)
    assert seen == {"other_kwarg": 1}


def test_context_manager_makes_context_available_and_explicit_kwarg_wins(store):
    seen = []

    class Spy:
        pass

    @serde.serialize.register(Spy)
    def _serialize_spy(value, serialization_context=None, **kwargs):
        seen.append(serialization_context)
        return {serde.KEY: "spy"}

    ambient = SerializationContext(object_store=store)
    explicit = SerializationContext(object_store=None)
    with serde.serialization_context(ambient):
        assert serde.get_serialization_context() is ambient
        State({"spy": Spy()}).serialize()
        State({"spy": Spy()}).serialize(serialization_context=explicit)
    assert serde.get_serialization_context() is None
    assert seen == [ambient, explicit]


def test_require_object_store_raises_clear_error():
    with pytest.raises(ValueError, match="requires an object store"):
        SerializationContext().require_object_store()


def test_type_and_field_serde_roundtrip_through_explicit_context(store, report_field_serde):
    ctx = SerializationContext(object_store=store)
    serialized = State({"blob": Blob(BLOB_BYTES), REPORT_FIELD: REPORT_TEXT}).serialize(
        serialization_context=ctx
    )

    # only small references end up in the serialized state
    assert len(json.dumps(serialized)) < 1_000
    restored = State.deserialize(serialized, serialization_context=ctx)
    assert isinstance(restored["blob"], Blob)
    assert isinstance(restored[REPORT_FIELD], ArtifactRef)
    assert store.gets == []  # deserializing never fetches the bytes
    assert restored["blob"].data == BLOB_BYTES
    assert restored[REPORT_FIELD].read(store) == REPORT_TEXT.encode()


def test_lazy_values_load_without_a_context_and_fail_only_when_read(store):
    """Loading state outside a configured app (a user calling `persister.load()`, the CLI) must
    still work -- the store is only needed once the data is actually read."""
    serialized = State({"blob": Blob(BLOB_BYTES)}).serialize(
        serialization_context=SerializationContext(object_store=store)
    )

    restored = State.deserialize(serialized)

    assert restored["blob"].ref.size_bytes == len(BLOB_BYTES)
    # re-saving doesn't need the data either
    assert State.deserialize(restored.serialize(serialization_context=SerializationContext()))
    with pytest.raises(ValueError, match="loaded without an object store"):
        restored["blob"].data


def test_sync_serialize_rejects_async_type_serializer_with_clear_error():
    with pytest.raises(ValueError, match="asynchronous.*aserialize"):
        State({"blob": AsyncBlob(b"data")}).serialize()
    with pytest.raises(ValueError, match="asynchronous"):
        State({"nested": {"items": [AsyncBlob(b"data")]}}).serialize()


def test_sync_serialize_rejects_async_field_serializer_with_clear_error(async_report_field_serde):
    store = InMemoryAsyncStore()
    with pytest.raises(ValueError, match="field serializer .* is asynchronous"):
        State({REPORT_FIELD: "text"}).serialize(
            serialization_context=SerializationContext(object_store=store)
        )


async def test_aserialize_and_adeserialize_await_async_serde(async_report_field_serde):
    store = InMemoryAsyncStore()
    ctx = SerializationContext(object_store=store)
    state = State(
        {
            "blob": AsyncBlob(b"blob bytes"),
            "nested": {"items": [AsyncBlob(b"nested bytes"), 1]},
            REPORT_FIELD: "report",
            "plain": "value",
        }
    )

    serialized = await state.aserialize(serialization_context=ctx)
    restored = await State.adeserialize(serialized, serialization_context=ctx)

    assert await restored["blob"].load() == b"blob bytes"
    assert await restored["nested"]["items"][0].load() == b"nested bytes"
    assert restored["nested"]["items"][1] == 1
    assert await restored[REPORT_FIELD].aread(store) == b"report"
    assert restored["plain"] == "value"


async def test_aserialize_matches_serialize_for_sync_serde():
    state = State({"a": 1, "b": [1, {"c": "d"}], "e": None})
    assert await state.aserialize() == state.serialize()
    assert (await State.adeserialize(state.serialize())).get_all() == state.get_all()


# --- application-level propagation ---


def test_persister_and_resume_use_application_object_store(tmp_path, store, report_field_serde):
    db_path = str(tmp_path / "state.db")
    persister = SQLitePersister.from_values(db_path=db_path, table_name="t")
    persister.initialize()

    app = _build_app(store, persister=persister)
    *_, final_state = app.run(halt_after=["result"])
    assert final_state["blob_size"] == len(BLOB_BYTES)
    assert serde.get_serialization_context() is None  # nothing leaks out of the run

    # what was persisted is a small reference, not the payload
    raw = sqlite3.connect(db_path).execute("SELECT state FROM t ORDER BY sequence_id").fetchall()
    assert all(len(row[0]) < 2_000 for row in raw)
    assert "ArtifactRef" in raw[-1][0]

    # resuming loads references through the same store -- lazily
    store.gets.clear()
    resumed = _build_app(store, persister=persister, initialize=True)
    assert isinstance(resumed.state["blob"], Blob)
    assert isinstance(resumed.state[REPORT_FIELD], ArtifactRef)
    assert store.gets == []
    assert resumed.state["blob"].data == BLOB_BYTES
    assert resumed.state[REPORT_FIELD].read(store) == REPORT_TEXT.encode()


def test_resume_mid_graph_hands_actions_a_lazily_loaded_value(tmp_path, store):
    """The deserialized value must be usable by later actions just like the live one -- resuming
    before `consume` runs is exactly where returning a bare ArtifactRef would break."""
    persister = SQLitePersister.from_values(db_path=str(tmp_path / "state.db"), table_name="t")
    persister.initialize()
    _build_app(store, persister=persister).step()  # only `produce` runs

    store.gets.clear()
    resumed = _build_app(store, persister=persister, initialize=True)
    *_, final_state = resumed.run(halt_after=["result"])

    assert final_state["blob_size"] == len(BLOB_BYTES)
    # loaded once, by `consume` -- re-saving the lazy value afterwards doesn't download it again
    assert len(store.gets) == 1


def test_tracker_logs_attributes_through_application_object_store(tmp_path, store):
    @action(reads=[], writes=[])
    def log_blob(state: State, __tracer) -> State:
        __tracer.log_attributes(blob=Blob(b"attribute bytes"))
        return state

    tracker = LocalTrackingClient(project="ctx_attrs", storage_dir=str(tmp_path / "tracking"))
    app = (
        ApplicationBuilder()
        .with_actions(log_blob)
        .with_transitions()
        .with_entrypoint("log_blob")
        .with_object_store(store)
        .with_tracker(tracker)
        .with_identifiers(app_id="attrs")
        .build()
    )
    app.step()

    log_path = os.path.join(tmp_path, "tracking", "ctx_attrs", "attrs", "log.jsonl")
    attributes = [json.loads(line) for line in open(log_path) if '"attribute"' in line]
    logged = attributes[-1]["value"]
    assert serde.deserialize(logged["ref"]).read(store) == b"attribute bytes"


def test_sync_serializer_using_async_store_fails_clearly():
    """A plain `def` serializer calling an async store gets a coroutine back; that must not be
    persisted as its string representation."""

    class NeedsStore:
        pass

    @serde.serialize.register(NeedsStore)
    def _serialize_needs_store(value, serialization_context=None, **kwargs):
        ref = serialization_context.require_object_store().put_artifact(b"data")
        return {serde.KEY: "needs_store", "ref": serde.serialize(ref)}

    ctx = SerializationContext(object_store=InMemoryAsyncStore())
    with pytest.raises(ValueError, match="Cannot serialize a coroutine"):
        State({"value": NeedsStore()}).serialize(serialization_context=ctx)


def test_tracker_serializes_state_through_application_object_store(
    tmp_path, store, report_field_serde
):
    tracker = LocalTrackingClient(project="ctx_test", storage_dir=str(tmp_path / "tracking"))
    app = _build_app(store, tracker=tracker)
    app.run(halt_after=["result"])

    log_path = os.path.join(tmp_path, "tracking", "ctx_test", "app", "log.jsonl")
    end_entries = [
        json.loads(line) for line in open(log_path) if json.loads(line)["type"] == "end_entry"
    ]
    final_state = end_entries[-1]["state"]
    assert final_state["blob"][serde.KEY] == "test_blob"
    assert final_state[REPORT_FIELD]["ref"][serde.KEY] == "ArtifactRef"

    # the tracker doubles as a state loader -- it deserializes through the store too
    with serde.serialization_context(SerializationContext(object_store=store)):
        loaded = tracker.load("pk", "app")
    assert isinstance(loaded["state"]["blob"], Blob)


def test_tracker_uses_context_for_streaming_actions(tmp_path, store):
    from burr.core.action import streaming_action

    @streaming_action(reads=[], writes=["blob"])
    def stream_blob(state: State) -> Generator[dict, None, None]:
        yield {"chunk": 1}, None
        yield {}, state.update(blob=Blob(BLOB_BYTES))

    tracker = LocalTrackingClient(project="ctx_stream", storage_dir=str(tmp_path / "tracking"))
    app = (
        ApplicationBuilder()
        .with_actions(stream_blob)
        .with_transitions()
        .with_entrypoint("stream_blob")
        .with_object_store(store)
        .with_tracker(tracker)
        .with_identifiers(app_id="streaming")
        .build()
    )
    _, container = app.stream_result(halt_after=["stream_blob"])
    for _ in container:
        pass
    container.get()

    log_path = os.path.join(tmp_path, "tracking", "ctx_stream", "streaming", "log.jsonl")
    end_entries = [json.loads(line) for line in open(log_path) if '"end_entry"' in line]
    assert end_entries[-1]["state"]["blob"][serde.KEY] == "test_blob"


def test_without_object_store_externalizing_serde_fails_clearly(tmp_path):
    tracker = LocalTrackingClient(project="no_store", storage_dir=str(tmp_path / "tracking"))
    app = (
        ApplicationBuilder()
        .with_actions(produce)
        .with_transitions()
        .with_entrypoint("produce")
        .with_tracker(tracker)
        .build()
    )
    with pytest.raises(ValueError, match="requires an object store"):
        app.step()


def test_sub_applications_serialize_through_cascaded_object_store(tmp_path, store):
    @action(reads=["n"], writes=["blob"])
    def make_blob(state: State) -> State:
        return state.update(blob=Blob(b"child-%d" % state["n"]))

    class MapBlobs(MapStates):
        def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[State, None, None]:
            for n in range(3):
                yield state.update(n=n)

        def action(self, state: State, inputs: Dict[str, Any]) -> SubgraphType:
            return RunnableGraph.create(make_blob)

        def reduce(self, state: State, states: Generator[State, None, None]) -> State:
            return state.update(child_blobs=[s["blob"].data for s in states])

        @property
        def reads(self) -> list[str]:
            return []

        @property
        def writes(self) -> list[str]:
            return ["child_blobs"]

    tracker = LocalTrackingClient(project="ctx_children", storage_dir=str(tmp_path / "tracking"))
    app = (
        ApplicationBuilder()
        .with_actions(map_blobs=MapBlobs())
        .with_transitions()
        .with_entrypoint("map_blobs")
        .with_object_store(store)
        .with_tracker(tracker)
        .with_identifiers(app_id="parent")
        .build()
    )
    *_, final_state = app.run(halt_after=["map_blobs"])
    assert sorted(final_state["child_blobs"]) == [b"child-0", b"child-1", b"child-2"]

    child_logs = [
        path
        for path in glob.glob(str(tmp_path / "tracking" / "ctx_children" / "*" / "log.jsonl"))
        if os.path.basename(os.path.dirname(path)) != "parent"
    ]
    assert len(child_logs) == 3
    stored = set()
    for path in child_logs:
        entries = [json.loads(line) for line in open(path) if '"end_entry"' in line]
        blob = entries[-1]["state"]["blob"]
        assert blob[serde.KEY] == "test_blob"
        stored.add(serde.deserialize(blob["ref"]).read(store))
    assert stored == {b"child-0", b"child-1", b"child-2"}


# --- async ---


@action(reads=[], writes=["blob", REPORT_FIELD])
async def aproduce(state: State) -> State:
    return state.update(blob=AsyncBlob(BLOB_BYTES), **{REPORT_FIELD: REPORT_TEXT})


async def test_async_persister_and_resume_use_async_object_store(
    tmp_path, async_report_field_serde
):
    from burr.integrations.persisters.b_aiosqlite import AsyncSQLitePersister

    store = InMemoryAsyncStore()
    db_path = str(tmp_path / "async_state.db")

    async def build(persister, initialize: bool):
        builder = (
            ApplicationBuilder()
            .with_actions(aproduce, result=Result("blob"))
            .with_transitions(("aproduce", "result"))
            .with_identifiers(app_id="async_app", partition_key="pk")
            .with_object_store(store)
            .with_state_persister(persister)
        )
        if initialize:
            builder = builder.initialize_from(
                persister,
                resume_at_next_action=True,
                default_state={},
                default_entrypoint="aproduce",
            )
        else:
            builder = builder.with_entrypoint("aproduce")
        return await builder.abuild()

    async with AsyncSQLitePersister.from_values(db_path=db_path, table_name="t") as persister:
        await persister.initialize()
        app = await build(persister, initialize=False)
        await app.arun(halt_after=["result"])

        resumed = await build(persister, initialize=True)
        assert isinstance(resumed.state["blob"], AsyncBlob)
        assert await resumed.state["blob"].load() == BLOB_BYTES
        assert await resumed.state[REPORT_FIELD].aread(store) == REPORT_TEXT.encode()

    raw = sqlite3.connect(db_path).execute("SELECT state FROM t").fetchall()
    assert all(len(row[0]) < 2_000 for row in raw)


async def test_sync_tracker_with_async_serializer_fails_clearly(tmp_path):
    tracker = LocalTrackingClient(project="async_sync", storage_dir=str(tmp_path / "tracking"))
    app = await (
        ApplicationBuilder()
        .with_actions(aproduce)
        .with_transitions()
        .with_entrypoint("aproduce")
        .with_object_store(InMemoryAsyncStore())
        .with_tracker(tracker)
        .abuild()
    )
    with pytest.raises(ValueError, match="asynchronous"):
        await app.astep()
