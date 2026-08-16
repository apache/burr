# How Actor Multiplexing Works with Burr Interceptors

## The Mental Model

Think of actors like **shared GPUs**:
- Each Burr Application has its own state (like each training job has its own model weights)
- Actors provide compute resources (like a GPU provides CUDA cores)
- State flows: Application → Actor → Application (round trip each request)

## Visual Flow Diagram

```
TIME: T0 (Initialization)
=======================
Main Process:
  App 1 (state={count: 0})  ──┐
  App 2 (state={count: 10}) ──┼──→ Interceptor Pool
  App 3 (state={count: 20}) ──┘         │
                                         │
                                         ↓
                               ┌─────────────────┐
                               │ Actor 0         │
                               │ - model loaded  │
                               │ - ready         │
                               └─────────────────┘
                               ┌─────────────────┐
                               │ Actor 1         │
                               │ - model loaded  │
                               │ - ready         │
                               └─────────────────┘


TIME: T1 (App 1 makes request)
================================
App 1 (state={count: 0})
  │
  └─→ app.step()
        │
        ├─→ Interceptor.should_intercept(action) → True
        │
        └─→ Interceptor.intercept_run(
              action=heavy_compute,
              state={count: 0},  ← State GOES WITH REQUEST
              inputs={}
            )
              │
              └─→ actor_pool.get_actor() → Actor 0
                    │
                    └─→ Actor 0.execute_action.remote(
                          action_name="heavy_compute",
                          state_dict={count: 0},  ← Serialized state
                          inputs={}
                        )
                          │
                          ↓
                    ┌─────────────────────────────────┐
                    │ Actor 0 (Ray Worker Process)    │
                    │                                 │
                    │ 1. Receive state_dict           │
                    │    state_dict = {count: 0}      │
                    │                                 │
                    │ 2. Reconstruct State object     │
                    │    state = State.deserialize(   │
                    │              state_dict)        │
                    │                                 │
                    │ 3. Run action with resources    │
                    │    result = {                   │
                    │      count: 0 * 2 = 0,         │
                    │      ...                        │
                    │    }                            │
                    │    new_state = state.update()   │
                    │                                 │
                    │ 4. Return result + new state    │
                    │    return (result, new_state)   │
                    │                                 │
                    │ 5. Actor FORGETS everything     │
                    │    (no state cached)            │
                    └─────────────────────────────────┘
                          │
                          ↓ result = {count: 0, ...}
                          ↓ new_state_dict = {count: 0, ...}
                    │
              ┌─────┘
              │
        ┌─────┘ Result returned to interceptor
        │
  ┌─────┘ Interceptor returns result to App
  │
App 1 updates its state:
  state = {count: 0, processed_by: actor_0}


TIME: T2 (App 2 makes request - CONCURRENT!)
=============================================
App 2 (state={count: 10})
  │
  └─→ app.step()
        │
        └─→ Interceptor.intercept_run(
              action=heavy_compute,
              state={count: 10},  ← DIFFERENT STATE
              inputs={}
            )
              │
              └─→ actor_pool.get_actor() → Actor 1 (round-robin)
                    │
                    └─→ Actor 1.execute_action.remote(
                          state_dict={count: 10},  ← App 2's state
                          inputs={}
                        )
                          │
                          ↓
                    ┌─────────────────────────────────┐
                    │ Actor 1 (Different Worker)      │
                    │                                 │
                    │ Receives App 2's state          │
                    │ state_dict = {count: 10}        │
                    │                                 │
                    │ Processes with same model       │
                    │ result = {count: 20, ...}       │
                    │                                 │
                    │ Returns to App 2                │
                    └─────────────────────────────────┘
                          │
                          ↓
App 2 receives result:
  state = {count: 20, processed_by: actor_1}


TIME: T3 (App 3 makes request)
================================
App 3 (state={count: 20})
  │
  └─→ Interceptor.intercept_run(
        state={count: 20},  ← Yet another different state
      )
        │
        └─→ actor_pool.get_actor() → Actor 0 (back to Actor 0!)
              │
              └─→ Actor 0.execute_action.remote(
                    state_dict={count: 20},  ← App 3's state
                  )
                    │
                    ↓
              ┌─────────────────────────────────┐
              │ Actor 0                          │
              │                                 │
              │ NOTE: Actor 0 previously         │
              │ processed App 1's request, but   │
              │ has NO MEMORY of it!             │
              │                                 │
              │ Receives App 3's state          │
              │ state_dict = {count: 20}        │
              │                                 │
              │ Processes independently         │
              │ result = {count: 40, ...}       │
              └─────────────────────────────────┘
                    │
                    ↓
App 3 receives result:
  state = {count: 40, processed_by: actor_0}
```

## Critical Points

### 1. State is NOT Stored in Actors

```python
# ❌ WRONG - What you might think happens
@ray.remote
class StatefulActor:
    def __init__(self):
        self.state = {}  # DON'T DO THIS

    def execute(self, action_name):
        # Uses self.state ← NOPE!
        ...

# ✅ CORRECT - What actually happens
@ray.remote
class StatelessActor:
    def __init__(self):
        self.model = load_model()  # Resources only!
        # NO state storage

    def execute(self, action_name, state_dict, inputs):
        # State is passed in ← YES!
        state = State.deserialize(state_dict)  # Use deserialize for serde layer
        result = self.model.predict(state["data"])
        new_state = state.update(result)
        return result, new_state.serialize()  # Use serialize for serde layer
        # State is returned ← YES!
```

### 2. Each Application Maintains Its Own State

```python
# In the main process, each app has its own state
app1 = ApplicationBuilder().with_state(count=0).build()   # state={count: 0}
app2 = ApplicationBuilder().with_state(count=10).build()  # state={count: 10}
app3 = ApplicationBuilder().with_state(count=20).build()  # state={count: 20}

# When app1.step() is called:
# 1. App1's current state (count=0) is retrieved
# 2. State is serialized and sent to actor
# 3. Actor processes it and returns new state
# 4. App1 updates its state with the result
# 5. App2 and App3's states are unchanged!
```

### 3. Interceptor is the Router

```python
class ActorBasedInterceptor:
    def __init__(self, actor_pool):
        self.actor_pool = actor_pool  # Shared pool

    def intercept_run(self, *, action, state, inputs, **kwargs):
        # 1. Pick an actor from the pool
        actor = self.actor_pool.get_actor(action.name)

        # 2. Send THIS application's state to the actor
        state_dict = state.serialize()  # Use serialize() for serde layer

        # 3. Execute remotely
        result_ref = actor.execute_action.remote(
            action.name,
            state_dict,  # ← App-specific state
            inputs
        )

        # 4. Wait for result
        result, new_state_dict = ray.get(result_ref)

        # 5. Return to THIS application
        # The Application will update its own state
        return result
```

## Concrete Example with Real Values

Let's trace 3 apps making requests:

```python
# Initial State
App1: {count: 0,  app_id: "user1"}
App2: {count: 10, app_id: "user2"}
App3: {count: 20, app_id: "user3"}

Actor0: model_loaded=True, state_cache=NONE
Actor1: model_loaded=True, state_cache=NONE

# Request 1: App1.step()
1. App1 calls step()
2. Interceptor picks Actor0
3. Sends to Actor0: {count: 0, app_id: "user1"}
4. Actor0 processes: 0 * 2 = 0
5. Actor0 returns: {count: 0, processed_by: "actor_0"}
6. App1 updates its state: {count: 0, app_id: "user1", processed_by: "actor_0"}

# Request 2: App2.step() (concurrent or after)
1. App2 calls step()
2. Interceptor picks Actor1 (round-robin)
3. Sends to Actor1: {count: 10, app_id: "user2"}  ← Different state!
4. Actor1 processes: 10 * 2 = 20
5. Actor1 returns: {count: 20, processed_by: "actor_1"}
6. App2 updates its state: {count: 20, app_id: "user2", processed_by: "actor_1"}

# Request 3: App3.step()
1. App3 calls step()
2. Interceptor picks Actor0 (back to Actor0!)
3. Sends to Actor0: {count: 20, app_id: "user3"}  ← App3's state
4. Actor0 processes: 20 * 2 = 40
   NOTE: Actor0 has NO MEMORY of App1's request!
5. Actor0 returns: {count: 40, processed_by: "actor_0"}
6. App3 updates its state: {count: 40, app_id: "user3", processed_by: "actor_0"}

# Final State
App1: {count: 0,  processed_by: "actor_0"}  ← Unchanged by App2 or App3
App2: {count: 20, processed_by: "actor_1"}  ← Unchanged by App1 or App3
App3: {count: 40, processed_by: "actor_0"}  ← Unchanged by App1 or App2

Actor0: Processed 2 requests (App1 and App3), no state cached
Actor1: Processed 1 request (App2), no state cached
```

## Why This Works Without Application Changes

The key is that the interceptor hook API was designed perfectly for this:

```python
def intercept_run(self, *, action: Action, state: State, inputs: Dict, **kwargs) -> dict:
    """
    Inputs:
    - action: The action to run
    - state: The FULL current state (from Application)  ← Key point!
    - inputs: Any additional inputs

    Returns:
    - result: Dict to be used to update state

    The Application handles:
    - Storing state before the call
    - Updating state after the call
    - State isolation between instances

    The Interceptor handles:
    - Routing to appropriate actor
    - Serializing/deserializing state
    - Managing actor pool
    """
```

## Code Reference: How Interceptor Passes State

From `actor_based_execution.py`:

```python
class ActorBasedInterceptor:
    def intercept_run(self, *, action, state, inputs, **kwargs) -> dict:
        # Get an actor from the pool
        actor = self.actor_pool.get_actor(action.name)

        # Convert Application's state to dict for serialization
        # Use serialize() to properly handle non-serializable objects via serde layer
        state_dict = state.serialize()  # ← Application's current state

        # Send to actor (with state!)
        result_ref = actor.execute_action.remote(
            action.name,
            state_dict,  # ← State travels with the request
            inputs
        )

        # Get result back
        result, new_state_dict = ray.get(result_ref)

        # Convert back to State object
        # Use deserialize() to properly handle non-serializable objects via serde layer
        new_state = State.deserialize(new_state_dict)

        # Return with special key so Application updates its state
        result_with_state = result.copy()
        result_with_state["__INTERCEPTOR_NEW_STATE__"] = new_state

        return result_with_state
        # ↑ Application receives this and updates its own state
```

## Comparison: What If Actors Were Stateful?

### Current (Stateless Actors)
```
Request Flow:
App → [state] → Actor → [state] → App
              processes

Pros:
✅ Simple: State clearly owned by Application
✅ Isolated: Apps can't interfere with each other
✅ Scalable: Actor can process any app's request
✅ Recoverable: Actor restart doesn't lose state
```

### Stateful Actors (Alternative)
```
Request Flow:
App → [app_id] → Actor → [retrieves state from cache] → processes → [stores state] → App

Pros:
✅ Less serialization overhead

Cons:
❌ Complex: State ownership unclear
❌ Risky: Apps could interfere if bugs exist
❌ Limited: Actor tied to specific app_ids
❌ Fragile: Actor restart loses cached state
❌ Memory: Must manage cache size/eviction
```

## Key Takeaway

**Actors are compute resources (like GPUs), not state stores.**

Each Application instance maintains its own state locally. When it needs to run an action:

1. Application has state (e.g., `{count: 10}`)
2. Interceptor packages: (action, state, inputs)
3. Actor receives package, processes, returns result
4. Application updates its own state
5. Actor forgets everything

This is why multiple applications can share actors naturally - the actors are stateless workers, not state managers!

## Try It Yourself

Run `actor_based_execution.py` with print statements:

```python
# Add to Actor.execute_action():
print(f"Actor {self.actor_id} received state: {state_dict}")
print(f"Actor {self.actor_id} returning result: {result}")

# Add to Application after .step():
print(f"App {i} state after step: {state.get_all()}")
```

You'll see each app maintains independent state even though they share actors!
