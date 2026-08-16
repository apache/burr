# Async Interceptors with Burr + Ray

## Overview

This guide explains how to use **async interceptors** with Burr to enable non-blocking execution in async applications like FastAPI, async web servers, or concurrent task processors.

## The Problem

When you have an async application (e.g., FastAPI endpoint) that needs to execute Burr actions on Ray:

```python
@app.post("/compute")
async def compute(request: Request):
    app = create_burr_app_with_ray_interceptor()
    result = await app.astep()  # ← We need this to NOT block!
    return result
```

**Without async interceptors:**
- `ray.get()` blocks the event loop
- Only one request can execute at a time
- Poor concurrency and throughput

**With async interceptors:**
- Ray calls wrapped in `asyncio.to_thread()`
- Event loop stays responsive
- Multiple requests execute concurrently

## Implementation

### 1. Create Async Interceptor

```python
from burr.lifecycle import ActionExecutionInterceptorHookAsync
import asyncio

class AsyncActorInterceptor(ActionExecutionInterceptorHookAsync):
    """Async interceptor for non-blocking Ray execution"""

    def __init__(self, actor_pool: ActorPoolManager):
        self.actor_pool = actor_pool

    def should_intercept(self, *, action: Action, **kwargs) -> bool:
        return "actor" in action.tags

    async def intercept_run(
        self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
    ) -> dict:
        # Get actor (async, thread-safe)
        actor = await self.actor_pool.get_actor(action.name)

        # State subsetting
        state_subset = state.subset(*action.reads) if action.reads else state
        state_dict = state_subset.get_all()

        # Execute on actor (non-blocking!)
        result_ref = actor.execute_action.remote(action, state_dict, inputs)
        result, new_state_dict = await asyncio.to_thread(ray.get, result_ref)

        # Return result with state
        if hasattr(action, "single_step") and action.single_step:
            new_state = State(new_state_dict)
            result_with_state = result.copy()
            result_with_state["__INTERCEPTOR_NEW_STATE__"] = new_state
            return result_with_state

        return result
```

### 2. Key Differences from Sync Version

| Aspect | Sync Interceptor | Async Interceptor |
|--------|-----------------|-------------------|
| Base class | `ActionExecutionInterceptorHook` | `ActionExecutionInterceptorHookAsync` |
| Method signature | `def intercept_run(...)` | `async def intercept_run(...)` |
| Ray call | `ray.get(result_ref)` | `await asyncio.to_thread(ray.get, result_ref)` |
| Actor pool access | Direct: `self.actor_pool.get_actor()` | Async: `await self.actor_pool.get_actor()` |
| Usage | `app.step()` | `await app.astep()` |

### 3. How It Works

The framework automatically detects async interceptors:

```python
# In application.py _astep() method:

# Check if there's an async interceptor
has_async_interceptor = False
if self._adapter_set:
    interceptor = self._adapter_set.get_first_matching_hook(
        "intercept_action_execution",
        lambda hook: hook.should_intercept(action=next_action)
    )
    if interceptor and inspect.iscoroutinefunction(interceptor.intercept_run):
        has_async_interceptor = True  # ← Detected!

# If async interceptor exists, use async execution path
if not next_action.is_async() and not has_async_interceptor:
    # Only delegate to sync if BOTH action and interceptor are sync
    return self._step(inputs=inputs, _run_hooks=False)
else:
    # Use async path (awaits the interceptor)
    result, new_state = await _arun_single_step_action(...)
```

**Key insight:** Even if the action itself is synchronous, if there's an async interceptor, the framework uses the async execution path to properly await the interceptor.

## Examples

### Example 1: Standalone Async Test

See [`async_standalone_test.py`](async_standalone_test.py) for a simple example that runs 10 concurrent "sessions" sharing 2 Ray actors.

```bash
python async_standalone_test.py
```

**Output:**
```
✅ All sessions completed in 1.97s

user_0: count=2, processed_by=actor_0, time=1115ms
user_1: count=22, processed_by=actor_1, time=1115ms
...

Actor Pool Statistics:
Total requests processed: 10
  Actor 0: 5 requests
  Actor 1: 5 requests

✅ 10 sessions shared 2 actors (5x multiplexing)
✅ Async execution - no blocking on Ray calls
```

### Example 2: FastAPI Production App

See [`async_fastapi_example.py`](async_fastapi_example.py) for a complete FastAPI example with:
- Async endpoints
- Actor pool shared across requests
- Non-blocking Ray execution
- Proper async/await patterns

```bash
# Terminal 1: Start server
python async_fastapi_example.py

# Terminal 2: Test concurrent requests
python async_fastapi_example.py test
```

## Performance Comparison

### Sequential Execution (Blocking)
```python
# Sync interceptor with ray.get() - BLOCKS event loop
for i in range(10):
    result = ray.get(actor.execute.remote())  # ← Blocks here
    # Total time: 10 * 200ms = 2000ms
```

### Concurrent Execution (Non-blocking)
```python
# Async interceptor with asyncio.to_thread()
tasks = [
    process_session(i)  # Each uses: await asyncio.to_thread(ray.get, ...)
    for i in range(10)
]
results = await asyncio.gather(*tasks)  # ← All run concurrently
# Total time: ~2000ms / num_actors = ~1000ms with 2 actors
```

**Speedup:** ~2x with 2 actors, scales linearly with actor count

## Common Patterns

### 1. Async-Safe Actor Pool

```python
class ActorPoolManager:
    def __init__(self, num_actors: int):
        self.actors = [HeavyComputeActor.remote(i) for i in range(num_actors)]
        self.next_actor_idx = 0
        self.lock = asyncio.Lock()  # ← Thread-safe for async

    async def get_actor(self, action_name: str):
        async with self.lock:  # ← Protect round-robin counter
            actor = self.actors[self.next_actor_idx]
            self.next_actor_idx = (self.next_actor_idx + 1) % len(self.actors)
            return actor
```

### 2. Non-blocking Ray Calls

```python
# ❌ Wrong - blocks event loop
result = ray.get(actor.execute.remote(action, state, inputs))

# ✅ Right - non-blocking
result = await asyncio.to_thread(ray.get, actor.execute.remote(action, state, inputs))
```

### 3. FastAPI Lifespan Management

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize actor pool on startup, cleanup on shutdown"""
    global actor_pool, interceptor

    # Startup
    ray.init(ignore_reinit_error=True)
    actor_pool = ActorPoolManager(num_actors=3)
    interceptor = AsyncActorInterceptor(actor_pool)

    yield

    # Shutdown
    actor_pool.shutdown()
    ray.shutdown()

app = FastAPI(lifespan=lifespan)
```

## Testing

Tests are included in `tests/core/test_action_interceptor.py`:

```bash
pytest tests/core/test_action_interceptor.py::test_async_interceptor_with_sync_action -v
pytest tests/core/test_action_interceptor.py::test_async_interceptor_with_async_action -v
```

Both tests verify:
- ✅ Async interceptors are detected and awaited
- ✅ Works with sync actions (common case)
- ✅ Works with async actions
- ✅ Multiple concurrent requests handled correctly

## Troubleshooting

### Issue: "TypeError: object dict can't be used in 'await' expression"

**Cause:** Trying to await `ray.get()` directly
```python
result = await ray.get(...)  # ❌ ray.get() is not awaitable
```

**Fix:** Use `asyncio.to_thread()`
```python
result = await asyncio.to_thread(ray.get, ...)  # ✅
```

### Issue: "RuntimeError: This event loop is already running"

**Cause:** Calling `asyncio.run()` inside an async function
```python
async def my_function():
    asyncio.run(some_coroutine())  # ❌ Already in event loop
```

**Fix:** Just await directly
```python
async def my_function():
    await some_coroutine()  # ✅
```

### Issue: Interceptor not being awaited

**Symptom:** `RuntimeWarning: coroutine 'intercept_run' was never awaited`

**Cause:** Using sync base class instead of async
```python
class MyInterceptor(ActionExecutionInterceptorHook):  # ❌ Wrong base
    async def intercept_run(...): ...
```

**Fix:** Use async base class
```python
class MyInterceptor(ActionExecutionInterceptorHookAsync):  # ✅
    async def intercept_run(...): ...
```

## Best Practices

1. **Always use `ActionExecutionInterceptorHookAsync`** for async interceptors
2. **Always use `await asyncio.to_thread(ray.get, ...)`** for Ray calls
3. **Use `asyncio.Lock()`** for thread-safe actor pool access
4. **Test with concurrent requests** to verify non-blocking behavior
5. **Monitor actor pool stats** to ensure load balancing
6. **Use FastAPI lifespan** for actor pool initialization/cleanup

## Production Checklist

Before deploying async interceptors to production:

- [ ] Actor pool properly sized (see [ARCHITECTURE.md](ARCHITECTURE.md))
- [ ] All Ray calls wrapped in `asyncio.to_thread()`
- [ ] Actor pool access protected with `asyncio.Lock()`
- [ ] Health checks implemented (see FastAPI example)
- [ ] Concurrent request testing completed
- [ ] Monitoring/logging added for actor metrics
- [ ] Error handling and retries implemented
- [ ] Graceful shutdown tested

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - Comparison of execution patterns
- [MULTIPLEXING_EXPLAINED.md](MULTIPLEXING_EXPLAINED.md) - Visual flow diagrams
- [SUMMARY.md](SUMMARY.md) - Production guide
- [async_fastapi_example.py](async_fastapi_example.py) - Full FastAPI example
- [async_standalone_test.py](async_standalone_test.py) - Simple async example

## Summary

Async interceptors enable:
- ✅ **Non-blocking execution** in async applications
- ✅ **Concurrent request handling** (multiple requests share actor pool)
- ✅ **Better throughput** (no event loop blocking)
- ✅ **Production-ready** patterns for FastAPI and async web servers
- ✅ **Automatic detection** by the framework (no manual configuration)

The framework automatically detects async interceptors and routes execution through the async path, even when actions themselves are synchronous. This makes it seamless to add async Ray execution to existing Burr applications.
