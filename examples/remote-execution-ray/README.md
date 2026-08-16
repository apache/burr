# Remote Execution with Ray

This example demonstrates how to use Burr's **Action Execution Interceptors** to run specific actions on Ray workers while keeping orchestration on the main process.

## Overview

Burr's lifecycle hook system includes **interceptors** that can wrap action execution and redirect it to different execution backends like Ray, Temporal, or custom distributed systems.

This example shows:
- ✅ Selective interception (only actions tagged with `ray` run remotely)
- ✅ Orchestrator hooks (run on main process)
- ✅ Worker hooks (run on Ray workers)
- ✅ Seamless mixing of local and remote execution
- ✅ State management across distributed execution

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Main Process (Orchestrator)                                 │
│                                                               │
│  ┌──────────────────────────────────────────────┐            │
│  │  Burr Application                             │            │
│  │                                               │            │
│  │  PreRunStepHook (Orchestrator) ────┐         │            │
│  │                                     ↓         │            │
│  │  RayActionInterceptor               │         │            │
│  │    - should_intercept()             │         │            │
│  │    - intercept_run() ───────────────┼─────────┼─────┐     │
│  │                                     │         │      │     │
│  │  PostRunStepHook (Orchestrator) ←──┘         │      │     │
│  └──────────────────────────────────────────────┘      │     │
└────────────────────────────────────────────────────────┼─────┘
                                                          │
                                         Ray Remote Call  │
                                                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Ray Worker                                                  │
│                                                              │
│  PreRunStepHookWorker  ────┐                                │
│                            ↓                                │
│  Action.run_and_update()  (actual execution)                │
│                            │                                │
│  PostRunStepHookWorker ←───┘                                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Key Concepts

### 1. Two-Tier Hook System

**Orchestrator Hooks** (run on main process):
- `PreRunStepHook` - runs before any action (local or remote)
- `PostRunStepHook` - runs after any action completes
- These hooks see all actions but don't know about execution details

**Worker Hooks** (run on Ray workers):
- `PreRunStepHookWorker` - runs on the worker before execution
- `PostRunStepHookWorker` - runs on the worker after execution
- Only called for intercepted actions
- Must be serializable (picklable)

### 2. Action Execution Interceptor

The interceptor has two methods:

```python
def should_intercept(self, *, action: Action, **kwargs) -> bool:
    """Decide if this action should be intercepted"""
    return "ray" in action.tags

def intercept_run(self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs) -> dict:
    """Execute the action on Ray and return the result"""
    # Get worker hooks to pass to Ray worker
    worker_adapter_set = kwargs.get("worker_adapter_set")

    # Execute on Ray with worker hooks
    @ray.remote
    def execute_on_ray():
        # Call worker hooks
        # Execute action
        # Return result

    return ray.get(execute_on_ray.remote())
```

### 3. Selective Execution

Actions are tagged to control where they run:

```python
@action(reads=["count"], writes=["count"], tags=["local"])
def local_task(state: State):
    # Runs on main process
    ...

@action(reads=["count"], writes=["count"], tags=["ray"])
def remote_task(state: State):
    # Runs on Ray worker
    ...
```

## Installation

```bash
pip install -r requirements.txt
```

## Examples

This directory contains several examples demonstrating different patterns:

### 1. Basic Function-Based Execution (`application.py`)

Simple example showing how to selectively run actions on Ray workers.

```bash
python application.py
```

### 2. Actor-Based Multiplexing (`actor_based_execution.py`)

Advanced example showing multiple Burr applications sharing a pool of Ray Actors. Actors hold expensive resources (ML models, connections) and multiplex between requests.

```bash
python actor_based_execution.py
```

Key features:
- ✅ **Resource reuse**: Expensive resources loaded once per actor
- ✅ **Multiplexing**: 10 applications sharing 2 actors
- ✅ **State isolation**: Each application maintains independent state
- ✅ **Load balancing**: Requests distributed across actor pool

See [ARCHITECTURE.md](ARCHITECTURE.md) and [MULTIPLEXING_EXPLAINED.md](MULTIPLEXING_EXPLAINED.md) for detailed explanations.

### 3. Async FastAPI Example (`async_fastapi_example.py`)

Production-ready example showing async FastAPI endpoints with non-blocking Ray actor execution.

```bash
# Terminal 1: Start server
python async_fastapi_example.py

# Terminal 2: Test concurrent requests
python async_fastapi_example.py test
```

Key features:
- ✅ **Non-blocking async**: No blocking on Ray calls
- ✅ **Concurrent requests**: Multiple FastAPI requests share actor pool
- ✅ **Production-ready**: Proper async/await patterns

### 4. Async Standalone Test (`async_standalone_test.py`)

Simpler async example without FastAPI dependency.

```bash
python async_standalone_test.py
```

### 5. Application on Ray Worker (`app_on_ray_worker.py`)

Advanced example showing an entire Burr application running on a Ray worker, with actions distributed to specialized Ray actors based on tags.

```bash
python app_on_ray_worker.py
```

Key features:
- ✅ **Entire app on Ray worker**: Main process submits applications to Ray workers
- ✅ **Nested distribution**: Ray worker → specialized Ray actors (for tagged actions)
- ✅ **Local execution**: Non-tagged actions run locally on the Ray worker
- ✅ **Specialized actors**: Different actor pools for different action types (GPU, DB, etc.)
- ✅ **Resource efficiency**: Applications share actor pools on the same worker

Architecture:
```
Main Process
  │
  ├─→ Ray Worker 1 (runs Burr app)
  │     ├─→ Local Action (runs on worker)
  │     ├─→ GPU Action → GPU Actor Pool
  │     └─→ DB Action → DB Actor Pool
  │
  └─→ Ray Worker 2 (runs Burr app)
        ├─→ Local Action (runs on worker)
        └─→ GPU Action → GPU Actor Pool (shared)
```

This pattern is useful when:
- You want to offload entire applications to Ray cluster
- You need different resource types (GPU, DB, etc.) for different actions
- You want to scale applications horizontally across Ray workers
- You want to keep lightweight actions local to avoid actor overhead

### 6. Application on Ray Worker with PostgreSQL Persistence (`app_on_ray_worker_with_persistence.py`)

Enhanced version of the above example with state checkpointing to PostgreSQL. State is automatically saved after each step, enabling resume from failures and state inspection.

```bash
# Without persistence (default)
python app_on_ray_worker_with_persistence.py

# With PostgreSQL persistence
export USE_PERSISTENCE=true
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=postgres
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=postgres
python app_on_ray_worker_with_persistence.py
```

Key features:
- ✅ **All features from example 5** (Ray worker execution, actor distribution)
- ✅ **PostgreSQL checkpointing**: State automatically saved after each step
- ✅ **Resume capability**: Can resume from saved state using `initialize_from()`
- ✅ **Connection management**: Proper connection handling in Ray environment
- ✅ **Environment-based config**: Configure via environment variables

**Setting up PostgreSQL:**

```bash
# Using Docker
docker run --name local-psql \
  -v local_psql_data:/var/lib/postgresql/data \
  -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres \
  -d postgres

# Install Burr with PostgreSQL support
pip install "burr[postgresql]"
```

**Resuming from saved state:**

```python
# In the remote function, set resume=True
future = run_burr_application_on_worker.remote(
    ...,
    resume=True,  # Will attempt to load from PostgreSQL
)
```

See [PERSISTENCE_WITH_RAY.md](PERSISTENCE_WITH_RAY.md) for detailed documentation.

## Running the Examples

### Basic Function-Based Example

```bash
python application.py
```

Expected output:
```
================================================================================
Burr + Ray Remote Execution Example
================================================================================

[Main Process] Initializing Ray...

================================================================================
Step 1: Local execution (increment_local)
================================================================================
[Main Process] About to execute action: increment_local
[Main Process] Finished executing action: increment_local
Result: count=1, operation=increment_local

================================================================================
Step 2: Ray execution (heavy_computation)
================================================================================
[Main Process] About to execute action: heavy_computation
[Main Process] Dispatching heavy_computation to Ray...
[Ray Worker] Starting action: heavy_computation on Ray worker
[Ray Worker] Running heavy computation with multiplier=3
[Ray Worker] Completed action: heavy_computation on Ray worker
[Main Process] Received result from Ray for heavy_computation
[Main Process] Finished executing action: heavy_computation
Result: count=3, operation=heavy_computation(x3)

...
```

### Jupyter Notebook

```bash
jupyter notebook notebook.ipynb
```

## Use Cases

This pattern is useful for:

1. **Compute-Intensive Operations**: Offload heavy computations to Ray clusters
2. **GPU Workloads**: Run ML inference/training on GPU workers
3. **Scalability**: Distribute work across multiple machines
4. **Resource Isolation**: Keep heavy operations away from orchestrator
5. **Hybrid Workflows**: Mix local control flow with distributed execution

## Extending to Other Backends

The same pattern works for other execution backends:

### Temporal

```python
class TemporalActionInterceptor(ActionExecutionInterceptorHook):
    def should_intercept(self, *, action, **kwargs):
        return "temporal" in action.tags

    def intercept_run(self, *, action, state, inputs, **kwargs):
        # Execute as Temporal activity
        return await workflow.execute_activity(
            action.run_and_update,
            state,
            **inputs
        )
```

### Custom Distributed System

```python
class CustomBackendInterceptor(ActionExecutionInterceptorHook):
    def should_intercept(self, *, action, **kwargs):
        return "distributed" in action.tags

    def intercept_run(self, *, action, state, inputs, **kwargs):
        # Submit to your custom backend
        job_id = backend.submit_job(action, state, inputs)
        result = backend.wait_for_completion(job_id)
        return result
```

## Important Notes

1. **State Serialization**: State must be serializable to pass to workers
2. **Worker Hooks**: Must be picklable (avoid closures with local variables)
3. **Error Handling**: Exceptions on workers propagate back to orchestrator
4. **Performance**: Ray overhead ~100ms per task; use for tasks >1s
5. **Async Interceptors**: For async FastAPI/web apps, use `ActionExecutionInterceptorHookAsync` with `async def intercept_run()`. The framework automatically detects and awaits async interceptors even when actions are synchronous.

## State Serialization

When interceptors send state to remote workers, they must use `state.serialize()` instead of `state.get_all()`. This ensures proper handling of non-serializable objects (like database clients) through Burr's serde layer.

### Using Serialization in Interceptors

**In the interceptor** (when sending state to workers):
```python
def intercept_run(self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs) -> dict:
    # Use serialize() to properly handle non-serializable objects
    state_subset = state.subset(*action.reads) if action.reads else state
    state_dict = state_subset.serialize()  # ✅ Uses serde layer

    # Send to worker...
    result, new_state_dict = ray.get(actor.execute_action.remote(state_dict, ...))

    # Deserialize when reconstructing state
    new_state = State.deserialize(new_state_dict)  # ✅ Uses deserialization
    return result
```

**On the worker/actor** (when receiving state):
```python
def execute_action(self, action, state_dict: dict, inputs: dict) -> tuple:
    # Deserialize state on worker side
    state = State.deserialize(state_dict)  # ✅ Uses deserialization

    # Execute action...
    result, new_state = action.run_and_update(state, **inputs)

    # Serialize before returning
    return result, new_state.serialize()  # ✅ Uses serde layer
```

### Handling Non-Serializable Objects (DB Clients, etc.)

If your state contains non-serializable objects (like database clients), register field-level serde:

```python
from burr.core.state import register_field_serde
from typing import Any

def serialize_db_client(value: Any, **kwargs) -> dict:
    """Serialize DB client to connection config"""
    return {
        "connection_string": value.connection_string,
        "type": "db_client"
    }

def deserialize_db_client(value: dict, **kwargs) -> Any:
    """Recreate DB client from connection config"""
    # Recreate connection on worker side
    return create_db_client(value["connection_string"])

# Register the serde for the field
register_field_serde("db_client", serialize_db_client, deserialize_db_client)
```

Now when state is serialized/deserialized, the DB client will be:
- **Serialized**: Converted to connection string/config dict
- **Deserialized**: Recreated on the worker side from the config

This pattern works for any non-serializable object that needs special handling:
- Database connections
- File handles
- Network connections
- Custom objects with complex state

**Why use `serialize()` instead of `get_all()`?**
- `get_all()` returns raw state values (may contain non-serializable objects)
- `serialize()` uses the serde layer to convert non-serializable objects to serializable dicts
- This aligns interceptors with the persistence layer (which also uses `serialize()`)

## Async Interceptors

For non-blocking execution in async applications (FastAPI, async web servers):

```python
from burr.lifecycle import ActionExecutionInterceptorHookAsync

class AsyncActorInterceptor(ActionExecutionInterceptorHookAsync):
    """Async interceptor for non-blocking Ray calls"""

    def should_intercept(self, *, action: Action, **kwargs) -> bool:
        return "actor" in action.tags

    async def intercept_run(
        self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
    ) -> dict:
        # Get actor from pool (async, thread-safe)
        actor = await self.actor_pool.get_actor(action.name)

        # Execute on actor (non-blocking)
        result_ref = actor.execute_action.remote(action, state, inputs)
        result = await asyncio.to_thread(ray.get, result_ref)

        return result
```

Key points:
- Use `ActionExecutionInterceptorHookAsync` base class
- Make `intercept_run()` an async method
- Use `await asyncio.to_thread(ray.get, ...)` to avoid blocking event loop
- Works seamlessly with `await app.astep()` in async contexts
- The framework automatically detects async interceptors and uses async execution path

## Related Documentation

- [Burr Lifecycle Hooks](https://burr.dagworks.io/concepts/hooks/)
- [Ray Core API](https://docs.ray.io/en/latest/ray-core/walkthrough.html)
- [Temporal Workflows](https://docs.temporal.io/)
