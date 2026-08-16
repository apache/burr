"""
Example: Actor-Based Execution with Ray

This demonstrates using Ray Actors to multiplex requests across multiple
Burr Application instances, enabling resource reuse and better utilization.

Key differences from basic interceptor:
1. Actors are long-lived (not created per request)
2. Actors hold expensive resources (models, connections)
3. Multiple applications can use the same Actor pool
4. State is still passed with each request (stateless actors)
"""

import time
from collections import defaultdict
from typing import Any, Dict

import ray

from burr.core import Action, ApplicationBuilder, State, action
from burr.lifecycle import ActionExecutionInterceptorHook

# ============================================================================
# Step 1: Define Ray Actors that hold expensive resources
# ============================================================================


@ray.remote
class HeavyComputeActor:
    """
    Actor that holds expensive resources and can handle multiple requests.
    This simulates holding a loaded ML model, database connection, etc.
    """

    def __init__(self, actor_id: int):
        self.actor_id = actor_id
        print(f"[Actor {actor_id}] Initializing expensive resources...")
        time.sleep(1)  # Simulate expensive initialization
        self.expensive_resource = f"ModelV1_{actor_id}"  # Simulated model
        self.request_count = 0
        print(f"[Actor {actor_id}] Ready to handle requests")

    def execute_action(self, action, state_dict: dict, inputs: dict) -> tuple:
        """
        Execute action using the actor's resources.

        The action object (from Ray object store) contains the actual code to run!
        State dict only contains the keys the action reads (subset).
        This maintains state isolation between applications.
        """
        self.request_count += 1
        print(f"[Actor {self.actor_id}] Request #{self.request_count}: {action.name}")

        # Reconstruct state from dict (this is already subsetted to action.reads)
        # Use deserialize to properly handle non-serializable objects via serde layer
        state = State.deserialize(state_dict)

        # Execute the ACTUAL action code!
        # The action's implementation runs here on the actor
        if hasattr(action, "single_step") and action.single_step:
            # Single-step actions do run_and_update
            result, new_state = action.run_and_update(state, **inputs)
        else:
            # Multi-step actions do run + update separately
            result = action.run(state, **inputs)
            new_state = action.update(result, state)

        # Inject which actor processed it (useful for debugging)
        result = result.copy()
        result["processed_by"] = f"actor_{self.actor_id}"
        new_state = new_state.update(processed_by=f"actor_{self.actor_id}")

        return result, new_state.serialize()

    def get_stats(self):
        """Get actor statistics"""
        return {
            "actor_id": self.actor_id,
            "request_count": self.request_count,
            "resource": self.expensive_resource,
        }


# ============================================================================
# Step 2: Create an Actor Pool Manager
# ============================================================================


class ActorPoolManager:
    """
    Manages a pool of Ray Actors for action execution.
    Handles round-robin distribution of requests.
    """

    def __init__(self, num_actors: int = 2):
        print(f"[ActorPool] Creating pool with {num_actors} actors...")
        self.actors = [HeavyComputeActor.remote(i) for i in range(num_actors)]
        self.next_actor_idx = 0
        self.stats = defaultdict(int)
        print(f"[ActorPool] Pool ready with {len(self.actors)} actors")

    def get_actor(self, action_name: str) -> Any:
        """
        Get next available actor (round-robin).

        In production, this could be:
        - Load-based routing
        - Action-specific actor pools
        - Locality-aware routing
        """
        actor = self.actors[self.next_actor_idx]
        self.next_actor_idx = (self.next_actor_idx + 1) % len(self.actors)
        self.stats[action_name] += 1
        return actor

    def get_pool_stats(self):
        """Get statistics from all actors"""
        stats_futures = [actor.get_stats.remote() for actor in self.actors]
        stats = ray.get(stats_futures)
        return {
            "actors": stats,
            "total_requests": sum(self.stats.values()),
            "requests_by_action": dict(self.stats),
        }

    def shutdown(self):
        """Cleanup actors"""
        for actor in self.actors:
            ray.kill(actor)


# ============================================================================
# Step 3: Create Actor-Based Interceptor
# ============================================================================


class ActorBasedInterceptor(ActionExecutionInterceptorHook):
    """
    Interceptor that routes actions to a pool of Ray Actors.

    Key differences from function-based interceptor:
    1. Uses persistent Actors instead of spawning functions
    2. Actors are shared across application instances
    3. Enables resource reuse and multiplexing
    """

    def __init__(self, actor_pool: ActorPoolManager):
        self.actor_pool = actor_pool
        self.ray_initialized = False

    def _ensure_ray_initialized(self):
        if not self.ray_initialized:
            if not ray.is_initialized():
                print("[Interceptor] Initializing Ray...")
                ray.init(ignore_reinit_error=True)
            self.ray_initialized = True

    def should_intercept(self, *, action: Action, **kwargs) -> bool:
        """Intercept actions tagged with 'actor'"""
        return "actor" in action.tags

    def intercept_run(
        self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
    ) -> dict:
        """Route action to an actor from the pool"""
        self._ensure_ray_initialized()

        # Get actor from pool
        actor = self.actor_pool.get_actor(action.name)

        print(f"[Interceptor] Routing {action.name} to actor pool...")

        # Only pass the state keys that the action actually reads
        # This reduces serialization overhead
        # Use serialize() to properly handle non-serializable objects via serde layer
        state_subset = state.subset(*action.reads) if action.reads else state
        state_dict = state_subset.serialize()

        # Put action in object store once (reusable across calls)
        # For frequently called actions, this avoids re-serialization
        action_ref = ray.put(action)

        # Execute on actor
        # The actor will call action.run_and_update() with the action's actual code
        result_ref = actor.execute_action.remote(
            action_ref,  # ← Object store reference (efficient for repeated calls)
            state_dict,  # ← Only the subset of state this action needs
            inputs,
        )
        result, new_state_dict = ray.get(result_ref)

        print("[Interceptor] Received result from actor")

        # For single-step actions, reconstruct state
        # Use deserialize to properly handle non-serializable objects via serde layer
        if hasattr(action, "single_step") and action.single_step:
            new_state = State.deserialize(new_state_dict)
            result_with_state = result.copy()
            result_with_state["__INTERCEPTOR_NEW_STATE__"] = new_state
            return result_with_state

        return result


# ============================================================================
# Step 4: Define Actions
# ============================================================================


@action(reads=["count"], writes=["count", "last_operation"], tags=["local"])
def local_increment(state: State) -> tuple:
    """Local action - no actor"""
    result = {
        "count": state["count"] + 1,
        "last_operation": "local_increment",
    }
    return result, state.update(**result)


@action(reads=["count"], writes=["count", "last_operation", "processed_by"], tags=["actor"])
def heavy_compute_actor(state: State) -> tuple:
    """Heavy action - runs on actor pool"""
    # THIS CODE ACTUALLY RUNS ON THE ACTOR!
    import time

    print(f"🔧 Computing on actor: count={state['count']}")
    time.sleep(0.3)  # Simulate expensive work

    result = {
        "count": state["count"] * 2,
        "last_operation": "heavy_compute_actor",
        "processed_by": "unknown",  # Actor will set this
    }
    return result, state.update(**result)


# ============================================================================
# Step 5: Demonstrate Multiple Applications Using Same Actor Pool
# ============================================================================


def run_multiple_applications():
    """
    Demonstrate multiple application instances sharing the same actor pool.
    This is the key benefit: resource reuse across applications.
    """
    print("=" * 80)
    print("Actor-Based Execution: Multiple Applications")
    print("=" * 80)
    print()

    # Initialize Ray and create actor pool
    if not ray.is_initialized():
        ray.init(ignore_reinit_error=True)

    # Create shared actor pool (expensive resources loaded once)
    actor_pool = ActorPoolManager(num_actors=2)

    # Create interceptor (shared across all applications)
    interceptor = ActorBasedInterceptor(actor_pool)

    # Create multiple application instances
    # Each represents a different user/session
    apps = []
    for i in range(10):
        app = (
            ApplicationBuilder()
            .with_state(count=i * 10)  # Different initial state
            .with_actions(local_increment, heavy_compute_actor)
            .with_transitions(
                ("local_increment", "heavy_compute_actor"),
                ("heavy_compute_actor", "local_increment"),
            )
            .with_entrypoint("local_increment")
            .with_hooks(interceptor)
            .build()
        )
        apps.append(app)
        print(f"Created Application {i} (initial count={i * 10})")

    print("\n" + "=" * 80)
    print("Executing Actions Across Multiple Applications")
    print("=" * 80)
    print()

    # Execute steps on all applications
    # They'll share the same actor pool
    for step in range(2):
        print(f"\n--- Step {step + 1} ---")
        for i, app in enumerate(apps):
            action, result, state = app.step()
            print(
                f"App {i}: {action.name} -> count={state['count']}, "
                f"processed_by={state.get('processed_by', 'local')}"
            )

    # Show actor pool statistics
    print("\n" + "=" * 80)
    print("Actor Pool Statistics")
    print("=" * 80)
    stats = actor_pool.get_pool_stats()
    print(f"Total requests processed: {stats['total_requests']}")
    print(f"Requests by action: {stats['requests_by_action']}")
    print("\nActor details:")
    for actor_stat in stats["actors"]:
        print(f"  Actor {actor_stat['actor_id']}: {actor_stat['request_count']} requests")

    # Cleanup
    actor_pool.shutdown()
    ray.shutdown()

    print("\n" + "=" * 80)
    print("Key Observations:")
    print("=" * 80)
    print("1. ✅ Multiple applications shared 2 actors")
    print("2. ✅ Expensive resources loaded only once (in actors)")
    print("3. ✅ State remained isolated per application")
    print("4. ✅ Requests distributed across actor pool")
    print("5. ✅ Significant resource savings vs. per-request initialization")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    run_multiple_applications()
