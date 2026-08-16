"""
Example demonstrating how to use Burr's action execution interceptors to run
actions remotely on Ray workers.

This example shows:
1. How to create a RayActionInterceptor to execute actions on Ray
2. How worker hooks run on the remote Ray worker
3. How to mix local and remote execution based on action tags
"""

import time
from typing import Any, Dict, Optional

import ray

from burr.core import Action, ApplicationBuilder, State, action
from burr.lifecycle import (
    ActionExecutionInterceptorHook,
    PostRunStepHook,
    PostRunStepHookWorker,
    PreRunStepHook,
    PreRunStepHookWorker,
)


# Define some example actions
@action(reads=["count"], writes=["count", "last_operation"], tags=["local"])
def increment_local(state: State) -> tuple:
    """Increment counter locally (not on Ray)"""
    result = {
        "count": state["count"] + 1,
        "last_operation": "increment_local",
    }
    return result, state.update(**result)


@action(reads=["count"], writes=["count", "last_operation"], tags=["ray"])
def heavy_computation(state: State, multiplier: int = 2) -> tuple:
    """Simulate heavy computation that should run on Ray"""
    print(f"[Ray Worker] Running heavy computation with multiplier={multiplier}")
    time.sleep(0.5)  # Simulate work
    result = {
        "count": state["count"] * multiplier,
        "last_operation": f"heavy_computation(x{multiplier})",
    }
    return result, state.update(**result)


@action(reads=["count"], writes=["count", "last_operation"], tags=["ray"])
def another_ray_task(state: State) -> tuple:
    """Another task that runs on Ray"""
    print("[Ray Worker] Running another Ray task")
    time.sleep(0.3)  # Simulate work
    result = {
        "count": state["count"] + 10,
        "last_operation": "another_ray_task(+10)",
    }
    return result, state.update(**result)


# Orchestrator hooks (run on main process)
class OrchestratorPreHook(PreRunStepHook):
    """Hook that runs on the main process before action execution"""

    def pre_run_step(self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs):
        print(f"[Main Process] About to execute action: {action.name}")


class OrchestratorPostHook(PostRunStepHook):
    """Hook that runs on the main process after action execution"""

    def post_run_step(
        self,
        *,
        action: Action,
        state: State,
        result: Optional[Dict[str, Any]],
        exception: Exception,
        **kwargs,
    ):
        print(f"[Main Process] Finished executing action: {action.name}")


# Worker hooks (run on Ray workers)
class WorkerPreHook(PreRunStepHookWorker):
    """Hook that runs on the Ray worker before action execution"""

    def pre_run_step_worker(
        self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
    ):
        print(f"[Ray Worker] Starting action: {action.name} on Ray worker")


class WorkerPostHook(PostRunStepHookWorker):
    """Hook that runs on the Ray worker after action execution"""

    def post_run_step_worker(
        self,
        *,
        action: Action,
        state: State,
        result: Optional[Dict[str, Any]],
        exception: Exception,
        **kwargs,
    ):
        print(f"[Ray Worker] Completed action: {action.name} on Ray worker")


# Ray Execution Interceptor
class RayActionInterceptor(ActionExecutionInterceptorHook):
    """Interceptor that executes actions tagged with 'ray' on Ray workers"""

    def __init__(self):
        self.ray_initialized = False

    def _ensure_ray_initialized(self):
        """Initialize Ray if not already initialized"""
        if not self.ray_initialized:
            if not ray.is_initialized():
                print("[Main Process] Initializing Ray...")
                ray.init(ignore_reinit_error=True)
            self.ray_initialized = True

    def should_intercept(self, *, action: Action, **kwargs) -> bool:
        """Intercept actions tagged with 'ray'"""
        return "ray" in action.tags

    def intercept_run(
        self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
    ) -> dict:
        """Execute the action on a Ray worker"""
        self._ensure_ray_initialized()

        print(f"[Main Process] Dispatching {action.name} to Ray...")

        # Extract worker hooks
        worker_adapter_set = kwargs.get("worker_adapter_set")

        # Serialize state before sending to remote worker
        # Use serialize() to properly handle non-serializable objects via serde layer
        state_subset = state.subset(*action.reads) if action.reads else state
        state_dict = state_subset.serialize()

        # Create a Ray remote function that executes the action
        @ray.remote
        def execute_on_ray(state_dict, worker_adapter_set, action, inputs):
            """Execute action on Ray worker with worker hooks"""
            # Deserialize state on worker side
            # Use deserialize to properly handle non-serializable objects via serde layer
            state = State.deserialize(state_dict)

            # Call pre-worker hooks
            if worker_adapter_set:
                worker_adapter_set.call_all_lifecycle_hooks_sync(
                    "pre_run_step_worker",
                    action=action,
                    state=state,
                    inputs=inputs,
                )

            # Execute the action
            if hasattr(action, "single_step") and action.single_step:
                result, new_state = action.run_and_update(state, **inputs)
            else:
                state_to_use = state.subset(*action.reads)
                result = action.run(state_to_use, **inputs)
                new_state = None

            # Call post-worker hooks
            if worker_adapter_set:
                worker_adapter_set.call_all_lifecycle_hooks_sync(
                    "post_run_step_worker",
                    action=action,
                    state=state,
                    result=result,
                    exception=None,
                )

            # Serialize new_state before returning
            new_state_dict = new_state.serialize() if new_state is not None else None
            return result, new_state_dict

        # Execute remotely and wait for result
        result_ref = execute_on_ray.remote(state_dict, worker_adapter_set, action, inputs)
        result, new_state_dict = ray.get(result_ref)

        print(f"[Main Process] Received result from Ray for {action.name}")

        # For single-step actions, include the new state
        # Deserialize new_state to properly handle non-serializable objects via serde layer
        if new_state_dict is not None:
            new_state = State.deserialize(new_state_dict)
            result_with_state = result.copy()
            result_with_state["__INTERCEPTOR_NEW_STATE__"] = new_state
            return result_with_state

        return result


def main():
    """Run the example application"""
    print("=" * 80)
    print("Burr + Ray Remote Execution Example")
    print("=" * 80)
    print()

    # Create interceptor and hooks
    ray_interceptor = RayActionInterceptor()
    orchestrator_pre = OrchestratorPreHook()
    orchestrator_post = OrchestratorPostHook()
    worker_pre = WorkerPreHook()
    worker_post = WorkerPostHook()

    # Build the application
    app = (
        ApplicationBuilder()
        .with_state(count=0)
        .with_actions(
            increment_local,
            heavy_computation,
            another_ray_task,
        )
        .with_transitions(
            ("increment_local", "heavy_computation"),
            ("heavy_computation", "another_ray_task"),
            ("another_ray_task", "increment_local"),
        )
        .with_entrypoint("increment_local")
        .with_hooks(
            ray_interceptor,
            orchestrator_pre,
            orchestrator_post,
            worker_pre,
            worker_post,
        )
        .build()
    )

    # Execute steps
    print("\n" + "=" * 80)
    print("Step 1: Local execution (increment_local)")
    print("=" * 80)
    action, result, state = app.step()
    print(f"Result: count={state['count']}, operation={state['last_operation']}")

    print("\n" + "=" * 80)
    print("Step 2: Ray execution (heavy_computation)")
    print("=" * 80)
    action, result, state = app.step(inputs={"multiplier": 3})
    print(f"Result: count={state['count']}, operation={state['last_operation']}")

    print("\n" + "=" * 80)
    print("Step 3: Ray execution (another_ray_task)")
    print("=" * 80)
    action, result, state = app.step()
    print(f"Result: count={state['count']}, operation={state['last_operation']}")

    print("\n" + "=" * 80)
    print("Step 4: Back to local execution (increment_local)")
    print("=" * 80)
    action, result, state = app.step()
    print(f"Result: count={state['count']}, operation={state['last_operation']}")

    print("\n" + "=" * 80)
    print("Final State:")
    print("=" * 80)
    print(f"Count: {state['count']}")
    print(f"Last Operation: {state['last_operation']}")

    # Shutdown Ray
    if ray.is_initialized():
        print("\n[Main Process] Shutting down Ray...")
        ray.shutdown()

    print("\n" + "=" * 80)
    print("Example completed successfully!")
    print("=" * 80)


if __name__ == "__main__":
    main()
