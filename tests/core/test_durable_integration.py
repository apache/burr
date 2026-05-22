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

import datetime
from collections import defaultdict
from typing import Literal, Optional

import pytest

from burr.core import ApplicationBuilder, GraphBuilder, State, action, resume
from burr.core.persistence import AsyncInMemoryPersister, BaseStatePersister, InMemoryPersister
from burr.core.state import State as _State


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
        state: "_State",
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


@action(reads=[], writes=["seen"])
def start(state):
    return state.update(seen=True)


@action(reads=["seen"], writes=["done"])
def gate(state, __context):
    decision = __context.suspend("approval")
    return state.update(done=decision["approved"])


def _graph():
    return (
        GraphBuilder()
        .with_actions(start=start, gate=gate)
        .with_transitions(("start", "gate"))
        .build()
    )


def _build(persister, graph):
    return (
        ApplicationBuilder()
        .with_graph(graph)
        .with_entrypoint("start")
        .with_state(State({}))
        .with_identifiers(app_id="run1", partition_key="pk1")
        .with_state_persister(persister)
        .build()
    )


def test_suspend_then_resume_completes_the_run():
    persister = InMemoryPersister()
    graph = _graph()

    # First process: run, suspend.
    app = _build(persister, graph)
    app.run(halt_after=["gate"])
    assert app.suspended is not None

    # The process can die here. New process: resume.
    final_state = resume(
        persister=persister, graph=graph,
        app_id="run1", partition_key="pk1",
        channel="approval", payload={"approved": True},
    )
    assert final_state["done"] is True

    # The suspension is now resolved.
    record = persister.load_suspension("pk1", "run1", "approval")
    assert record.resolved is True


def test_resume_is_idempotent():
    persister = InMemoryPersister()
    graph = _graph()
    app = _build(persister, graph)
    app.run(halt_after=["gate"])

    first = resume(
        persister=persister, graph=graph, app_id="run1", partition_key="pk1",
        channel="approval", payload={"approved": True},
    )
    # Webhook retries are real: a second resume is a no-op.
    second = resume(
        persister=persister, graph=graph, app_id="run1", partition_key="pk1",
        channel="approval", payload={"approved": True},
    )
    assert first["done"] == second["done"] is True


def test_resume_unknown_channel_raises():
    persister = InMemoryPersister()
    graph = _graph()
    app = _build(persister, graph)
    app.run(halt_after=["gate"])

    with pytest.raises(ValueError):
        resume(
            persister=persister, graph=graph, app_id="run1", partition_key="pk1",
            channel="nonexistent", payload={},
        )


async def test_async_suspend_then_aresume_completes():
    from burr.core import aresume

    @action(reads=[], writes=["seen"])
    async def astart(state):
        return state.update(seen=True)

    @action(reads=["seen"], writes=["done"])
    async def agate(state, __context):
        decision = __context.suspend("approval")
        return state.update(done=decision["approved"])

    graph = (
        GraphBuilder()
        .with_actions(astart=astart, agate=agate)
        .with_transitions(("astart", "agate"))
        .build()
    )
    persister = InMemoryPersister()
    app = (
        ApplicationBuilder()
        .with_graph(graph)
        .with_entrypoint("astart")
        .with_state(State({}))
        .with_identifiers(app_id="arun1", partition_key="pk1")
        .with_state_persister(persister)
        .build()
    )
    await app.arun(halt_after=["agate"])
    assert app.suspended is not None

    final_state = await aresume(
        persister=persister, graph=graph, app_id="arun1", partition_key="pk1",
        channel="approval", payload={"approved": True},
    )
    assert final_state["done"] is True


def test_resume_through_in_state_fallback():
    """Resume uses the in-state fallback path when the persister does not support
    dedicated durable storage (supports_durable_storage() is False). NonDurablePersister
    does not override save_suspension, so it triggers the fallback path where
    suspension data rides inside the State blob."""
    persister = NonDurablePersister()

    graph = _graph()

    # First process: build app, run until it suspends at 'gate'.
    app = _build(persister, graph)
    app.run(halt_after=["gate"])
    assert app.suspended is not None

    # Same persister instance -- in-memory SQLite is lost if we open a new connection.
    final_state = resume(
        persister=persister,
        graph=graph,
        app_id="run1",
        partition_key="pk1",
        channel="approval",
        payload={"approved": True},
    )
    assert final_state["done"] is True


def test_resume_in_state_fallback_second_call_raises():
    """A second resume() call on an in-state fallback persister raises ValueError.

    After the first resume() completes, the resumed run's new state row no longer
    carries '__burr_durable__', so the suspension record is gone. A second resume()
    must raise ValueError with a message that names the in-state fallback as the
    reason, distinguishing it from a never-suspended app_id.
    """
    persister = NonDurablePersister()

    graph = _graph()

    # Suspend.
    app = _build(persister, graph)
    app.run(halt_after=["gate"])
    assert app.suspended is not None

    # First resume succeeds.
    resume(
        persister=persister,
        graph=graph,
        app_id="run1",
        partition_key="pk1",
        channel="approval",
        payload={"approved": True},
    )

    # Second resume on in-state fallback must raise ValueError naming the cause.
    with pytest.raises(ValueError, match="already resolved on a persister without durable storage"):
        resume(
            persister=persister,
            graph=graph,
            app_id="run1",
            partition_key="pk1",
            channel="approval",
            payload={"approved": True},
        )


async def test_async_suspend_resume_with_async_durable_persister():
    """aresume() works end-to-end with an async durable persister.

    Uses AsyncInMemoryPersister (async + durable storage) to exercise the full
    async load/journal/rebuild path introduced in Task 4.6.
    """
    from burr.core import aresume

    @action(reads=[], writes=["seen"])
    async def astart(state):
        return state.update(seen=True)

    @action(reads=["seen"], writes=["done"])
    async def agate(state, __context):
        decision = __context.suspend("approval")
        return state.update(done=decision["approved"])

    graph = (
        GraphBuilder()
        .with_actions(astart=astart, agate=agate)
        .with_transitions(("astart", "agate"))
        .build()
    )
    persister = AsyncInMemoryPersister()
    app = await (
        ApplicationBuilder()
        .with_graph(graph)
        .with_entrypoint("astart")
        .with_state(State({}))
        .with_identifiers(app_id="async_durable_run1", partition_key="pk1")
        .with_state_persister(persister)
        .abuild()
    )
    await app.arun(halt_after=["agate"])
    assert app.suspended is not None

    final_state = await aresume(
        persister=persister,
        graph=graph,
        app_id="async_durable_run1",
        partition_key="pk1",
        channel="approval",
        payload={"approved": True},
    )
    assert final_state["done"] is True

    # Confirm async mark_suspension_resolved was called.
    record = await persister.load_suspension("pk1", "async_durable_run1", "approval")
    assert record.resolved is True


# --- Task 3.6: durable side effect runs exactly once across suspend/resume ----

# Module-level counter: survives the Application instance, not the process.
_side_effect_calls = []


@action(reads=[], writes=["summary", "approved"])
def summarize_then_gate(state, __context):
    summary = __context.durable("summarize", _expensive_summarize, "draft text")
    decision = __context.suspend("approval", metadata={"summary": summary})
    return state.update(summary=summary, approved=decision["approved"])


def _expensive_summarize(text):
    _side_effect_calls.append(text)
    return f"summary of {text}"


def test_durable_side_effect_runs_once_across_suspend_resume():
    _side_effect_calls.clear()
    graph = (
        GraphBuilder()
        .with_actions(summarize_then_gate=summarize_then_gate)
        .with_transitions()
        .build()
    )
    persister = InMemoryPersister()
    app = (
        ApplicationBuilder()
        .with_graph(graph)
        .with_entrypoint("summarize_then_gate")
        .with_state(State({}))
        .with_identifiers(app_id="once1", partition_key="pk")
        .with_state_persister(persister)
        .build()
    )
    app.run(halt_after=["summarize_then_gate"])
    assert app.suspended is not None
    assert len(_side_effect_calls) == 1  # ran once before suspending

    final_state = resume(
        persister=persister, graph=graph, app_id="once1", partition_key="pk",
        channel="approval", payload={"approved": True},
    )
    # The action re-ran top-to-bottom on resume, but summarize was replayed.
    assert len(_side_effect_calls) == 1
    assert final_state["approved"] is True
    assert final_state["summary"] == "summary of draft text"


# --- Task 3.7: non-deterministic branch raises DeterminismError ---------------

_branch_toggle = {"value": True}


@action(reads=[], writes=["out"])
def nondeterministic(state, __context):
    # ANTI-PATTERN under test: a durable() call behind a branch that flips
    # between the first run and the resume re-run.
    if _branch_toggle["value"]:
        __context.durable("branch_a", lambda: "a")
    else:
        __context.durable("branch_b", lambda: "b")
    decision = __context.suspend("approval")
    return state.update(out=decision["ok"])


def test_nondeterministic_branch_raises_determinism_error():
    from burr.core.durable import DeterminismError

    _branch_toggle["value"] = True
    try:
        graph = (
            GraphBuilder()
            .with_actions(nondeterministic=nondeterministic)
            .with_transitions()
            .build()
        )
        persister = InMemoryPersister()
        app = (
            ApplicationBuilder()
            .with_graph(graph)
            .with_entrypoint("nondeterministic")
            .with_state(State({}))
            .with_identifiers(app_id="det1", partition_key="pk")
            .with_state_persister(persister)
            .build()
        )
        app.run(halt_after=["nondeterministic"])

        # Flip the branch before resume: the re-run takes branch_b.
        _branch_toggle["value"] = False
        with pytest.raises(DeterminismError):
            resume(
                persister=persister, graph=graph, app_id="det1", partition_key="pk",
                channel="approval", payload={"ok": True},
            )
    finally:
        _branch_toggle["value"] = True


# --- Task 4.2: SQLite end-to-end through dedicated tables --------------------


def test_suspend_resume_with_sqlite_dedicated_storage(tmp_path):
    """End-to-end: suspend on a file-backed SQLite persister, close the connection
    (simulating process death), reopen with a fresh persister against the same file,
    resume. Exercises the dedicated ``burr_suspensions`` + ``burr_journal`` tables
    across a true process boundary."""
    from burr.core.persistence import SQLitePersister

    db = str(tmp_path / "durable.db")

    graph = _graph()
    p1 = SQLitePersister.from_values(db)
    p1.initialize()
    app = (
        ApplicationBuilder()
        .with_graph(graph)
        .with_entrypoint("start")
        .with_state(State({}))
        .with_identifiers(app_id="sql1", partition_key="pk")
        .with_state_persister(p1)
        .build()
    )
    app.run(halt_after=["gate"])
    assert app.suspended is not None
    p1.connection.close()  # simulate the process dying

    # New process: brand-new persister against the same DB file.
    p2 = SQLitePersister.from_values(db)
    p2.initialize()
    final_state = resume(
        persister=p2, graph=graph, app_id="sql1", partition_key="pk",
        channel="approval", payload={"approved": True},
    )
    assert final_state["done"] is True
    p2.connection.close()
