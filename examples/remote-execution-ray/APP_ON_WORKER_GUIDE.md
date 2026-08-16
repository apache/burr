# Running Burr Applications on Ray Workers

This guide explains the pattern of running entire Burr applications on Ray workers, with actions distributed to specialized Ray actors based on tags.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Main Process (Orchestrator)                                │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Submit applications to Ray workers                │     │
│  │  run_burr_application_on_worker.remote(...)        │     │
│  └────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ Ray Remote Function
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Ray Worker (Application Execution)                         │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Burr Application                                   │     │
│  │  - State management                                 │     │
│  │  - Workflow orchestration                           │     │
│  │  - Interceptor routing                              │     │
│  └────────────────────────────────────────────────────┘     │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  WorkerLevelInterceptor                             │     │
│  │  - Routes tagged actions to actors                  │     │
│  │  - Executes local actions on worker                 │     │
│  └────────────────────────────────────────────────────┘     │
│                                                              │
│  Local Actions (tags=["local"])                             │
│  └─→ Execute directly on Ray worker                         │
│                                                              │
│  Tagged Actions (tags=["gpu", "db"])                        │
│  ├─→ GPU Actions → GPU Actor Pool                           │
│  └─→ DB Actions → DB Actor Pool                             │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ Ray Actor Calls
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Specialized Ray Actors                                      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ GPU Actor 0  │  │ GPU Actor 1  │  │ DB Actor 0   │     │
│  │              │  │              │  │              │     │
│  │ - GPU Model  │  │ - GPU Model  │  │ - DB Conn    │     │
│  │ - CUDA       │  │ - CUDA       │  │ - Pool       │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                              │
│  Actions execute here with specialized resources            │
└─────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Ray Remote Function

The `run_burr_application_on_worker` function is decorated with `@ray.remote`, making it execute on a Ray worker:

```python
@ray.remote
def run_burr_application_on_worker(
    initial_state: dict,
    actor_pool_stats: dict,
    app_config: dict,
) -> dict:
    # Creates and runs Burr application on Ray worker
    ...
```

### 2. Worker-Level Interceptor

The `WorkerLevelInterceptor` runs on the Ray worker and routes actions:

- **Tagged actions** (`gpu`, `db`, `specialized`) → Route to specialized actors
- **Local actions** (no matching tags) → Execute directly on worker

```python
class WorkerLevelInterceptor(ActionExecutionInterceptorHook):
    def should_intercept(self, *, action: Action, **kwargs) -> bool:
        return any(tag in action.tags for tag in ["gpu", "db", "specialized"])

    def intercept_run(self, *, action: Action, state: State, ...):
        # Route to actor or execute locally
        ...
```

### 3. Specialized Actor Pools

Different actor pools for different resource types:

```python
actor_pool = SpecializedActorPool()
gpu_actor = actor_pool.get_actor("gpu")  # Round-robin selection
db_actor = actor_pool.get_actor("db")
```

## Execution Flow

1. **Main Process**: Submits application to Ray worker
   ```python
   future = run_burr_application_on_worker.remote(initial_state, ...)
   ```

2. **Ray Worker**: Creates application with interceptor
   ```python
   app = ApplicationBuilder()...
       .with_hooks(interceptor)
       .build()
   ```

3. **Action Execution**:
   - **Local action** (`tags=["local"]`): Executes directly on worker
   - **Tagged action** (`tags=["gpu"]`): Interceptor routes to GPU actor

4. **Actor Execution**: Action runs on specialized actor with resources

5. **State Management**: State serialized/deserialized at boundaries

## When to Use This Pattern

✅ **Use when:**
- You want to offload entire applications to Ray cluster
- You need different resource types (GPU, DB, etc.) for different actions
- You want to scale applications horizontally across Ray workers
- You want to keep lightweight actions local (avoid actor overhead)
- You have multiple applications that can share actor pools

❌ **Don't use when:**
- All actions need the same resources (use simple actor pool)
- Actions are very lightweight (overhead not worth it)
- You need tight coupling with main process state

## Benefits

1. **Horizontal Scaling**: Run multiple applications in parallel on different workers
2. **Resource Specialization**: Different actors for different resource needs
3. **Efficiency**: Local actions avoid actor overhead
4. **Resource Sharing**: Multiple applications share actor pools on same worker
5. **State Isolation**: Each application maintains independent state

## State Serialization

State is properly serialized/deserialized at boundaries:

- **Worker → Actor**: `state.serialize()` before sending
- **Actor → Worker**: `State.deserialize()` after receiving

This ensures non-serializable objects (DB clients, etc.) are handled via the serde layer.

## Example Usage

```python
# Submit multiple applications to Ray workers
futures = []
for i in range(10):
    future = run_burr_application_on_worker.remote(
        initial_state={"count": i * 10},
        actor_pool_stats={},
        app_config={"app_id": f"app_{i}"}
    )
    futures.append(future)

# Wait for all to complete
results = ray.get(futures)
```

## Comparison with Other Patterns

| Pattern | Application Location | Action Distribution | Use Case |
|---------|---------------------|-------------------|----------|
| **Basic Interceptor** | Main process | Main → Ray actors | Single app, selective offloading |
| **Actor Multiplexing** | Main process | Main → Shared actor pool | Multiple apps, resource reuse |
| **App on Worker** (this) | Ray worker | Worker → Specialized actors | Scale apps, resource specialization |

## Next Steps

- See `app_on_ray_worker.py` for complete working example
- Customize actor pools for your resource types
- Add persistence/tracking hooks as needed
- Consider async version for non-blocking execution
