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

import pytest

from burr.core import ApplicationBuilder, GraphBuilder, State, action, resume
from burr.core.persistence import InMemoryPersister, SQLitePersister


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


def test_resume_through_in_state_fallback_with_sqlite():
    """Resume uses the in-state fallback path when the persister does not support
    dedicated durable storage (supports_durable_storage() is False). SQLitePersister
    is a first-party persister that does NOT override save_suspension, so it triggers
    the fallback path where suspension data rides inside the State blob."""
    persister = SQLitePersister(":memory:")
    persister.initialize()

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
    persister = SQLitePersister(":memory:")
    persister.initialize()

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
