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

import dataclasses
import glob
import hashlib
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
    state = State({"a": 1, "b": [1, {"c": "d"}], "e": None, "f": {serde.KEY: "user data"}})
    assert await state.aserialize() == state.serialize()
    assert (await State.adeserialize(state.serialize())).get_all() == state.get_all()


async def test_async_serde_round_trips_dicts_carrying_the_serde_marker_key():
    store = InMemoryAsyncStore()
    ctx = SerializationContext(object_store=store)
    state = State({"meta": {serde.KEY: "user data", "blob": AsyncBlob(b"nested")}})

    restored = await State.adeserialize(
        await state.aserialize(serialization_context=ctx), serialization_context=ctx
    )

    assert restored["meta"][serde.KEY] == "user data"
    assert await restored["meta"]["blob"].load() == b"nested"


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


# --- the per-application serialization context (one context per Application) ---
#
# A SerializationContext carries a `memo`, so its identity is now load-bearing: the load that
# resumes an application and every persist/track that application later does must run inside the
# *same* context, or anything the deserializer seeds is thrown away with the load-time object.
# One context per build, never a process-wide one.


class MemoBlob:
    """A large value whose serde externalizes bytes and caches the reference by content hash.

    This is the "hash-then-skip" pattern: hash in memory, check the memo, do I/O only on a miss.
    The memo holds the store-side fact (the ArtifactRef), not the payload, so per-value metadata
    (``name`` here) is always rebuilt from the live value -- two blobs with the same bytes but
    different metadata do not collapse onto one another.
    """

    def __init__(self, data: bytes, name: str = "blob"):
        self.data = data
        self.name = name

    def __eq__(self, other):
        return isinstance(other, MemoBlob) and (other.data, other.name) == (self.data, self.name)


class TrackedStore(LocalFileSystemArtifactStore):
    """Counts every backend call so a test can assert that an unchanged value costs nothing."""

    def __init__(self, root_dir: str):
        super().__init__(root_dir)
        self.ops = []

    def put(self, data, key):
        self.ops.append(("put", len(data)))
        return super().put(data, key)

    def get(self, key):
        data = super().get(key)
        self.ops.append(("get", len(data)))
        return data

    def exists(self, key):
        self.ops.append(("exists", 0))
        return super().exists(key)

    def digest(self, key):
        self.ops.append(("digest", 0))
        return super().digest(key)


class CountedAsyncStore(InMemoryAsyncStore):
    """In-memory async store that counts every backend call."""

    def __init__(self):
        super().__init__()
        self.ops = []

    async def put(self, data, key):
        self.ops.append(("put", len(data)))
        return await super().put(data, key)

    async def get(self, key):
        self.ops.append(("get", len(self.data.get(key, b""))))
        return await super().get(key)

    async def exists(self, key):
        self.ops.append(("exists", 0))
        return await super().exists(key)


def _register_memo_blob_serde(key: str) -> None:
    """Registers a hash-then-skip serde pair under a test-unique envelope key."""

    @serde.serialize.register(MemoBlob)
    def _serialize_memo_blob(value, serialization_context=None, **kwargs):
        h = hashlib.sha256(value.data).hexdigest()
        ref = serialization_context.memo.get(h)
        if ref is None:
            ref = serialization_context.require_object_store().put_artifact(value.data)
            serialization_context.memo[h] = ref
        return {serde.KEY: key, "ref": serde.serialize(ref), "name": value.name, "hash": h}

    @serde.deserializer.register(key)
    def _deserialize_memo_blob(value, serialization_context=None, **kwargs):
        ref = serde.deserialize(value["ref"])
        blob = MemoBlob(
            data=ref.read(serialization_context.require_object_store()), name=value["name"]
        )
        serialization_context.memo[value["hash"]] = ref
        return blob


def _register_async_memo_blob_serde(key: str) -> None:
    """Async counterpart of _register_memo_blob_serde -- same lifecycle guarantee."""

    @serde.serialize.register(MemoBlob)
    async def _serialize_memo_blob(value, serialization_context=None, **kwargs):
        h = hashlib.sha256(value.data).hexdigest()
        ref = serialization_context.memo.get(h)
        if ref is None:
            ref = await serialization_context.require_object_store().put_artifact(value.data)
            serialization_context.memo[h] = ref
        return {serde.KEY: key, "ref": serde.serialize(ref), "name": value.name, "hash": h}

    @serde.deserializer.register(key)
    async def _deserialize_memo_blob(value, serialization_context=None, **kwargs):
        ref = serde.deserialize(value["ref"])
        blob = MemoBlob(
            data=await ref.aread(serialization_context.require_object_store()),
            name=value["name"],
        )
        serialization_context.memo[value["hash"]] = ref
        return blob


MEMO_BYTES = b"a contract worth storing " * 20


@action(reads=[], writes=["memo_blob"])
def produce_memo(state: State) -> State:
    return state.update(memo_blob=MemoBlob(MEMO_BYTES, name="contract.pdf"))


@action(reads=["memo_blob"], writes=["memo_size"])
def consume_memo(state: State) -> State:
    return state.update(memo_size=len(state["memo_blob"].data))


@action(reads=[], writes=["memo_blob"])
async def aproduce_memo(state: State) -> State:
    return state.update(memo_blob=MemoBlob(MEMO_BYTES, name="contract.pdf"))


@action(reads=["memo_blob"], writes=["memo_size"])
async def aconsume_memo(state: State) -> State:
    return state.update(memo_size=len(state["memo_blob"].data))


SYNC_MEMO = {
    "actions": {"produce_memo": produce_memo, "consume_memo": consume_memo},
    "transitions": (("produce_memo", "consume_memo"), ("consume_memo", "produce_memo")),
    "entrypoint": "produce_memo",
    "halt_after": "consume_memo",
}
ASYNC_MEMO = {
    "actions": {"aproduce_memo": aproduce_memo, "aconsume_memo": aconsume_memo},
    "transitions": (("aproduce_memo", "aconsume_memo"), ("aconsume_memo", "aproduce_memo")),
    "entrypoint": "aproduce_memo",
    "halt_after": "aconsume_memo",
}


def _build_memo_app(store, app_id, shape, persister=None, tracker=None, resume=False):
    builder = (
        ApplicationBuilder()
        .with_actions(**shape["actions"])
        .with_transitions(*shape["transitions"])
        .with_identifiers(app_id=app_id, partition_key="pk")
        .with_object_store(store)
    )
    if persister is not None:
        builder = builder.with_state_persister(persister)
    if tracker is not None:
        builder = builder.with_tracker(tracker)
    if resume:
        return builder.initialize_from(
            persister,
            resume_at_next_action=True,
            default_state={},
            default_entrypoint=shape["entrypoint"],
        )
    return builder.with_entrypoint(shape["entrypoint"])


def _app_context(app) -> SerializationContext:
    """The one SerializationContext the application installed for its hook dispatches."""
    factory = app._adapter_set._hook_context
    assert factory is not None, "an application with an object store must install a hook context"
    cells = [
        cell.cell_contents
        for cell in (getattr(factory, "__closure__", None) or ())
        if isinstance(cell.cell_contents, SerializationContext)
    ]
    assert len(cells) == 1, cells
    return cells[0]


def test_sync_resume_seeds_a_memo_the_first_persist_can_use(tmp_path):
    """The point of the memo: an unchanged artifact costs nothing after a resume."""
    _register_memo_blob_serde("test_memo_sync_resume")
    store = TrackedStore(str(tmp_path / "blobs"))
    persister = SQLitePersister.from_values(db_path=str(tmp_path / "state.db"), table_name="t")
    persister.initialize()

    app = _build_memo_app(store, "memo-sync", SYNC_MEMO, persister=persister).build()
    app.run(halt_after=[SYNC_MEMO["halt_after"]])
    assert ("put", len(MEMO_BYTES)) in store.ops, store.ops
    store.ops.clear()

    resumed = _build_memo_app(
        store, "memo-sync", SYNC_MEMO, persister=persister, resume=True
    ).build()
    assert resumed.state["memo_blob"].data == MEMO_BYTES
    assert ("get", len(MEMO_BYTES)) in store.ops  # the load itself downloads it
    store.ops.clear()

    resumed.run(halt_after=[SYNC_MEMO["halt_after"]])  # re-persists the unchanged value, twice
    assert store.ops == [], store.ops
    persister.cleanup()


async def test_async_resume_seeds_a_memo_the_first_persist_can_use(tmp_path):
    """Same lifecycle guarantee on the async path (async store + async serde + async persister)."""
    from burr.integrations.persisters.b_aiosqlite import AsyncSQLitePersister

    _register_async_memo_blob_serde("test_memo_async_resume")
    store = CountedAsyncStore()
    persister = await AsyncSQLitePersister.from_values(
        db_path=str(tmp_path / "astate.db"), table_name="t"
    )
    await persister.initialize()

    app = await _build_memo_app(store, "memo-async", ASYNC_MEMO, persister=persister).abuild()
    await app.arun(halt_after=[ASYNC_MEMO["halt_after"]])
    assert ("put", len(MEMO_BYTES)) in store.ops, store.ops
    store.ops.clear()

    resumed = await _build_memo_app(
        store, "memo-async", ASYNC_MEMO, persister=persister, resume=True
    ).abuild()
    assert resumed.state["memo_blob"].data == MEMO_BYTES
    assert ("get", len(MEMO_BYTES)) in store.ops
    store.ops.clear()

    await resumed.arun(halt_after=[ASYNC_MEMO["halt_after"]])
    assert store.ops == [], store.ops
    await persister.cleanup()


def test_load_and_hooks_share_one_context_sync(tmp_path):
    """Identity: the context the deserializer saw is the one the application's hooks use."""
    _register_memo_blob_serde("test_identity_sync")
    seen = {"serialize": [], "deserialize": []}
    inner_serialize = serde.serialize.dispatch(MemoBlob)

    @serde.serialize.register(MemoBlob)
    def _capture(value, serialization_context=None, **kwargs):
        seen["serialize"].append(serialization_context)
        return inner_serialize(value, serialization_context=serialization_context, **kwargs)

    inner_deserialize = serde.deserializer.func_map["test_identity_sync"]

    @serde.deserializer.register("test_identity_sync")
    def _capture_de(value, serialization_context=None, **kwargs):
        seen["deserialize"].append(serialization_context)
        return inner_deserialize(value, serialization_context=serialization_context, **kwargs)

    store = TrackedStore(str(tmp_path / "blobs2"))
    persister = SQLitePersister.from_values(db_path=str(tmp_path / "identity.db"), table_name="t")
    persister.initialize()
    _build_memo_app(store, "identity", SYNC_MEMO, persister=persister).build().run(
        halt_after=[SYNC_MEMO["halt_after"]]
    )

    cold_serializes = len(seen["serialize"])
    resumed = _build_memo_app(
        store, "identity", SYNC_MEMO, persister=persister, resume=True
    ).build()
    resumed.run(halt_after=[SYNC_MEMO["halt_after"]])

    assert len(seen["deserialize"]) == 1, "the resumed load must have run the deserializer once"
    load_ctx = seen["deserialize"][0]
    assert load_ctx is _app_context(resumed), (
        "the load-time context must be the very object the application's hooks install, or "
        "anything the deserializer seeded on it is discarded"
    )
    post_resume = seen["serialize"][cold_serializes:]
    assert post_resume, "the resumed run must have serialized"
    assert all(ctx is load_ctx for ctx in post_resume), post_resume
    persister.cleanup()


async def test_load_and_hooks_share_one_context_async(tmp_path):
    from burr.integrations.persisters.b_aiosqlite import AsyncSQLitePersister

    _register_async_memo_blob_serde("test_identity_async")
    seen = {"serialize": [], "deserialize": []}
    inner_serialize = serde.serialize.dispatch(MemoBlob)

    @serde.serialize.register(MemoBlob)
    async def _capture(value, serialization_context=None, **kwargs):
        seen["serialize"].append(serialization_context)
        return await inner_serialize(value, serialization_context=serialization_context, **kwargs)

    inner_deserialize = serde.deserializer.func_map["test_identity_async"]

    @serde.deserializer.register("test_identity_async")
    async def _capture_de(value, serialization_context=None, **kwargs):
        seen["deserialize"].append(serialization_context)
        return await inner_deserialize(value, serialization_context=serialization_context, **kwargs)

    store = CountedAsyncStore()
    persister = await AsyncSQLitePersister.from_values(
        db_path=str(tmp_path / "identity_async.db"), table_name="t"
    )
    await persister.initialize()
    app = await _build_memo_app(store, "identity-a", ASYNC_MEMO, persister=persister).abuild()
    await app.arun(halt_after=[ASYNC_MEMO["halt_after"]])
    cold_serializes = len(seen["serialize"])

    resumed = await _build_memo_app(
        store, "identity-a", ASYNC_MEMO, persister=persister, resume=True
    ).abuild()
    await resumed.arun(halt_after=[ASYNC_MEMO["halt_after"]])

    assert len(seen["deserialize"]) == 1
    load_ctx = seen["deserialize"][0]
    assert load_ctx is _app_context(resumed)
    post_resume = seen["serialize"][cold_serializes:]
    assert post_resume, "the resumed run must have serialized"
    assert all(ctx is load_ctx for ctx in post_resume), post_resume
    await persister.cleanup()


def test_two_applications_do_not_share_a_serialization_context(tmp_path):
    """No process-wide memo: two applications cannot see or pollute each other's cache."""
    store = TrackedStore(str(tmp_path / "blobs3"))
    a = _build_memo_app(store, "app-a", SYNC_MEMO).build()
    b = _build_memo_app(store, "app-b", SYNC_MEMO).build()
    ctx_a, ctx_b = _app_context(a), _app_context(b)
    assert ctx_a is not ctx_b
    ctx_a.memo["poison"] = "mine only"
    assert ctx_b.memo == {}
    # a serialization outside any application gets no context, so it cannot reach either memo
    assert serde.get_serialization_context() is None


def test_one_builder_reused_builds_independent_memos(tmp_path):
    """A builder is a template: two builds from it must not inherit each other's cache."""
    store = TrackedStore(str(tmp_path / "blobs4"))
    builder = _build_memo_app(store, "reuse", SYNC_MEMO)
    ctx1 = _app_context(builder.build())
    ctx2 = _app_context(builder.build())
    assert ctx1 is not ctx2
    ctx1.memo["k"] = "first"
    assert ctx2.memo == {}


def test_hook_context_hands_the_same_object_every_dispatch(tmp_path):
    """Every dispatch of one application reuses one context -- that is what makes the memo useful."""
    store = TrackedStore(str(tmp_path / "blobs5"))
    app = _build_memo_app(store, "single", SYNC_MEMO).build()
    ctx = _app_context(app)
    with app._adapter_set._hook_context():
        assert serde.get_serialization_context() is ctx
        with app._adapter_set._hook_context():
            assert serde.get_serialization_context() is ctx
    assert serde.get_serialization_context() is None


def test_no_object_store_leaves_behaviour_unchanged(tmp_path):
    """The compatibility bar: nothing installed, nothing shared, nothing about the type changed."""
    builder = (
        ApplicationBuilder()
        .with_actions(**SYNC_MEMO["actions"])
        .with_transitions(*SYNC_MEMO["transitions"])
        .with_entrypoint(SYNC_MEMO["entrypoint"])
        .with_identifiers(app_id="no-store", partition_key="pk")
    )
    assert builder._serialization_hook_context() is None
    app = builder.build()
    assert app._adapter_set._hook_context is None
    # the memo is excluded from comparison and hashing, so the dataclass keeps the semantics it
    # had before it existed
    assert isinstance(hash(SerializationContext()), int)
    store = TrackedStore(str(tmp_path / "blobs6"))
    assert SerializationContext(object_store=store) == SerializationContext(object_store=store)
    assert SerializationContext(object_store=store) != SerializationContext()
    assert SerializationContext() != SerializationContext(object_store=store)
    a, b = SerializationContext(), SerializationContext()
    a.memo["x"] = 1
    assert b.memo == {}
    assert [f.name for f in dataclasses.fields(SerializationContext)] == ["object_store", "memo"]


def test_memo_key_is_a_cache_key_not_an_identity_key(tmp_path):
    """Two values with identical bytes but different metadata keep their own metadata.

    The memo caches the ArtifactRef, never the payload, so `name` is always rebuilt from the live
    value. This is the regression that caching the whole payload under sha256(data) would allow.
    """
    _register_memo_blob_serde("test_memo_metadata")
    store = TrackedStore(str(tmp_path / "blobs_meta"))
    ctx = SerializationContext(object_store=store)
    with serde.serialization_context(ctx):
        state = State(
            {
                "a": MemoBlob(b"same content", name="a.pdf"),
                "b": MemoBlob(b"same content", name="b.pdf"),
            }
        )
        serialized = state.serialize()
    assert serialized["a"]["name"] == "a.pdf"
    assert serialized["b"]["name"] == "b.pdf"
    assert serialized["a"]["ref"] == serialized["b"]["ref"]  # same content, one artifact
    assert len(store.ops) == 2  # one exists + one put covers both values

    with serde.serialization_context(SerializationContext(object_store=store)):
        restored = State.deserialize(serialized)
    assert restored["a"].name == "a.pdf"
    assert restored["b"].name == "b.pdf"
    assert restored["a"].data == restored["b"].data == b"same content"


def test_persister_and_tracker_share_the_memo_in_one_step(tmp_path):
    """Two adapters serializing the same state in one step must make one store call, not two."""
    _register_memo_blob_serde("test_persister_tracker")
    store = TrackedStore(str(tmp_path / "blobs7"))
    persister = SQLitePersister.from_values(db_path=str(tmp_path / "pt.db"), table_name="t")
    persister.initialize()
    tracker = LocalTrackingClient(project="memo-pt", storage_dir=str(tmp_path / "tracking"))

    app = _build_memo_app(store, "pt", SYNC_MEMO, persister=persister, tracker=tracker).build()
    app.run(halt_after=[SYNC_MEMO["halt_after"]])
    assert store.ops.count(("put", len(MEMO_BYTES))) == 1, store.ops

    log_path = os.path.join(str(tmp_path), "tracking", "memo-pt", "pt", "log.jsonl")
    with open(log_path, encoding="utf-8") as f:
        log = f.read()
    assert "ArtifactRef" in log
    assert MEMO_BYTES.decode() not in log  # the log holds a reference, not the payload

    store.ops.clear()
    resumed = _build_memo_app(
        store, "pt", SYNC_MEMO, persister=persister, tracker=tracker, resume=True
    ).build()
    # deserialization is eager: resuming downloads the artifact once, through the two adapters
    assert store.ops == [("get", len(MEMO_BYTES))], store.ops
    store.ops.clear()

    resumed.run(halt_after=[SYNC_MEMO["halt_after"]])
    assert store.ops == [], store.ops
    persister.cleanup()
