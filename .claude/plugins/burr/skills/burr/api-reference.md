<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
-->

# Apache Burr API Reference

This is a quick reference for the most commonly used Apache Burr APIs. For complete documentation, see https://burr.apache.org/

## Core Imports

```python
from burr.core import action, State, ApplicationBuilder, default, when, expr
from burr.core.action import Action
from burr.core.application import Application
from burr.core import graph
```

## Actions

### @action Decorator

The `@action` decorator converts a function into a Burr action.

```python
@action(reads=["key1", "key2"], writes=["result"])
def my_action(state: State, param: str) -> State:
    """Action that reads from state and returns updated state."""
    value = state["key1"] + state["key2"]
    return state.update(result=value + param)
```

**Parameters:**
- `reads`: List of state keys this action reads from
- `writes`: List of state keys this action writes to

**Action Function Signature:**
- First parameter: `state: State`
- Additional parameters: Runtime inputs (passed via `inputs` in `app.run()`)
- Return: Updated `State` object

### Streaming Actions

Actions can stream intermediate results using generators:

```python
@action(reads=["input"], writes=["output"])
def streaming_action(state: State) -> Generator[State, None, Tuple[dict, State]]:
    """Action that yields intermediate states."""
    for i in range(10):
        # Yield intermediate states
        yield state.update(progress=i)

    # Return final result and state
    result = {"output": "done"}
    return result, state.update(**result)
```

### Async Actions

Actions can be async:

```python
@action(reads=["url"], writes=["data"])
async def fetch_data(state: State) -> State:
    """Async action for I/O-bound operations."""
    async with httpx.AsyncClient() as client:
        response = await client.get(state["url"])
        data = response.json()
    return state.update(data=data)
```

### Action Methods

Actions can be bound with default parameters:

```python
# Define a reusable action
@action(reads=["prompt"], writes=["response"])
def llm_call(state: State, system_prompt: str, model: str) -> State:
    response = call_llm(state["prompt"], system_prompt, model)
    return state.update(response=response)

# Bind with different parameters
answer_action = llm_call.bind(
    system_prompt="Answer questions",
    model="gpt-4"
)
summarize_action = llm_call.bind(
    system_prompt="Summarize text",
    model="gpt-3.5-turbo"
)
```

## State

The `State` object is an immutable container for application state.

### Creating State

```python
from burr.core import State

state = State({"counter": 0, "messages": []})
```

### Accessing State

```python
# Dictionary-style access
value = state["key"]

# Get with default
value = state.get("key", default_value)

# Check if key exists
if "key" in state:
    pass
```

### Updating State

State is **immutable**. All methods return NEW State objects:

```python
# Update single or multiple keys
new_state = state.update(counter=5, name="Alice")

# Append to a list (creates list if doesn't exist)
new_state = state.append(messages={"role": "user", "content": "hello"})

# Increment numbers
new_state = state.increment(counter=1)

# Extend lists with multiple items
new_state = state.extend(tags=["tag1", "tag2", "tag3"])

# Wipe state (keep only specified keys)
new_state = state.wipe(keep=["counter"])

# Chain operations (each returns State)
new_state = state.update(prompt=prompt).append(history=item).increment(count=1)

# Update with dictionary
new_state = state.update(**{"key": "value"})
```

### Using State in Actions

Actions return `Tuple[dict, State]`:

```python
from typing import Tuple

@action(reads=["input"], writes=["output"])
def my_action(state: State) -> Tuple[dict, State]:
    # 1. Read from state
    input_value = state["input"]

    # 2. Process
    output_value = process(input_value)

    # 3. Return (result_dict, new_state)
    return {"output": output_value}, state.update(output=output_value)
```

The result dict is exposed to callers and tracking systems. The new state flows to the next action.

**Shorthand (also valid):**
```python
@action(reads=["counter"], writes=["counter"])
def increment(state: State) -> State:
    result = {"counter": state["counter"] + 1}
    return state.update(**result)  # Framework infers result
```

### State Methods

- `.update(**kwargs) -> State`: Set/update one or more keys
- `.append(**kwargs) -> State`: Append to list values (creates list if needed)
- `.extend(**kwargs) -> State`: Extend lists with multiple items
- `.increment(**kwargs) -> State`: Increment integer values
- `.wipe(keep: List[str] = None, delete: List[str] = None) -> State`: Remove keys
- `.merge(other: State) -> State`: Merge two states (other wins on conflicts)
- `.subset(*keys: str) -> State`: Return new State with only specified keys
- `.get(key, default=None) -> Any`: Get value with default
- `.get_all() -> dict`: Get all state as dictionary
- `.serialize() -> dict`: Serialize state to JSON-compatible dict
- `.subset(*keys) -> State`: Create new state with only specified keys

## ApplicationBuilder

Fluent API for building Burr applications.

### Basic Pattern

```python
app = (
    ApplicationBuilder()
    .with_actions(
        action1=my_action,
        action2=another_action
    )
    .with_transitions(
        ("action1", "action2", default),
        ("action2", "action1", when(should_loop=True))
    )
    .with_state(initial_key="value")
    .with_entrypoint("action1")
    .build()
)
```

### ApplicationBuilder Methods

**Core building blocks:**

- `.with_actions(**actions: Action)` - Register actions
- `.with_transitions(*transitions: Tuple)` - Define state machine transitions
- `.with_state(**state: Any)` - Set initial state
- `.with_entrypoint(action: str)` - Set starting action
- `.build() -> Application` - Construct the application

**Observability & Tracking:**

- `.with_tracker(tracker_type: str, project: str, **params)` - Enable tracking
  - `tracker_type="local"` - Local filesystem tracking (launches UI)
  - `project` - Project name in the UI
  - `params={"storage_dir": "~/.burr"}` - Storage location

**Identity & Persistence:**

- `.with_identifiers(app_id: str, partition_key: str)` - Set app identifiers
- `.with_state_persister(persister: StatePersister)` - Enable state persistence
- `.initialize_from(persister, resume_at_next_action=True, default_state={}, default_entrypoint=None)` - Load from persister

**Lifecycle & Hooks:**

- `.with_hooks(*hooks: LifecycleAdapter)` - Add lifecycle hooks
- `.with_typing(typing_system: TypingSystem)` - Add type validation

**Graph-based construction:**

- `.with_graph(graph: Graph)` - Use pre-built graph instead of actions+transitions

### Using Pre-built Graphs

```python
from burr.core import graph

g = (
    graph.GraphBuilder()
    .with_actions(action1, action2, action3)
    .with_transitions(
        ("action1", "action2"),
        ("action2", "action3")
    )
    .build()
)

app = (
    ApplicationBuilder()
    .with_graph(g)
    .with_state(key="value")
    .with_entrypoint("action1")
    .build()
)
```

## Transitions

Transitions define how the state machine moves between actions.

### Basic Transition

```python
("source_action", "target_action")
```

### Conditional Transitions

**Using `default`** - Matches if no other condition matches:
```python
from burr.core import default

("action1", "action2", default)
```

**Using `when()`** - Match based on state values:
```python
from burr.core import when

("check_age", "adult_path", when(age__gte=18))
("check_age", "child_path", when(age__lt=18))
```

**Condition operators:**
- `key=value` - Exact match
- `key__eq=value` - Explicit equality
- `key__ne=value` - Not equal
- `key__lt=value` - Less than
- `key__lte=value` - Less than or equal
- `key__gt=value` - Greater than
- `key__gte=value` - Greater than or equal
- `key__in=[values]` - In list
- `key__notin=[values]` - Not in list
- `key__contains=value` - Collection/string contains value
- `key__is=value` - Identity check (`is`), useful for `None`
- `key__isnot=value` - Negated identity (`is not`)

**Using `expr()`** - Arbitrary Python expressions:
```python
from burr.core import expr

("counter", "counter", expr("counter < 10"))
("counter", "done", default)
```

### Multi-source/target Transitions

Transition from multiple sources to multiple targets:

```python
# Multiple sources to one target
(["action1", "action2"], "action3")

# One source to multiple targets (conditional branching - only one executes)
("start", ["parallel1", "parallel2"])

# For actual parallelism, use MapActions/MapStates/MapActionsAndStates
```

## Application

The built application instance provides methods to execute and inspect the state machine.

### Running Applications

**Basic execution:**
```python
action, result, state = app.run(halt_after=["action_name"])
```

**With inputs:**
```python
action, result, state = app.run(
    halt_after=["action_name"],
    inputs={"param1": "value1"}
)
```

**Async execution:**
```python
action, result, state = await app.arun(halt_after=["action_name"])
```

**Iterate through execution:**
```python
for action, result, state in app.iterate(halt_after=["end_action"]):
    print(f"Executed {action.name}, result: {result}")
```

**Stream results:**
```python
for state in app.stream_result(halt_after=["end_action"]):
    print(f"Current state: {state}")
```

### Application Properties

- `app.state` - Current state
- `app.graph` - State machine graph
- `app.uid` - Unique application identifier

### Visualization

```python
# Generate state machine diagram
app.visualize(
    output_file_path="statemachine.png",
    include_conditions=True,
    view=True,  # Auto-open the file
    format="png"  # or "pdf", "svg"
)
```

## Parallelism

Apache Burr provides high-level APIs for parallel execution of actions or subgraphs.

### MapStates

Apply the same action to multiple state variations.

```python
from burr.core.parallelism import MapStates
from burr.core import action, State, ApplicationContext
from typing import Dict, Any

@action(reads=["prompt"], writes=["result"])
def query_llm(state: State) -> State:
    result = call_llm(state["prompt"])
    return state.update(result=result)

class TestMultiplePrompts(MapStates):
    def action(self, state: State, inputs: Dict[str, Any]):
        return query_llm.with_name("query_llm")

    def states(self, state: State, context: ApplicationContext, inputs: Dict[str, Any]):
        for prompt in state["prompts"]:
            yield state.update(prompt=prompt)

    def reduce(self, state: State, states):
        results = [s["result"] for s in states]
        return state.update(all_results=results)

    @property
    def reads(self) -> list[str]:
        return ["prompts"]

    @property
    def writes(self) -> list[str]:
        return ["all_results"]
```

### MapActions

Apply different actions to the same state.

```python
from burr.core.parallelism import MapActions

class TestMultipleLLMs(MapActions):
    def actions(self, state: State, context: ApplicationContext, inputs: Dict[str, Any]):
        yield query_gpt4.with_name("gpt4")
        yield query_claude.with_name("claude")
        yield query_o1.with_name("o1")

    def state(self, state: State, inputs: Dict[str, Any]) -> State:
        return state  # Pass same state to all actions

    def reduce(self, state: State, states):
        results = [s["result"] for s in states]
        return state.update(all_results=results)

    @property
    def reads(self) -> list[str]:
        return ["prompt"]

    @property
    def writes(self) -> list[str]:
        return ["all_results"]
```

### MapActionsAndStates

Run all combinations of actions and states (cartesian product).

```python
from burr.core.parallelism import MapActionsAndStates

class TestModelsAndPrompts(MapActionsAndStates):
    def actions(self, state: State, context: ApplicationContext, inputs: Dict[str, Any]):
        for model in ["gpt-4", "claude", "o1"]:
            yield query_llm.bind(model=model).with_name(f"query_{model}")

    def states(self, state: State, context: ApplicationContext, inputs: Dict[str, Any]):
        for prompt in state["prompts"]:
            yield state.update(prompt=prompt)

    def reduce(self, state: State, states):
        results = []
        for s in states:
            results.append({"model": s["model"], "prompt": s["prompt"], "result": s["result"]})
        return state.update(all_results=results)

    @property
    def reads(self) -> list[str]:
        return ["prompts"]

    @property
    def writes(self) -> list[str]:
        return ["all_results"]
```

### RunnableGraph

Wrap a graph for use as a subgraph in parallel execution.

```python
from burr.core.parallelism import RunnableGraph
from burr.core.graph import GraphBuilder

graph = (
    GraphBuilder()
    .with_actions(action1, action2, action3)
    .with_transitions(
        ("action1", "action2"),
        ("action2", "action3")
    )
    .build()
)

runnable = RunnableGraph(
    graph=graph,
    entrypoint="action1",
    halt_after=["action3"]
)

# Use in MapStates or MapActions
class RunSubgraphs(MapStates):
    def action(self, state: State, inputs: Dict[str, Any]):
        return runnable  # Return the RunnableGraph

    def states(self, state: State, context: ApplicationContext, inputs: Dict[str, Any]):
        for item in state["items"]:
            yield state.update(current_item=item)

    def reduce(self, state: State, states):
        results = [s["final_result"] for s in states]
        return state.update(all_results=results)

    @property
    def reads(self) -> list[str]:
        return ["items"]

    @property
    def writes(self) -> list[str]:
        return ["all_results"]
```

### Executors

Control how parallel tasks are executed.

```python
from concurrent.futures import ThreadPoolExecutor

# Use multithreading (default)
app = (
    ApplicationBuilder()
    .with_parallel_executor(ThreadPoolExecutor(max_workers=10))
    .with_actions(parallel_action=MyParallelAction())
    .build()
)

# For Ray-based distributed execution
from burr.integrations.ray import RayExecutor
import ray

ray.init()
app = (
    ApplicationBuilder()
    .with_parallel_executor(RayExecutor())
    .with_actions(parallel_action=MyParallelAction())
    .build()
)
```

## Persistence

### Built-in Persisters

**SQLite Persister:**
```python
from burr.core.persistence import SQLitePersister

persister = SQLitePersister(
    db_path="app.db",
    table_name="burr_state",
    connect_kwargs={"check_same_thread": False}
)
persister.initialize()
```

**Using with ApplicationBuilder:**
```python
app = (
    ApplicationBuilder()
    .with_actions(...)
    .with_transitions(...)
    .with_identifiers(app_id="my-app", partition_key="user-123")
    .with_state_persister(persister)
    .initialize_from(
        persister,
        resume_at_next_action=True,
        default_state={"counter": 0},
        default_entrypoint="start"
    )
    .build()
)
```

### Custom Persisters

Implement `BaseStatePersister` interface:

```python
from burr.core.persistence import BaseStatePersister

class CustomPersister(BaseStatePersister):
    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        """List all app IDs for a partition."""
        pass

    def load(self, partition_key: str, app_id: str, **kwargs) -> dict:
        """Load persisted state."""
        pass

    def save(self, partition_key: str, app_id: str,
             state: State, **kwargs) -> dict:
        """Save state."""
        pass
```

## Tracking & Telemetry

### Local Tracking

```python
from burr.tracking import LocalTrackingClient

tracker = LocalTrackingClient(
    project="my_project",
    storage_dir="~/.burr"
)

app = (
    ApplicationBuilder()
    .with_actions(...)
    .with_tracker(tracker)
    .build()
)
```

**Launch UI:**
```bash
burr
```

### Tracking Integrations

- **Langsmith**: `from burr.integrations.langsmith import LangsmithTracker`
- **Weights & Biases**: `from burr.integrations.wandb import WandbTracker`
- **OpenTelemetry**: Built-in support for OTEL tracing

## Hooks

Hooks provide lifecycle callbacks for observability and integration.

### Available Hooks

```python
from burr.lifecycle import LifecycleAdapter

class PrePostActionHookAsync(LifecycleAdapter):
    async def pre_run_step(self, action: Action, **kwargs):
        """Called before each action."""
        pass

    async def post_run_step(self, action: Action, result: dict, state: State, **kwargs):
        """Called after each action."""
        pass
```

### Common Hook Use Cases

- Logging and monitoring
- Performance tracking
- External system integration
- State validation
- Debugging and inspection

## Common Helper Functions

### Result Action

Special action that returns a result and halts:

```python
from burr.core import Result

app = (
    ApplicationBuilder()
    .with_actions(
        compute=my_action,
        result=Result("output_key")
    )
    .with_transitions(
        ("compute", "result")
    )
    .build()
)
```

### Input Action

Special action that captures runtime inputs:

```python
from burr.core.action import Input

app = (
    ApplicationBuilder()
    .with_actions(
        get_input=Input("user_prompt"),
        process=my_action
    )
    .with_transitions(
        ("get_input", "process")
    )
    .build()
)

app.run(halt_after=["process"], inputs={"user_prompt": "Hello"})
```

## Type Safety with Pydantic

### Pydantic Typed State

Use Pydantic models for type-safe state with IDE support, autocomplete, and validation.

**Define state model:**
```python
from pydantic import BaseModel, Field
from typing import Optional

class ApplicationState(BaseModel):
    prompt: Optional[str] = Field(default=None, description="User prompt")
    response: Optional[str] = Field(default=None, description="AI response")
    count: int = Field(default=0, description="Request count")
```

**Configure application:**
```python
from burr.integrations.pydantic import PydanticTypingSystem

app = (
    ApplicationBuilder()
    .with_typing(PydanticTypingSystem(ApplicationState))
    .with_state(ApplicationState())
    .build()
)
```

**Use in actions:**
```python
@action.pydantic(reads=["prompt"], writes=["response"])
def process(state: ApplicationState, llm_client) -> ApplicationState:
    # Access state as attributes (not brackets)
    user_prompt = state.prompt

    # Process
    response = llm_client.generate(user_prompt)

    # Mutate in-place and return (mutation on internal copy)
    state.response = response
    return state
```

**Access typed state after run:**
```python
action, result, state = app.run(halt_after=["process"])

# Use .data property to access Pydantic model
print(state.data.response)  # IDE autocomplete works!
print(state.data.count)
```

### Key Differences: Regular vs Pydantic State

| Feature | Regular State | Pydantic Typed State |
|---------|---------------|---------------------|
| **Definition** | `State({"key": value})` | Pydantic `BaseModel` |
| **Access** | `state["key"]` | `state.key` |
| **Updates** | `state.update()`, `state.append()` | In-place mutation |
| **Return Type** | `Tuple[dict, State]` | `ApplicationState` |
| **Decorator** | `@action(...)` | `@action.pydantic(...)` |
| **Type Safety** | Runtime only | Compile-time + Runtime |
| **IDE Support** | No autocomplete | Full autocomplete |
| **Validation** | Manual | Automatic via Pydantic |

## Testing

Actions are pure functions that are easy to test:

```python
def test_my_action():
    state = State({"counter": 0})
    new_state = my_action(state, param="test")
    assert new_state["counter"] == 1
    assert new_state["result"] == "test"
```

Test state machines by running them:

```python
def test_application():
    app = build_my_app()
    action, result, state = app.run(halt_after=["end"])
    assert state["final_value"] == expected_value
```

## Best Practices

1. **Keep actions focused** - Single responsibility per action
2. **Declare reads/writes accurately** - Helps with debugging and optimization
3. **Use type hints** - Improves IDE support and catches bugs
4. **Enable tracking** - Always use `.with_tracker()` during development
5. **Test actions independently** - Actions are pure functions
6. **Use persistence for long-running workflows** - Enable state resumption
7. **Leverage hooks** - Add observability without changing core logic
8. **Visualize your state machine** - Use `.visualize()` to understand flow

## Quick Links

- Apache Burr Documentation: https://burr.apache.org/
- GitHub: https://github.com/apache/burr
- Examples: `examples/` directory in the Apache Burr repository
- Discord: https://discord.gg/6Zy2DwP4f3
