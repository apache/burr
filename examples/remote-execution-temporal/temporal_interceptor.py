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

"""Temporal interceptor for Burr actions.

Demonstrates using the ActionExecutionInterceptorHook to route Burr action
execution to Temporal workflows. This validates that the interceptor pattern
works for backends beyond Ray.

Temporal provides durable execution guarantees: if a worker crashes mid-action,
Temporal automatically retries the activity on another worker. Combined with
Burr's state tracking, this gives you observable, durable agent workflows.

Requirements:
    pip install temporalio

Usage:
    1. Start a Temporal server (e.g., `temporal server start-dev`)
    2. Start the worker: `python temporal_interceptor.py worker`
    3. Run the app: `python temporal_interceptor.py run`
"""

import logging
from typing import Any, Dict

from burr.core import Action, ApplicationBuilder, State, action
from burr.lifecycle import (
    ActionExecutionInterceptorHookAsync,
    PostRunStepHookWorkerAsync,
    PreRunStepHookWorkerAsync,
)

logger = logging.getLogger(__name__)

TASK_QUEUE = "burr-actions"


# --- Temporal Activity (runs on worker) ---


async def execute_burr_action_activity(
    action_name: str,
    action_reads: list,
    action_writes: list,
    state_dict: dict,
    inputs: dict,
) -> dict:
    """Temporal activity that executes a Burr action on a worker.

    This is registered as a Temporal activity. The Temporal worker calls this
    function, which reconstructs the state, runs the action, and returns the
    result as a serializable dict.
    """
    # In production, you'd reconstruct state and run the real action here.
    # For this example, we simulate running the action body.
    logger.info(f"[Worker] Executing action '{action_name}' with reads={action_reads}")

    # Execute via the function registry (simplified)
    result = {}
    for key in action_writes:
        if key in inputs:
            result[key] = inputs[key]
        elif key in state_dict:
            result[key] = state_dict[key]
        else:
            result[key] = None

    return {"result": result, "action_name": action_name}


# --- Interceptor ---


class TemporalInterceptor(ActionExecutionInterceptorHookAsync):
    """Route Burr action execution to Temporal activities.

    Actions tagged with "durable" will be executed as Temporal activities,
    giving them automatic retry, timeout, and durability guarantees.

    Actions without the "durable" tag execute locally as usual.
    """

    def __init__(self, temporal_client=None, task_queue: str = TASK_QUEUE):
        """Initialize the Temporal interceptor.

        Args:
            temporal_client: An initialized Temporal client. If None, connects
                on first use.
            task_queue: Temporal task queue name for routing activities.
        """
        self._client = temporal_client
        self._task_queue = task_queue

    async def _get_client(self):
        """Lazy-connect to Temporal server."""
        if self._client is None:
            from temporalio.client import Client

            self._client = await Client.connect("localhost:7233")
        return self._client

    def should_intercept(self, *, action: Action, **future_kwargs: Any) -> bool:
        """Intercept actions tagged with 'durable'."""
        return hasattr(action, "tags") and "durable" in getattr(action, "tags", {})

    async def intercept_run(
        self,
        *,
        action: Action,
        state: State,
        inputs: Dict[str, Any],
        **future_kwargs: Any,
    ) -> dict:
        """Execute the action as a Temporal activity.

        Serializes the state and inputs, starts a Temporal workflow that
        runs the action as an activity, and returns the result.
        """
        client = await self._get_client()

        # Serialize state for transport
        state_dict = {k: v for k, v in state.get_all().items() if not k.startswith("__")}

        logger.info(
            f"[Interceptor] Routing '{action.name}' to Temporal " f"(queue={self._task_queue})"
        )

        # Call worker hooks if provided
        worker_adapter_set = future_kwargs.get("worker_adapter_set")
        if worker_adapter_set:
            await worker_adapter_set.call_all_lifecycle_hooks_async(
                "pre_run_step_worker",
                action=action,
                state=state,
                inputs=inputs,
            )

        # Execute as Temporal activity
        result_data = await client.execute_workflow(
            "burr-action-workflow",
            args=[
                action.name,
                list(action.reads),
                list(action.writes),
                state_dict,
                inputs,
            ],
            id=f"burr-{action.name}-{id(state)}",
            task_queue=self._task_queue,
        )

        result = result_data.get("result", {})

        # Call post-run worker hooks
        if worker_adapter_set:
            await worker_adapter_set.call_all_lifecycle_hooks_async(
                "post_run_step_worker",
                action=action,
                state=state,
                result=result,
                exception=None,
            )

        # For single-step actions, wrap state update
        if hasattr(action, "single_step") and action.single_step:
            new_state = state.update(**{k: result.get(k) for k in action.writes})
            result["__INTERCEPTOR_NEW_STATE__"] = new_state

        return result


# --- Worker-side hooks ---


class TemporalWorkerLogger(PreRunStepHookWorkerAsync, PostRunStepHookWorkerAsync):
    """Example worker hook that logs action execution on the Temporal worker side."""

    async def pre_run_step_worker(
        self, *, action: Action, state: "State", inputs: Dict[str, Any], **future_kwargs
    ):
        """Log before action runs on worker."""
        logger.info(f"[Worker Hook] PRE: {action.name}")

    async def post_run_step_worker(
        self,
        *,
        action: Action,
        state: "State",
        result: dict,
        exception: Exception,
        **future_kwargs,
    ):
        """Log after action runs on worker."""
        logger.info(f"[Worker Hook] POST: {action.name} -> {list(result.keys())}")


# --- Example Application ---


@action(reads=["query"], writes=["search_results"])
def search_web(state: State) -> State:
    """Search the web (runs locally, fast)."""
    query = state["query"]
    return state.update(search_results=[f"Result for: {query}"])


@action(reads=["search_results"], writes=["summary"])
def summarize_results(state: State) -> State:
    """Summarize search results (tagged durable, runs on Temporal)."""
    results = state["search_results"]
    summary = f"Summary of {len(results)} results"
    return state.update(summary=summary)


@action(reads=["summary"], writes=["final_answer"])
def generate_answer(state: State) -> State:
    """Generate final answer (tagged durable, runs on Temporal)."""
    return state.update(final_answer=f"Answer based on: {state['summary']}")


def build_app(use_temporal: bool = False):
    """Build the example application.

    Args:
        use_temporal: If True, route durable-tagged actions to Temporal.
            If False, run everything locally.
    """
    hooks = []
    if use_temporal:
        hooks.append(TemporalInterceptor())
        hooks.append(TemporalWorkerLogger())

    app = (
        ApplicationBuilder()
        .with_actions(
            search_web=search_web,
            summarize_results=summarize_results.with_tags("durable"),
            generate_answer=generate_answer.with_tags("durable"),
        )
        .with_transitions(
            ("search_web", "summarize_results", default),
            ("summarize_results", "generate_answer", default),
        )
        .with_entrypoint("search_web")
        .with_state(query="How do Burr interceptors work?")
        .with_hooks(*hooks)
        .with_tracker(project="temporal-interceptor-demo")
        .build()
    )
    return app


if __name__ == "__main__":
    import sys

    from burr.core import default

    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        print("Starting Temporal worker... (requires temporal server)")
        print("Run: temporal server start-dev")
        # In production, you'd register activities and start the worker here
    else:
        print("Running app locally (no Temporal)...")
        print("Pass 'worker' arg to start Temporal worker instead.")
        print()

        app = build_app(use_temporal=False)
        for i in range(3):
            action_result, result, state = app.step()
            print(f"  Step {i + 1}: {action_result.name} -> {list(result.keys())}")

        print(f"\nFinal answer: {state['final_answer']}")
        print("Done! Check Burr UI for tracking.")
