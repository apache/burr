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

"""Human-in-the-loop durable execution example.

Demonstrates a draft -> review -> finalize workflow where the "review" step:
1. Uses ``durable()`` to memoize an expensive summary so it is computed once
   even if the process is restarted before the human responds.
2. Calls ``suspend("human_approval")`` to pause the workflow and wait for an
   external signal (webhook, UI button, etc.).
3. Continues to finalization once the human payload arrives via ``resume()``.
"""

import pathlib
from typing import Optional, Tuple

from burr.core import ApplicationBuilder, GraphBuilder, State, action, resume
from burr.core.application import Application
from burr.core.graph import Graph
from burr.core.persistence import SQLitePersister

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@action(reads=[], writes=["draft"])
def draft(state: State) -> State:
    """Produce the initial draft content."""
    return state.update(draft="This is the initial draft content for review.")


@action(reads=["draft"], writes=["review_decision"])
def review(state: State, __context) -> State:
    """Memoize a summary, then suspend waiting for human approval.

    The ``durable()`` call ensures the summarizer runs exactly once across
    the suspend/resume boundary — the result is replayed from the journal on
    resume instead of being recomputed.
    """
    summary = __context.durable(
        "summarize",
        lambda d: f"SUMMARY: {d[:20]}...",
        state["draft"],
    )
    # Suspend until a human delivers a payload over the "human_approval" channel.
    # The payload is expected to be a dict with key "approved" (bool).
    payload = __context.suspend(
        "human_approval",
        metadata={"summary": summary},
    )
    return state.update(review_decision=payload)


@action(reads=["review_decision"], writes=["approved"])
def finalize(state: State) -> State:
    """Record the human's decision."""
    decision = state["review_decision"]
    return state.update(approved=decision.get("approved", False))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_application(
    app_id: str,
    partition_key: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Tuple[Application, Graph, SQLitePersister]:
    """Build and return the application, its graph, and the persister.

    :param app_id: Unique identifier for this run.
    :param partition_key: Optional partition key (e.g. tenant / user id).
    :param db_path: Path for the SQLite database. Defaults to a file next to
        this script so re-runs pick up where they left off.
    :return: Tuple of (application, graph, persister).
    """
    if db_path is None:
        db_path = str(pathlib.Path(__file__).parent / "durable.db")

    persister = SQLitePersister.from_values(db_path)
    persister.initialize()

    graph = (
        GraphBuilder()
        .with_actions(draft=draft, review=review, finalize=finalize)
        .with_transitions(("draft", "review"), ("review", "finalize"))
        .build()
    )

    app = (
        ApplicationBuilder()
        .with_graph(graph)
        .with_entrypoint("draft")
        .with_state(State({}))
        .with_identifiers(app_id=app_id, partition_key=partition_key)
        .with_state_persister(persister)
        .build()
    )

    return app, graph, persister


# ---------------------------------------------------------------------------
# Main: run the full suspend/resume cycle for demonstration
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    _DB_PATH = str(pathlib.Path(__file__).parent / "durable.db")
    # Remove stale DB so the demo always starts fresh.
    if os.path.exists(_DB_PATH):
        os.remove(_DB_PATH)

    # --- First half: run until the workflow suspends at "review" ---
    app, graph, persister = build_application(app_id="demo-1", db_path=_DB_PATH)

    # Generate the state-machine diagram (graphviz binary required).
    try:
        app.visualize(
            output_file_path=str(pathlib.Path(__file__).parent / "statemachine"),
            include_conditions=False,
            view=False,
            format="png",
        )
        print("State machine saved to statemachine.png")
    except Exception as exc:
        print(f"visualize skipped: {exc}")

    app.run(halt_after=["review"])
    print("Suspended on channel:", app.suspended.channel)
    print("Suspension metadata:", app.suspended.metadata)

    # --- Second half: simulate the human approving the draft ---
    final_state = resume(
        persister=persister,
        graph=graph,
        app_id="demo-1",
        partition_key=None,
        channel="human_approval",
        payload={"approved": True},
    )
    print("Final approved:", final_state["approved"])
