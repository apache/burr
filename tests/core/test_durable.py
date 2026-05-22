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

import dataclasses
import datetime
from collections import defaultdict
from typing import Literal, Optional

import pytest

from burr.core.durable import (
    DeterminismError,
    JournalEntry,
    SuspensionRecord,
    _Suspended,
)
from burr.core.persistence import BaseStatePersister
from burr.core.state import State


class NonDurablePersister(BaseStatePersister):
    """Dict-backed persister that does NOT override any durable-storage methods.

    ``supports_durable_storage(NonDurablePersister())`` returns False because
    ``save_suspension`` is inherited unchanged from ``BaseStatePersister``.
    The Application therefore stores suspensions and journal entries inside
    the State blob (in-state fallback path).
    """

    def __init__(self):
        self._storage = defaultdict(lambda: defaultdict(list))

    def save(
        self,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int,
        position: str,
        state: "State",
        status: Literal["completed", "failed", "suspended"],
        **kwargs,
    ):
        record = {
            "partition_key": partition_key or "",
            "app_id": app_id,
            "sequence_id": sequence_id,
            "position": position,
            "state": state,
            "created_at": datetime.datetime.now().isoformat(),
            "status": status,
        }
        self._storage[partition_key][app_id].append(record)

    def load(
        self,
        partition_key: str,
        app_id: Optional[str],
        sequence_id: Optional[int] = None,
        **kwargs,
    ):
        if app_id is None:
            return None
        states = self._storage[partition_key][app_id]
        if not states:
            return None
        if sequence_id is None:
            return states[-1]
        matching = [s for s in states if s["sequence_id"] == sequence_id]
        return matching[-1] if matching else None

    def list_app_ids(self, partition_key: str, **kwargs):
        return list(self._storage[partition_key].keys())


def test_suspended_is_base_exception_not_exception():
    assert issubclass(_Suspended, BaseException)
    assert not issubclass(_Suspended, Exception)


def test_suspended_carries_channel_schema_metadata():
    sig = _Suspended(channel="approval", schema_json={"type": "object"}, metadata={"k": "v"})
    assert sig.channel == "approval"
    assert sig.schema_json == {"type": "object"}
    assert sig.metadata == {"k": "v"}


def test_determinism_error_is_exception():
    assert issubclass(DeterminismError, Exception)


def test_suspension_record_fields():
    record = SuspensionRecord(
        suspension_id="s1",
        partition_key="p",
        app_id="a",
        sequence_id=3,
        position="review",
        channel="approval",
        schema_json=None,
        metadata={"summary": "hi"},
        inputs={"x": 1},
        state={"draft": "text"},
        created_at="2026-05-22T00:00:00",
        resolved=False,
    )
    assert dataclasses.is_dataclass(record)
    assert record.resolved is False
    assert record.state == {"draft": "text"}


def test_journal_entry_fields():
    entry = JournalEntry(
        partition_key="p",
        app_id="a",
        sequence_id=3,
        step_key="summarize",
        call_index=0,
        result="cached value",
    )
    assert dataclasses.is_dataclass(entry)
    assert entry.call_index == 0
    assert entry.result == "cached value"


def test_save_status_literal_includes_suspended():
    import typing

    from burr.core.persistence import BaseStateSaver

    hints = typing.get_type_hints(BaseStateSaver.save)
    status_arg = hints["status"]
    assert "suspended" in typing.get_args(status_arg)


def test_durable_symbols_exported_from_burr_core():
    import burr.core as core

    assert hasattr(core, "DeterminismError")
    assert hasattr(core, "SuspensionRecord")


def test_base_persister_durable_methods_raise_not_implemented():
    from burr.core.durable import JournalEntry, SuspensionRecord
    from burr.core.persistence import BaseStatePersister

    # Use DevNullPersister which satisfies the abstract methods but does not
    # override the durable methods, so all five should raise NotImplementedError.
    from burr.core.persistence import DevNullPersister

    p = DevNullPersister()

    dummy_record = SuspensionRecord(
        suspension_id="s1",
        partition_key="p",
        app_id="a",
        sequence_id=1,
        position="action",
        channel="ch",
        schema_json=None,
        metadata=None,
        inputs={},
        state={},
        created_at="2026-05-22T00:00:00",
        resolved=False,
    )
    dummy_entry = JournalEntry(
        partition_key="p",
        app_id="a",
        sequence_id=1,
        step_key="k",
        call_index=0,
        result=None,
    )

    with pytest.raises(NotImplementedError):
        p.save_suspension(dummy_record)

    with pytest.raises(NotImplementedError):
        p.load_suspension("p", "a", "ch")

    with pytest.raises(NotImplementedError):
        p.save_journal_entry(dummy_entry)

    with pytest.raises(NotImplementedError):
        p.load_journal("p", "a", 1)

    with pytest.raises(NotImplementedError):
        p.mark_suspension_resolved("s1")


def test_supports_durable_storage_false_for_non_durable_persister():
    from burr.core.durable import supports_durable_storage

    persister = NonDurablePersister()
    assert supports_durable_storage(persister) is False


def test_supports_durable_storage_true_for_in_memory():
    from burr.core.durable import supports_durable_storage
    from burr.core.persistence import InMemoryPersister

    assert supports_durable_storage(InMemoryPersister()) is True


def test_in_memory_persister_suspension_round_trip():
    from burr.core.durable import SuspensionRecord
    from burr.core.persistence import InMemoryPersister

    persister = InMemoryPersister()
    record = SuspensionRecord(
        suspension_id="s1", partition_key="p", app_id="a", sequence_id=2,
        position="review", channel="approval", schema_json=None,
        metadata=None, inputs={}, state={"draft": "d"},
        created_at="2026-05-22T00:00:00", resolved=False,
    )
    persister.save_suspension(record)
    loaded = persister.load_suspension("p", "a", "approval")
    assert loaded.suspension_id == "s1"
    assert loaded.state == {"draft": "d"}
    assert loaded.resolved is False


def test_in_memory_persister_journal_round_trip():
    from burr.core.durable import JournalEntry
    from burr.core.persistence import InMemoryPersister

    persister = InMemoryPersister()
    entry = JournalEntry(
        partition_key="p", app_id="a", sequence_id=2,
        step_key="summarize", call_index=0, result="cached",
    )
    persister.save_journal_entry(entry)
    journal = persister.load_journal("p", "a", 2)
    assert len(journal) == 1
    assert journal[0].result == "cached"


# --- In-state fallback codec tests -------------------------------------------


def test_suspension_codec_round_trip():
    from burr.core.durable import (
        SuspensionRecord,
        read_suspension_from_state,
        write_suspension_into_state,
    )
    from burr.core.state import State

    record = SuspensionRecord(
        suspension_id="s42",
        partition_key="p",
        app_id="a",
        sequence_id=5,
        position="review",
        channel="approval",
        schema_json=None,
        metadata={"note": "hi"},
        inputs={"x": 1},
        state={"draft": "text"},
        created_at="2026-05-22T00:00:00",
        resolved=False,
    )
    state = State()
    new_state = write_suspension_into_state(state, record)
    result = read_suspension_from_state(new_state, "approval")

    assert result is not None
    assert result.suspension_id == record.suspension_id
    assert result.channel == record.channel
    assert result.state == record.state
    assert result.resolved == record.resolved


def test_read_suspension_from_state_channel_mismatch():
    from burr.core.durable import (
        SuspensionRecord,
        read_suspension_from_state,
        write_suspension_into_state,
    )
    from burr.core.state import State

    record = SuspensionRecord(
        suspension_id="s1",
        partition_key="p",
        app_id="a",
        sequence_id=1,
        position="act",
        channel="approval",
        schema_json=None,
        metadata=None,
        inputs={},
        state={},
        created_at="2026-05-22T00:00:00",
        resolved=False,
    )
    state = write_suspension_into_state(State(), record)

    assert read_suspension_from_state(state, "other_channel") is None
    assert read_suspension_from_state(State(), "approval") is None


def test_journal_codec_round_trip():
    from burr.core.durable import (
        JournalEntry,
        read_journal_from_state,
        write_journal_into_state,
    )
    from burr.core.state import State

    entries = [
        JournalEntry(
            partition_key="p", app_id="a", sequence_id=3,
            step_key="step_a", call_index=0, result="first",
        ),
        JournalEntry(
            partition_key="p", app_id="a", sequence_id=3,
            step_key="step_b", call_index=1, result="second",
        ),
    ]
    state = write_journal_into_state(State(), entries)
    loaded = read_journal_from_state(state)

    assert len(loaded) == 2
    call_indices = {e.call_index for e in loaded}
    assert call_indices == {0, 1}
    results = {e.call_index: e.result for e in loaded}
    assert results[0] == "first"
    assert results[1] == "second"


def test_journal_codec_preserves_json_friendly_result():
    from burr.core.durable import (
        JournalEntry,
        read_journal_from_state,
        write_journal_into_state,
    )
    from burr.core.state import State

    original_result = {"k": [1, 2]}
    entry = JournalEntry(
        partition_key="p", app_id="a", sequence_id=7,
        step_key="fetch", call_index=0, result=original_result,
    )
    state = write_journal_into_state(State(), [entry])
    loaded = read_journal_from_state(state)

    assert len(loaded) == 1
    assert loaded[0].result == original_result


# --- InMemoryPersister: mark_suspension_resolved tests -----------------------


def test_in_memory_persister_mark_suspension_resolved_flips_flag():
    from burr.core.durable import SuspensionRecord
    from burr.core.persistence import InMemoryPersister

    persister = InMemoryPersister()
    record = SuspensionRecord(
        suspension_id="s99",
        partition_key="p",
        app_id="a",
        sequence_id=1,
        position="review",
        channel="approval",
        schema_json=None,
        metadata=None,
        inputs={},
        state={},
        created_at="2026-05-22T00:00:00",
        resolved=False,
    )
    persister.save_suspension(record)
    persister.mark_suspension_resolved("s99")
    loaded = persister.load_suspension("p", "a", "approval")
    assert loaded is not None
    assert loaded.resolved is True


def test_in_memory_persister_mark_suspension_resolved_unknown_id_is_noop():
    from burr.core.persistence import InMemoryPersister

    persister = InMemoryPersister()
    # Must not raise for an id that was never stored.
    persister.mark_suspension_resolved("does-not-exist")


def test_in_memory_persister_mark_suspension_resolved_is_conditional():
    """mark_suspension_resolved must match SQLite semantics: True on first call,
    False on second call (already resolved), and False for an unknown id."""
    from burr.core.durable import SuspensionRecord
    from burr.core.persistence import InMemoryPersister

    persister = InMemoryPersister()
    record = SuspensionRecord(
        suspension_id="s-cond",
        partition_key="p",
        app_id="a",
        sequence_id=1,
        position="review",
        channel="approval",
        schema_json=None,
        metadata=None,
        inputs={},
        state={},
        created_at="2026-05-22T00:00:00",
        resolved=False,
    )
    persister.save_suspension(record)

    # First call: row was unresolved, should flip and return True.
    first = persister.mark_suspension_resolved("s-cond")
    assert first is True

    # Second call: already resolved, should be a no-op and return False.
    second = persister.mark_suspension_resolved("s-cond")
    assert second is False

    # Unknown id: nothing to flip, must return False.
    unknown = persister.mark_suspension_resolved("does-not-exist")
    assert unknown is False


# --- InMemoryPersister: load_journal ordering test ---------------------------


def test_in_memory_persister_journal_ordered_by_call_index():
    from burr.core.durable import JournalEntry
    from burr.core.persistence import InMemoryPersister

    persister = InMemoryPersister()
    # Insert out of order: 2, 0, 1
    for idx in (2, 0, 1):
        persister.save_journal_entry(
            JournalEntry(
                partition_key="p",
                app_id="a",
                sequence_id=5,
                step_key=f"step_{idx}",
                call_index=idx,
                result=f"result_{idx}",
            )
        )
    journal = persister.load_journal("p", "a", 5)
    assert [e.call_index for e in journal] == [0, 1, 2]


# --- ApplicationContext.suspend() tests ---------------------------------------


def _make_context(resume_signals=None, state_persister=None):
    from burr.core.application import ApplicationContext

    return ApplicationContext(
        app_id="a", partition_key="p", sequence_id=1, tracker=None,
        parallel_executor_factory=lambda: None, state_initializer=None,
        state_persister=state_persister, action_name="review",
        _resume_signals=resume_signals or {},
        _loaded_journal=[], _journal_sink=[],
    )


def test_suspend_raises_on_first_call():
    from burr.core.durable import _Suspended

    ctx = _make_context()
    with pytest.raises(_Suspended) as excinfo:
        ctx.suspend("approval", metadata={"summary": "hi"})
    assert excinfo.value.channel == "approval"
    assert excinfo.value.metadata == {"summary": "hi"}


def test_suspend_returns_payload_when_signal_present():
    ctx = _make_context(resume_signals={"approval": {"approved": True}})
    result = ctx.suspend("approval")
    assert result == {"approved": True}


def test_suspend_validates_payload_against_live_schema():
    pydantic = pytest.importorskip("pydantic")

    class Approval(pydantic.BaseModel):
        approved: bool

    ctx = _make_context(resume_signals={"approval": {"approved": True}})
    result = ctx.suspend("approval", schema=Approval)
    assert isinstance(result, Approval)
    assert result.approved is True


def test_suspend_first_call_schema_json_populated():
    pydantic = pytest.importorskip("pydantic")

    class Approval(pydantic.BaseModel):
        approved: bool

    ctx = _make_context()
    with pytest.raises(_Suspended) as excinfo:
        ctx.suspend("approval", schema=Approval)
    assert excinfo.value.schema_json == Approval.model_json_schema()


# ---------------------------------------------------------------------------
# Integration: suspend signal caught by the sync run loop (Task 2.3)
# ---------------------------------------------------------------------------


def _suspending_app(persister):
    from burr.core import ApplicationBuilder, State, action

    @action(reads=[], writes=["seen"])
    def start(state):
        return state.update(seen=True)

    @action(reads=["seen"], writes=["done"])
    def gate(state, __context):
        decision = __context.suspend("approval")
        return state.update(done=decision)

    return (
        ApplicationBuilder()
        .with_actions(start=start, gate=gate)
        .with_transitions(("start", "gate"))
        .with_entrypoint("start")
        .with_state(State({}))
        .with_identifiers(app_id="app1", partition_key="pk1")
        .with_state_persister(persister)
        .build()
    )


def test_run_stops_and_records_suspension():
    from burr.core.persistence import InMemoryPersister

    persister = InMemoryPersister()
    app = _suspending_app(persister)
    app.run(halt_after=["gate"])

    assert app.suspended is not None
    assert app.suspended.channel == "approval"
    assert app.suspended.position == "gate"
    record = persister.load_suspension("pk1", "app1", "approval")
    assert record is not None
    assert record.resolved is False
    assert record.state.get("seen") is True


# ---------------------------------------------------------------------------
# Integration: suspend signal caught by the async run loop (Task 2.4)
# ---------------------------------------------------------------------------


async def test_arun_stops_and_records_suspension():
    from burr.core import ApplicationBuilder, State, action
    from burr.core.persistence import InMemoryPersister

    @action(reads=[], writes=["seen"])
    async def astart(state):
        return state.update(seen=True)

    @action(reads=["seen"], writes=["done"])
    async def agate(state, __context):
        decision = __context.suspend("approval")
        return state.update(done=decision)

    persister = InMemoryPersister()
    app = (
        ApplicationBuilder()
        .with_actions(astart=astart, agate=agate)
        .with_transitions(("astart", "agate"))
        .with_entrypoint("astart")
        .with_state(State({}))
        .with_identifiers(app_id="app2", partition_key="pk2")
        .with_state_persister(persister)
        .build()
    )
    await app.arun(halt_after=["agate"])

    assert app.suspended is not None
    assert app.suspended.position == "agate"
    record = persister.load_suspension("pk2", "app2", "approval")
    assert record is not None
    assert record.channel == "approval"
    assert record.resolved is False
    assert record.state.get("seen") is True


# --- ApplicationContext.durable() tests (Task 3.1) ----------------------------


def test_durable_executes_fn_and_journals_on_first_run():
    calls = []

    def side_effect(x):
        calls.append(x)
        return x * 2

    ctx = _make_context()
    result = ctx.durable("double", side_effect, 21)
    assert result == 42
    assert calls == [21]
    # The entry was appended to the journal sink for persistence.
    assert len(ctx._journal_sink) == 1
    assert ctx._journal_sink[0].step_key == "double"
    assert ctx._journal_sink[0].call_index == 0
    assert ctx._journal_sink[0].result == 42


def test_durable_forwards_positional_and_keyword_args():
    ctx = _make_context()
    result = ctx.durable("combine", lambda x, y: (x, y), 1, y=2)
    assert result == (1, 2)


def test_durable_assigns_increasing_call_index():
    ctx = _make_context()
    ctx.durable("a", lambda: 1)
    ctx.durable("b", lambda: 2)
    assert [e.call_index for e in ctx._journal_sink] == [0, 1]
    assert [e.step_key for e in ctx._journal_sink] == ["a", "b"]


# --- ApplicationContext.durable() replay tests (Task 3.2) ---------------------


def test_durable_replays_from_loaded_journal_without_executing_fn():
    from burr.core.durable import JournalEntry

    recorded = [
        JournalEntry("p", "a", 1, "double", 0, 42),
    ]
    ctx = _make_context()
    ctx._loaded_journal = recorded

    calls = []

    def side_effect(x):
        calls.append(x)
        return x * 2

    result = ctx.durable("double", side_effect, 21)
    assert result == 42
    assert calls == []  # fn must NOT run on replay


def test_durable_replay_then_execute_for_calls_past_the_journal():
    from burr.core.durable import JournalEntry

    ctx = _make_context()
    ctx._loaded_journal = [JournalEntry("p", "a", 1, "first", 0, "cached")]

    first = ctx.durable("first", lambda: "fresh")
    second = ctx.durable("second", lambda: "executed")
    assert first == "cached"      # replayed
    assert second == "executed"   # past the journal -> executed


# --- ApplicationContext.durable() determinism error (Task 3.3) ----------------


def test_durable_raises_determinism_error_on_key_mismatch():
    from burr.core.durable import DeterminismError, JournalEntry

    ctx = _make_context()
    ctx._loaded_journal = [JournalEntry("p", "a", 1, "summarize", 0, "x")]

    with pytest.raises(DeterminismError):
        # The first durable call on resume used a different key than recorded.
        ctx.durable("translate", lambda: "y")


def test_journal_sink_flushed_into_state_on_completion_with_fallback():
    from burr.core import ApplicationBuilder, State, action
    from burr.core.durable import read_journal_from_state

    @action(reads=[], writes=["v"])
    def compute(state, __context):
        value = __context.durable("calc", lambda: 99)
        return state.update(v=value)

    persister = NonDurablePersister()
    app = (
        ApplicationBuilder()
        .with_actions(compute=compute)
        .with_entrypoint("compute")
        .with_state(State({}))
        .with_identifiers(app_id="j1", partition_key="pk")
        .with_state_persister(persister)
        .build()
    )
    app.run(halt_after=["compute"])
    loaded = persister.load("pk", "j1")
    journal = read_journal_from_state(loaded["state"])
    assert len(journal) == 1
    assert journal[0].result == 99


def test_journal_accumulates_across_multiple_actions():
    from burr.core import ApplicationBuilder, State, action
    from burr.core.durable import read_journal_from_state

    @action(reads=[], writes=["a"])
    def step_a(state, __context):
        v = __context.durable("a_calc", lambda: 1)
        return state.update(a=v)

    @action(reads=["a"], writes=["b"])
    def step_b(state, __context):
        v = __context.durable("b_calc", lambda: 2)
        return state.update(b=v)

    persister = NonDurablePersister()
    app = (
        ApplicationBuilder()
        .with_actions(step_a=step_a, step_b=step_b)
        .with_transitions(("step_a", "step_b"))
        .with_entrypoint("step_a")
        .with_state(State({}))
        .with_identifiers(app_id="j2", partition_key="pk")
        .with_state_persister(persister)
        .build()
    )
    app.run(halt_after=["step_b"])
    loaded = persister.load("pk", "j2")
    journal = read_journal_from_state(loaded["state"])
    assert len(journal) == 2
    keys = {e.step_key for e in journal}
    assert keys == {"a_calc", "b_calc"}


def test_journal_no_double_count_via_stream_result():
    """Regression guard: step_a's journal entry must not be double-counted
    when stream_result() fast-forwards through it and then executes a
    non-streaming step_b.  The fix is self._journal_sink = [] at line ~1744
    of application.py, immediately before the direct self._step() call in
    the non-streaming branch of stream_result().  Deleting that line causes
    this test to observe 3 journal entries instead of 2."""
    from burr.core import ApplicationBuilder, State, action
    from burr.core.durable import read_journal_from_state

    @action(reads=[], writes=["a"])
    def step_a(state, __context):
        v = __context.durable("a_calc", lambda: 1)
        return state.update(a=v)

    @action(reads=["a"], writes=["b"])
    def step_b(state, __context):
        v = __context.durable("b_calc", lambda: 2)
        return state.update(b=v)

    persister = NonDurablePersister()
    app = (
        ApplicationBuilder()
        .with_actions(step_a=step_a, step_b=step_b)
        .with_transitions(("step_a", "step_b"))
        .with_entrypoint("step_a")
        .with_state(State({}))
        .with_identifiers(app_id="j3", partition_key="pk")
        .with_state_persister(persister)
        .build()
    )
    # step_a is NOT in halt_after, so stream_result fast-forwards through it
    # via self.run(), then hits the non-streaming branch for step_b.
    # The fix resets _journal_sink before that branch so step_a's entry is
    # not accumulated a second time into the persisted state.
    action_, container = app.stream_result(halt_after=["step_b"])
    result, final_state = container.get()

    # Verify via the persisted state (the source of truth for the bug).
    loaded = persister.load("pk", "j3")
    journal = read_journal_from_state(loaded["state"])
    assert len(journal) == 2, (
        f"Expected 2 journal entries (a_calc + b_calc), got {len(journal)}: "
        f"{[e.step_key for e in journal]}"
    )
    assert {e.step_key for e in journal} == {"a_calc", "b_calc"}


# --- ApplicationContext.adurable() tests (Task 3.5) ---------------------------


@pytest.mark.asyncio
async def test_adurable_executes_coroutine_and_journals():
    calls = []

    async def async_side_effect(x):
        calls.append(x)
        return x + 1

    ctx = _make_context()
    result = await ctx.adurable("inc", async_side_effect, 41)
    assert result == 42
    assert calls == [41]
    assert ctx._journal_sink[0].step_key == "inc"


@pytest.mark.asyncio
async def test_adurable_replays_without_executing():
    from burr.core.durable import JournalEntry

    ctx = _make_context()
    ctx._loaded_journal = [JournalEntry("p", "a", 1, "inc", 0, 42)]

    calls = []

    async def async_side_effect(x):
        calls.append(x)
        return x + 1

    result = await ctx.adurable("inc", async_side_effect, 41)
    assert result == 42
    assert calls == []


@pytest.mark.asyncio
async def test_adurable_journals_into_durable_persister():
    from burr.core.persistence import InMemoryPersister

    persister = InMemoryPersister()

    async def async_side_effect():
        return "value"

    ctx = _make_context(state_persister=persister)
    await ctx.adurable("step", async_side_effect)

    journal = persister.load_journal("p", "a", 1)
    assert len(journal) == 1
    assert journal[0].step_key == "step"
    assert journal[0].result == "value"


@pytest.mark.asyncio
async def test_ahandle_suspension_persists_via_async_durable_persister():
    from burr.core import ApplicationBuilder, GraphBuilder, State, action
    from burr.core.persistence import AsyncInMemoryPersister

    @action(reads=[], writes=["seen"])
    async def astart(state):
        return state.update(seen=True)

    @action(reads=["seen"], writes=["done"])
    async def agate(state, __context):
        decision = __context.suspend("approval")
        return state.update(done=decision["approved"])

    persister = AsyncInMemoryPersister()
    graph = (
        GraphBuilder()
        .with_actions(astart=astart, agate=agate)
        .with_transitions(("astart", "agate"))
        .build()
    )
    app = await (
        ApplicationBuilder()
        .with_graph(graph)
        .with_entrypoint("astart")
        .with_state(State({}))
        .with_identifiers(app_id="arun1", partition_key="pk1")
        .with_state_persister(persister)
        .abuild()
    )
    await app.arun(halt_after=["agate"])
    assert app.suspended is not None

    # The async durable path persists via await persister.save_suspension(...),
    # so the record lives in persister._suspensions, NOT inside the State blob.
    record = await persister.load_suspension("pk1", "arun1", "approval")
    assert record is not None
    assert record.channel == "approval"
    assert record.resolved is False
