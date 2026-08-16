# Actor-Based Architecture for Burr on Ray

This document explores different architectures for scaling Burr applications using Ray, from simple function-based execution to advanced actor-based multiplexing.

## Table of Contents

1. [Architecture Comparison](#architecture-comparison)
2. [Option 1: Function-Based (Current)](#option-1-function-based-current)
3. [Option 2: Stateless Actor Pool](#option-2-stateless-actor-pool)
4. [Option 3: Stateful Actors](#option-3-stateful-actors)
5. [When to Use Each Approach](#when-to-use-each-approach)
6. [Implementation Requirements](#implementation-requirements)

## Architecture Comparison

| Feature | Function-Based | Stateless Actor Pool | Stateful Actors |
|---------|---------------|---------------------|-----------------|
| **Resource Reuse** | ❌ New process each time | ✅ Actors persist | ✅ Actors persist |
| **State Management** | Application manages | Application manages | Actor can cache |
| **Complexity** | Low | Medium | High |
| **Initialization Cost** | Every request | Once per actor | Once per actor |
| **Multi-App Support** | N/A | ✅ Natural | ⚠️ Requires coordination |
| **State Isolation** | ✅ Automatic | ✅ Automatic | ⚠️ Must implement |
| **Use Case** | Simple offloading | Resource pooling | Complex stateful systems |

## Option 1: Function-Based (Current)

**Architecture:**
```python
@ray.remote
def execute_action(...):
    # Fresh process for each request
    model = load_model()  # ❌ Expensive!
    result = model.predict(...)
    return result
```

**Pros:**
- ✅ Simplest implementation
- ✅ Perfect state isolation (no shared state)
- ✅ No lifecycle management needed
- ✅ Works with existing Application class

**Cons:**
- ❌ Expensive initialization on every request
- ❌ No resource reuse
- ❌ Higher latency (model loading, connection setup, etc.)
- ❌ Poor resource utilization

**When to Use:**
- Actions are lightweight (< 100ms)
- No expensive initialization
- Prototyping/development
- State-heavy operations where isolation is critical

**Example Use Cases:**
- Simple data transformations
- Stateless API calls
- Quick computations

## Option 2: Stateless Actor Pool

**Architecture:**
```python
@ray.remote
class ModelActor:
    def __init__(self):
        self.model = load_model()  # ✅ Load once

    def execute(self, state: State, inputs: dict) -> dict:
        # State passed in, not stored
        result = self.model.predict(state["data"])
        return result

# Pool of actors shared across applications
actor_pool = [ModelActor.remote() for _ in range(N)]
```

**Pros:**
- ✅ Resources loaded once per actor
- ✅ Multiple applications share actors
- ✅ State isolation maintained (state passed with each request)
- ✅ Minimal changes to Application class
- ✅ Better resource utilization
- ✅ Lower latency (no initialization)

**Cons:**
- ⚠️ Need actor lifecycle management
- ⚠️ Must handle actor failures/restarts
- ⚠️ State serialization overhead on each call

**When to Use:**
- **Expensive initialization** (ML models, database connections)
- **Multiple concurrent applications** (multi-tenant systems)
- **Resource-constrained environments** (limited GPUs/memory)
- **High-throughput requirements**

**Example Use Cases:**
- ML inference with loaded models
- Database query executors with connection pools
- API gateways with persistent connections
- GPU-accelerated operations

**Implementation (Working Example):**
See `actor_based_execution.py` for complete implementation.

Key components:
1. `HeavyComputeActor` - holds expensive resources
2. `ActorPoolManager` - manages actor lifecycle and routing
3. `ActorBasedInterceptor` - routes actions to actor pool

## Option 3: Stateful Actors

**Architecture:**
```python
@ray.remote
class StatefulApplicationActor:
    def __init__(self):
        self.model = load_model()
        self.state_cache = {}  # (app_id, partition_key) -> State

    def execute(self, app_id: str, partition_key: str,
                action_name: str, inputs: dict) -> dict:
        # Retrieve or initialize state
        key = (app_id, partition_key)
        state = self.state_cache.get(key, self._init_state(key))

        # Execute action
        result = self.model.predict(state["data"])

        # Update cached state
        state = self._update_state(state, result)
        self.state_cache[key] = state

        return result
```

**Pros:**
- ✅ Minimal state serialization (cached in actor)
- ✅ Can maintain conversation/session state
- ✅ Enables complex optimizations (batching, caching)
- ✅ Potential for cross-request optimizations

**Cons:**
- ❌ High complexity
- ❌ State synchronization challenges
- ❌ Must handle state consistency across actor failures
- ❌ Requires modified Application class or wrapper
- ❌ Memory management (cache eviction, limits)
- ❌ State isolation must be manually implemented

**When to Use:**
- **Long-running conversations** with persistent context
- **Batch processing** where state accumulates
- **Complex state machines** with frequent state access
- **Performance-critical** paths where serialization is bottleneck

**Example Use Cases:**
- Chatbots with conversation history
- Recommendation engines with user profile caching
- Stream processing with windowed aggregations
- Real-time feature stores

**Would Require:**

### Modified Application Class

```python
class ActorBackedApplication(Application):
    """Application that delegates execution to Ray Actors"""

    def __init__(self, actor_handle, **kwargs):
        self.actor = actor_handle
        super().__init__(**kwargs)

    def _step(self, inputs, _run_hooks=True):
        # Delegate to actor instead of local execution
        result = ray.get(self.actor.execute_step.remote(
            app_id=self._uid,
            partition_key=self._partition_key,
            inputs=inputs
        ))
        # Update local state snapshot
        self._state = State(result["state"])
        return result["action"], result["result"], self._state
```

### Actor-Side Application Runner

```python
@ray.remote
class ApplicationExecutorActor:
    """Actor that runs Burr applications with state caching"""

    def __init__(self, application_builder):
        self.builder = application_builder
        self.applications = {}  # (app_id, partition_key) -> Application
        self.expensive_resource = load_model()

    def execute_step(self, app_id: str, partition_key: str, inputs: dict):
        # Get or create application instance
        key = (app_id, partition_key)
        if key not in self.applications:
            self.applications[key] = self.builder.build()

        app = self.applications[key]
        action, result, state = app.step(inputs)

        return {
            "action": action.name,
            "result": result,
            "state": state.get_all()
        }
```

## When to Use Each Approach

### Decision Tree

```
Does action have expensive initialization (>1s)?
├─ NO → Use Function-Based (Option 1)
└─ YES → Need resource reuse
    │
    ├─ Do you have multiple concurrent users/sessions?
    │  ├─ NO → Use Function-Based (Option 1)
    │  └─ YES → Go to next question
    │
    ├─ Is state simple and can be serialized efficiently?
    │  ├─ YES → Use Stateless Actor Pool (Option 2) ✅ RECOMMENDED
    │  └─ NO → Go to next question
    │
    └─ Do you need cross-request optimizations or complex state?
       ├─ YES → Consider Stateful Actors (Option 3)
       │        But only if you can handle the complexity!
       └─ NO → Use Stateless Actor Pool (Option 2)
```

### Specific Scenarios

**Use Function-Based When:**
- ✅ Development/prototyping
- ✅ Lightweight actions (<100ms)
- ✅ No initialization cost
- ✅ Simple debugging is priority
- ✅ Low request volume

**Use Stateless Actor Pool When:**
- ✅ ML model inference (models loaded in actors)
- ✅ Database operations (connection pools)
- ✅ Multi-tenant SaaS applications
- ✅ GPU workloads (limited GPU resources)
- ✅ API rate limiting (actors manage quotas)
- ✅ **Most production use cases** ⭐

**Use Stateful Actors When:**
- ✅ Real-time chat/conversation systems
- ✅ Online learning models (state evolves with requests)
- ✅ Complex session management
- ✅ Stream processing with windows
- ⚠️ Only if you have expertise in distributed state management

## Implementation Requirements

### For Option 2 (Stateless Actor Pool)

**Required Changes:**
1. ✅ **No Application class changes needed!**
2. ✅ Create Actor class with resource initialization
3. ✅ Create ActorPoolManager for lifecycle
4. ✅ Modify interceptor to use actor pool
5. ✅ Handle actor failures/restarts

**Example:** See `actor_based_execution.py`

### For Option 3 (Stateful Actors)

**Required Changes:**
1. ❌ **Significant Application class changes**
2. Create Actor-backed Application variant
3. Implement state caching and eviction
4. Handle state consistency
5. Implement state recovery on failures
6. Add state synchronization mechanisms
7. Monitor memory usage

**Not Recommended:** Unless you have specific requirements that justify the complexity.

## Performance Comparison

### Latency Breakdown (Example: ML Inference)

**Function-Based (Option 1):**
```
Total Latency: ~2100ms
├─ Ray overhead:        100ms
├─ Model loading:      2000ms ❌
└─ Inference:            10ms
```

**Stateless Actor Pool (Option 2):**
```
Total Latency: ~110ms
├─ Ray overhead:        100ms
├─ Model loading:         0ms ✅ (loaded once)
└─ Inference:            10ms

First request: ~2100ms (actor initialization)
Subsequent:    ~110ms (19x faster!)
```

**Stateful Actors (Option 3):**
```
Total Latency: ~50ms
├─ Ray overhead:         40ms
├─ State retrieval:       0ms ✅ (cached)
├─ Model loading:         0ms ✅ (loaded once)
└─ Inference:            10ms

But: Added complexity in state management
```

### Throughput Comparison (Requests/Second)

**Scenario:** 10 concurrent applications, ML inference action

| Approach | RPS | Resource Usage | Notes |
|----------|-----|----------------|-------|
| Function-Based | ~5 | High (load model each time) | Unscalable |
| Actor Pool (2 actors) | ~180 | Low (2 models loaded) | ✅ Recommended |
| Actor Pool (10 actors) | ~900 | Medium (10 models loaded) | Best throughput |
| Stateful (2 actors) | ~200 | Low + state memory | Complex |

## Best Practices

### For Stateless Actor Pool (Option 2)

1. **Actor Pool Sizing:**
   ```python
   # Rule of thumb
   num_actors = min(
       num_available_gpus,  # If GPU-bound
       concurrent_users // 5,  # If CPU-bound
       max_memory // model_memory  # If memory-bound
   )
   ```

2. **Routing Strategy:**
   ```python
   # Round-robin (simple)
   actor = actors[request_id % len(actors)]

   # Load-based (better)
   actor = min(actors, key=lambda a: a.get_queue_size())

   # Locality-aware (best for stateful patterns)
   actor_id = hash(app_id) % len(actors)
   actor = actors[actor_id]
   ```

3. **Error Handling:**
   ```python
   def execute_with_retry(actor, action, state, inputs, max_retries=3):
       for attempt in range(max_retries):
           try:
               return ray.get(actor.execute.remote(action, state, inputs))
           except ray.exceptions.RayActorError:
               if attempt < max_retries - 1:
                   actor = recreate_actor()  # Recreate failed actor
               else:
                   raise
   ```

4. **Monitoring:**
   ```python
   # Track actor health
   @ray.remote
   class MonitoredActor:
       def get_metrics(self):
           return {
               "requests_processed": self.request_count,
               "avg_latency": self.avg_latency,
               "memory_usage": self.get_memory_usage(),
               "last_request": time.time() - self.last_request_time
           }
   ```

## Migration Path

**Phase 1:** Start with function-based (Option 1)
- Get basic interceptor working
- Validate functionality
- Measure baseline performance

**Phase 2:** Move to stateless actor pool (Option 2)
- Identify expensive initialization
- Create actor pool for those actions
- Measure improvement
- **Stop here for most cases!** ✅

**Phase 3:** (Optional) Consider stateful actors (Option 3)
- Only if profiling shows state serialization bottleneck
- Only if you have stateful use case (chat, streaming)
- Build incrementally with careful testing

## Conclusion

**For most production use cases, Option 2 (Stateless Actor Pool) is the sweet spot:**
- ✅ Significant performance improvement
- ✅ Reasonable complexity
- ✅ No Application class changes needed
- ✅ Battle-tested pattern (used by many Ray applications)

**Option 3 (Stateful Actors) should only be considered if:**
- You have measured evidence of state serialization bottleneck
- You have experience with distributed state management
- Your use case genuinely requires cross-request state

The provided `actor_based_execution.py` demonstrates Option 2 and shows how to share actors across multiple Burr applications efficiently.
