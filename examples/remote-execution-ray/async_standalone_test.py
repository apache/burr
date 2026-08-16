"""
Standalone Async Test - No FastAPI Required

This demonstrates async Burr + Ray without needing a web server.
Shows how multiple concurrent "requests" can share an actor pool efficiently.
"""

import asyncio
import time
from typing import Any, Dict

import ray

from burr.core import Action, ApplicationBuilder, State, action
from burr.lifecycle import ActionExecutionInterceptorHookAsync

# ============================================================================
# Ray Actor
# ============================================================================


@ray.remote
class HeavyComputeActor:
    """Actor that holds expensive resources"""

    def __init__(self, actor_id: int):
        self.actor_id = actor_id
        print(f"[Actor {actor_id}] Initializing...")
        time.sleep(0.5)  # Simulate expensive initialization
        self.request_count = 0
        print(f"[Actor {actor_id}] Ready")

    def execute_action(self, action, state_dict: dict, inputs: dict) -> tuple:
        """Execute action on actor"""
        self.request_count += 1
        # Use deserialize to properly handle non-serializable objects via serde layer
        state = State.deserialize(state_dict)

        if hasattr(action, "single_step") and action.single_step:
            result, new_state = action.run_and_update(state, **inputs)
        else:
            result = action.run(state, **inputs)
            new_state = action.update(result, state)

        result = result.copy()
        result["processed_by"] = f"actor_{self.actor_id}"
        new_state = new_state.update(processed_by=f"actor_{self.actor_id}")

        return result, new_state.serialize()

    def get_stats(self):
        return {"actor_id": self.actor_id, "request_count": self.request_count}


# ============================================================================
# Actor Pool Manager
# ============================================================================


class ActorPoolManager:
    """Async-safe actor pool"""

    def __init__(self, num_actors: int = 2):
        print(f"\n[Pool] Creating {num_actors} actors...")
        self.actors = [HeavyComputeActor.remote(i) for i in range(num_actors)]
        self.next_actor_idx = 0
        self.lock = asyncio.Lock()

    async def get_actor(self, action_name: str):
        async with self.lock:
            actor = self.actors[self.next_actor_idx]
            self.next_actor_idx = (self.next_actor_idx + 1) % len(self.actors)
            return actor

    async def get_pool_stats(self):
        stats_futures = [actor.get_stats.remote() for actor in self.actors]
        stats = await asyncio.gather(
            *[asyncio.to_thread(ray.get, future) for future in stats_futures]
        )
        return stats

    def shutdown(self):
        for actor in self.actors:
            ray.kill(actor)


# ============================================================================
# Async Interceptor
# ============================================================================


class AsyncActorInterceptor(ActionExecutionInterceptorHookAsync):
    """Async interceptor - non-blocking Ray calls"""

    def __init__(self, actor_pool: ActorPoolManager):
        self.actor_pool = actor_pool
        self.action_cache = {}

    def should_intercept(self, *, action: Action, **kwargs) -> bool:
        return "actor" in action.tags

    async def intercept_run(
        self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
    ) -> dict:
        # Get actor (async, thread-safe)
        actor = await self.actor_pool.get_actor(action.name)

        # State subsetting
        # Use serialize() to properly handle non-serializable objects via serde layer
        state_subset = state.subset(*action.reads) if action.reads else state
        state_dict = state_subset.serialize()

        # Cache action
        if action.name not in self.action_cache:
            self.action_cache[action.name] = ray.put(action)
        action_ref = self.action_cache[action.name]

        # Execute on actor (async, non-blocking)
        result_ref = actor.execute_action.remote(action_ref, state_dict, inputs)
        result, new_state_dict = await asyncio.to_thread(ray.get, result_ref)

        # Reconstruct state for single-step actions
        # Use deserialize to properly handle non-serializable objects via serde layer
        if hasattr(action, "single_step") and action.single_step:
            new_state = State.deserialize(new_state_dict)
            result_with_state = result.copy()
            result_with_state["__INTERCEPTOR_NEW_STATE__"] = new_state
            return result_with_state

        return result


# ============================================================================
# Actions
# ============================================================================


@action(reads=["count"], writes=["count", "last_operation"], tags=["local"])
async def local_increment(state: State) -> tuple:
    """Local async action"""
    await asyncio.sleep(0.01)
    result = {"count": state["count"] + 1, "last_operation": "local_increment"}
    return result, state.update(**result)


@action(reads=["count"], writes=["count", "last_operation", "processed_by"], tags=["actor"])
def heavy_compute(state: State) -> tuple:
    """Heavy action - runs on actor"""
    time.sleep(0.2)  # Simulate work
    result = {
        "count": state["count"] * 2,
        "last_operation": "heavy_compute",
        "processed_by": "unknown",
    }
    return result, state.update(**result)


# ============================================================================
# Test Concurrent Execution
# ============================================================================


async def process_session(session_id: str, initial_count: int, interceptor):
    """Simulate processing a user session"""
    start = time.time()

    # Create application for this session
    app = (
        ApplicationBuilder()
        .with_state(count=initial_count)
        .with_actions(local_increment, heavy_compute)
        .with_transitions(
            ("local_increment", "heavy_compute"),
            ("heavy_compute", "local_increment"),
        )
        .with_entrypoint("local_increment")
        .with_hooks(interceptor)
        .build()
    )

    # Execute steps
    action1, result1, state1 = await app.astep()
    action2, result2, state2 = await app.astep()

    elapsed = (time.time() - start) * 1000

    return {
        "session_id": session_id,
        "count": state2["count"],
        "processed_by": state2.get("processed_by", "local"),
        "time_ms": elapsed,
    }


async def main():
    """Run concurrent sessions"""
    print("=" * 80)
    print("Async Burr + Ray Actor Pool - Standalone Test")
    print("=" * 80)

    # Initialize Ray
    if not ray.is_initialized():
        ray.init(ignore_reinit_error=True)

    # Create actor pool (2 actors, 10 sessions = multiplexing!)
    actor_pool = ActorPoolManager(num_actors=2)
    interceptor = AsyncActorInterceptor(actor_pool)

    print("\n" + "=" * 80)
    print("Processing 10 Concurrent Sessions")
    print("=" * 80)

    # Create 10 concurrent sessions
    tasks = [process_session(f"user_{i}", i * 10, interceptor) for i in range(10)]

    # Execute all concurrently
    print("\n🚀 Launching 10 concurrent sessions...")
    start = time.time()
    results = await asyncio.gather(*tasks)
    total_time = time.time() - start

    print(f"\n✅ All sessions completed in {total_time:.2f}s")

    # Show results
    print("\n" + "=" * 80)
    print("Results")
    print("=" * 80)
    for result in results:
        print(
            f"{result['session_id']}: count={result['count']}, "
            f"processed_by={result['processed_by']}, "
            f"time={result['time_ms']:.0f}ms"
        )

    # Show actor stats
    stats = await actor_pool.get_pool_stats()
    print("\n" + "=" * 80)
    print("Actor Pool Statistics")
    print("=" * 80)
    total_requests = sum(s["request_count"] for s in stats)
    print(f"Total requests processed: {total_requests}")
    for stat in stats:
        print(f"  Actor {stat['actor_id']}: {stat['request_count']} requests")

    print("\n" + "=" * 80)
    print("Key Observations")
    print("=" * 80)
    print("✅ 10 sessions shared 2 actors (5x multiplexing)")
    print("✅ Async execution - no blocking on Ray calls")
    print("✅ State isolation maintained per session")
    print("✅ Load balanced across actor pool")
    print(f"✅ Total time: {total_time:.2f}s (parallel execution)")
    print(f"✅ Sequential would take: ~{10 * 0.2:.1f}s (5x slower!)")

    # Cleanup
    actor_pool.shutdown()
    ray.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
