"""
FastAPI + Burr + Ray Actor Pool - Async Example

This demonstrates:
1. FastAPI async endpoints receiving concurrent requests
2. Async interceptor that dispatches to Ray actors without blocking
3. Multiple requests sharing an actor pool efficiently
4. Non-blocking execution with proper async/await patterns
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, Dict

import ray
from fastapi import FastAPI
from pydantic import BaseModel

from burr.core import Action, ApplicationBuilder, State, action
from burr.lifecycle import ActionExecutionInterceptorHookAsync

# ============================================================================
# Ray Actor (same as before, but we'll call it async)
# ============================================================================


@ray.remote
class HeavyComputeActor:
    """
    Actor that holds expensive resources (ML models, DB connections, etc.)
    and can handle multiple requests without reloading.
    """

    def __init__(self, actor_id: int):
        self.actor_id = actor_id
        print(f"[Actor {actor_id}] Initializing expensive resources...")
        time.sleep(1)  # Simulate expensive initialization (model loading)
        self.expensive_resource = f"ModelV1_{actor_id}"
        self.request_count = 0
        print(f"[Actor {actor_id}] Ready to handle requests")

    def execute_action(self, action, state_dict: dict, inputs: dict) -> tuple:
        """
        Execute action using the actor's resources.
        This is called from async context but the method itself is sync.
        """
        self.request_count += 1
        request_id = self.request_count
        print(f"[Actor {self.actor_id}] Request #{request_id}: {action.name}")

        # Reconstruct state (already subsetted to action.reads)
        # Use deserialize to properly handle non-serializable objects via serde layer
        state = State.deserialize(state_dict)

        # Execute the ACTUAL action code
        if hasattr(action, "single_step") and action.single_step:
            result, new_state = action.run_and_update(state, **inputs)
        else:
            result = action.run(state, **inputs)
            new_state = action.update(result, state)

        # Inject metadata
        result = result.copy()
        result["processed_by"] = f"actor_{self.actor_id}"
        result["request_number"] = request_id
        new_state = new_state.update(
            processed_by=f"actor_{self.actor_id}", request_number=request_id
        )

        return result, new_state.serialize()

    def get_stats(self):
        """Get actor statistics"""
        return {
            "actor_id": self.actor_id,
            "request_count": self.request_count,
            "resource": self.expensive_resource,
        }


# ============================================================================
# Actor Pool Manager
# ============================================================================


class ActorPoolManager:
    """Manages a pool of Ray Actors with async-friendly interface"""

    def __init__(self, num_actors: int = 2):
        print(f"[ActorPool] Creating pool with {num_actors} actors...")
        self.actors = [HeavyComputeActor.remote(i) for i in range(num_actors)]
        self.next_actor_idx = 0
        self.lock = asyncio.Lock()
        print(f"[ActorPool] Pool ready with {len(self.actors)} actors")

    async def get_actor(self, action_name: str):
        """Get next available actor (round-robin) - async safe"""
        async with self.lock:
            actor = self.actors[self.next_actor_idx]
            self.next_actor_idx = (self.next_actor_idx + 1) % len(self.actors)
            return actor

    async def get_pool_stats(self):
        """Get statistics from all actors - async"""
        stats_futures = [actor.get_stats.remote() for actor in self.actors]
        # Use asyncio to wait for ray futures
        stats = await asyncio.gather(
            *[asyncio.to_thread(ray.get, future) for future in stats_futures]
        )
        return {
            "actors": stats,
            "total_requests": sum(s["request_count"] for s in stats),
        }

    def shutdown(self):
        """Cleanup actors"""
        for actor in self.actors:
            ray.kill(actor)


# ============================================================================
# Async Interceptor for Ray Actors
# ============================================================================


class AsyncActorBasedInterceptor(ActionExecutionInterceptorHookAsync):
    """
    Async interceptor that routes actions to Ray Actors without blocking.

    Key features:
    - Async actor selection (thread-safe)
    - Non-blocking Ray calls using asyncio.to_thread()
    - State subsetting for efficiency
    - Object store optimization for actions
    """

    def __init__(self, actor_pool: ActorPoolManager):
        self.actor_pool = actor_pool
        self.ray_initialized = False
        self.action_cache = {}

    def _ensure_ray_initialized(self):
        if not self.ray_initialized:
            if not ray.is_initialized():
                print("[Interceptor] Initializing Ray...")
                ray.init(ignore_reinit_error=True)
            self.ray_initialized = True

    def should_intercept(self, *, action: Action, **kwargs) -> bool:
        """Intercept actions tagged with 'actor'"""
        return "actor" in action.tags

    async def intercept_run(
        self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
    ) -> dict:
        """
        Route action to an actor from the pool - ASYNC version.

        This doesn't block the event loop while waiting for Ray.
        """
        self._ensure_ray_initialized()

        # Get actor from pool (async, thread-safe)
        actor = await self.actor_pool.get_actor(action.name)

        print(f"[Interceptor] Routing {action.name} to actor pool (async)...")

        # Only pass the state subset the action needs
        # Use serialize() to properly handle non-serializable objects via serde layer
        state_subset = state.subset(*action.reads) if action.reads else state
        state_dict = state_subset.serialize()

        # Cache action in object store (optimization)
        if action.name not in self.action_cache:
            self.action_cache[action.name] = ray.put(action)
        action_ref = self.action_cache[action.name]

        # Execute on actor - use asyncio.to_thread to avoid blocking
        result_ref = actor.execute_action.remote(action_ref, state_dict, inputs)

        # Wait for result without blocking the event loop
        result, new_state_dict = await asyncio.to_thread(ray.get, result_ref)

        print("[Interceptor] Received result from actor (async)")

        # For single-step actions, reconstruct state
        # Use deserialize to properly handle non-serializable objects via serde layer
        if hasattr(action, "single_step") and action.single_step:
            new_state = State.deserialize(new_state_dict)
            result_with_state = result.copy()
            result_with_state["__INTERCEPTOR_NEW_STATE__"] = new_state
            return result_with_state

        return result


# ============================================================================
# Define Burr Actions
# ============================================================================


@action(reads=["count"], writes=["count", "last_operation"], tags=["local"])
async def local_increment(state: State) -> tuple:
    """Local async action - no actor"""
    await asyncio.sleep(0.01)  # Simulate async work
    result = {
        "count": state["count"] + 1,
        "last_operation": "local_increment",
    }
    return result, state.update(**result)


@action(
    reads=["count"],
    writes=["count", "last_operation", "processed_by", "request_number"],
    tags=["actor"],
)
def heavy_compute_actor(state: State) -> tuple:
    """Heavy action - runs on actor pool"""
    # THIS CODE RUNS ON THE ACTOR!
    import time

    print(f"🔧 Computing on actor: count={state['count']}")
    time.sleep(0.3)  # Simulate expensive work

    result = {
        "count": state["count"] * 2,
        "last_operation": "heavy_compute_actor",
        "processed_by": "unknown",
        "request_number": 0,
    }
    return result, state.update(**result)


# ============================================================================
# FastAPI Application
# ============================================================================

# Global actor pool (initialized on startup)
actor_pool = None
interceptor = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize Ray and actor pool on startup, cleanup on shutdown"""
    global actor_pool, interceptor

    print("\n" + "=" * 80)
    print("FastAPI + Burr + Ray - Async Actor Pool Example")
    print("=" * 80 + "\n")

    # Initialize Ray
    if not ray.is_initialized():
        ray.init(ignore_reinit_error=True)

    # Create actor pool (expensive resources loaded once)
    actor_pool = ActorPoolManager(num_actors=3)

    # Create interceptor
    interceptor = AsyncActorBasedInterceptor(actor_pool)

    print("\n✅ Server ready to handle requests\n")

    yield

    # Cleanup
    print("\n🛑 Shutting down...")
    actor_pool.shutdown()
    ray.shutdown()


app = FastAPI(lifespan=lifespan)


# ============================================================================
# Request/Response Models
# ============================================================================


class ComputeRequest(BaseModel):
    session_id: str
    initial_count: int = 0


class ComputeResponse(BaseModel):
    session_id: str
    count: int
    last_operation: str
    processed_by: str
    request_number: int
    processing_time_ms: float


# ============================================================================
# FastAPI Endpoints
# ============================================================================


@app.post("/compute", response_model=ComputeResponse)
async def compute(request: ComputeRequest):
    """
    Execute a computation on Ray actors without blocking.

    Multiple concurrent requests will be distributed across the actor pool.
    """
    start_time = time.time()

    print(f"\n[FastAPI] Received request from session: {request.session_id}")

    # Create a Burr application for this request
    # Each request gets its own application instance (own state)
    app = (
        ApplicationBuilder()
        .with_state(count=request.initial_count)
        .with_actions(local_increment, heavy_compute_actor)
        .with_transitions(
            ("local_increment", "heavy_compute_actor"),
            ("heavy_compute_actor", "local_increment"),
        )
        .with_entrypoint("local_increment")
        .with_hooks(interceptor)
        .build()
    )

    # Execute two steps (increment -> heavy compute)
    action1, result1, state1 = await app.astep()
    action2, result2, state2 = await app.astep()

    processing_time = (time.time() - start_time) * 1000

    print(
        f"[FastAPI] Completed request from session: {request.session_id} "
        f"in {processing_time:.1f}ms"
    )

    return ComputeResponse(
        session_id=request.session_id,
        count=state2["count"],
        last_operation=state2["last_operation"],
        processed_by=state2.get("processed_by", "unknown"),
        request_number=state2.get("request_number", 0),
        processing_time_ms=processing_time,
    )


@app.get("/stats")
async def get_stats():
    """Get actor pool statistics"""
    if actor_pool is None:
        return {"error": "Actor pool not initialized"}

    stats = await actor_pool.get_pool_stats()
    return stats


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "ray_initialized": ray.is_initialized(),
        "actor_pool_active": actor_pool is not None,
    }


# ============================================================================
# Test Client (for demonstration)
# ============================================================================


async def test_concurrent_requests():
    """
    Simulate concurrent requests to demonstrate non-blocking execution.
    """
    import httpx

    print("\n" + "=" * 80)
    print("Testing Concurrent Requests")
    print("=" * 80 + "\n")

    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # Send 10 concurrent requests
        tasks = []
        for i in range(10):
            request_data = {
                "session_id": f"user_{i}",
                "initial_count": i * 10,
            }
            tasks.append(client.post("/compute", json=request_data))

        # Wait for all to complete
        print("Sending 10 concurrent requests...")
        start = time.time()
        responses = await asyncio.gather(*tasks)
        elapsed = time.time() - start

        print(f"\n✅ All requests completed in {elapsed:.2f}s\n")

        # Show results
        for response in responses:
            data = response.json()
            print(
                f"Session {data['session_id']}: "
                f"count={data['count']}, "
                f"processed_by={data['processed_by']}, "
                f"time={data['processing_time_ms']:.1f}ms"
            )

        # Show stats
        stats_response = await client.get("/stats")
        stats = stats_response.json()
        print("\n📊 Actor Pool Statistics:")
        print(f"   Total requests: {stats['total_requests']}")
        for actor in stats["actors"]:
            print(f"   Actor {actor['actor_id']}: {actor['request_count']} requests")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Run test client
        async def run_test():
            # Wait for server to be ready
            await asyncio.sleep(2)
            await test_concurrent_requests()

        asyncio.run(run_test())
    else:
        # Run server
        import uvicorn

        print("\n🚀 Starting FastAPI server...")
        print("   URL: http://localhost:8000")
        print("   Docs: http://localhost:8000/docs")
        print("\n   To test concurrent requests:")
        print("   In another terminal, run:")
        print("   python async_fastapi_example.py test\n")

        uvicorn.run(app, host="0.0.0.0", port=8000)
