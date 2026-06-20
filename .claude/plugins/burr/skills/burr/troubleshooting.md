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

# Apache Burr Troubleshooting Guide

Common issues and solutions when working with Apache Burr.

## Installation Issues

### Issue: `burr` command not found after installation

**Problem:**
```bash
$ burr
command not found: burr
```

**Solutions:**

1. Install with UI dependencies:
```bash
pip install "burr[start]"
```

2. Check if burr is in your PATH:
```bash
which burr
# or
python -m burr
```

3. If using poetry:
```bash
poetry add "burr[start]"
poetry run burr
```

### Issue: UI won't start or shows errors

**Problem:**
```
Error starting Burr UI: Module not found
```

**Solutions:**

1. Ensure you installed the `[start]` extra:
```bash
pip install "burr[start]"
```

2. Check port is not already in use:
```bash
# Default is port 7241
lsof -i :7241
```

3. Specify custom port:
```bash
burr --port 8000
```

4. Check storage directory permissions:
```bash
ls -la ~/.burr
```

## State Machine Issues

### Issue: Infinite loops in transitions

**Problem:**
```python
# State machine never halts
app.run(halt_after=["end"])  # Never reaches "end"
```

**Common Causes:**

1. **Missing halt condition:**
```python
# ❌ Bad - loops forever
.with_transitions(
    ("process", "process", default)  # Always loops!
)

# ✅ Good - has exit condition
.with_transitions(
    ("process", "process", expr("counter < 10")),
    ("process", "end", default)
)
```

2. **Condition never becomes true:**
```python
# ❌ Bad - condition may never be met
.with_transitions(
    ("wait", "wait", when(status="pending")),
    ("wait", "done", when(status="complete"))
    # What if status is "error"? Stuck forever!
)

# ✅ Good - always has fallback
.with_transitions(
    ("wait", "wait", when(status="pending")),
    ("wait", "done", when(status="complete")),
    ("wait", "error_handler", default)
)
```

**Debugging:**
1. Use `.visualize()` to see the graph:
```python
app.visualize(output_file_path="debug.png", include_conditions=True)
```

2. Add logging in actions:
```python
@action(reads=["counter"], writes=["counter"])
def process(state: State) -> State:
    print(f"Counter: {state['counter']}")  # Debug output
    return state.update(counter=state["counter"] + 1)
```

3. Use the Burr UI to watch execution in real-time:
```bash
burr
```

### Issue: Wrong action executes

**Problem:**
```
Expected action 'process_data' but 'error_handler' executed instead
```

**Common Causes:**

1. **Transition condition order matters:**
```python
# ❌ Bad - default matches first
.with_transitions(
    ("check", "error", default),  # This always matches!
    ("check", "success", when(valid=True))
)

# ✅ Good - specific conditions first
.with_transitions(
    ("check", "success", when(valid=True)),
    ("check", "error", default)
)
```

2. **State value is not what you expect:**
```python
# Debug: Check actual state values
@action(reads=["value"], writes=["result"])
def check_value(state: State) -> State:
    print(f"Value is: {state['value']}, type: {type(state['value'])}")
    # Maybe it's a string "True" not boolean True?
    return state.update(result=state["value"])
```

3. **Using `when()` with complex objects:**
```python
# ❌ Bad - object comparison may not work as expected
.with_transitions(
    ("check", "next", when(user={"id": 123}))  # Dict comparison
)

# ✅ Good - use simpler state values
.with_transitions(
    ("check", "next", when(user_id=123))  # Direct value comparison
)
```

## State Issues

### Issue: State not updating

**Problem:**
```python
# State remains unchanged after action
state_before = app.state["counter"]  # 0
app.run(halt_after=["increment"])
state_after = app.state["counter"]   # Still 0!
```

**Common Causes:**

1. **Not returning updated state:**
```python
# ❌ Bad - returns None
@action(reads=["counter"], writes=["counter"])
def increment(state: State) -> State:
    state.update(counter=state["counter"] + 1)
    # Missing return!

# ✅ Good - returns updated state
@action(reads=["counter"], writes=["counter"])
def increment(state: State) -> State:
    result = {"counter": state["counter"] + 1}
    return state.update(**result)
```

**Note:** You can return just `State` (shorthand) or `Tuple[dict, State]` (explicit):
```python
from typing import Tuple

# Explicit pattern (recommended for clarity)
@action(reads=["counter"], writes=["counter"])
def increment(state: State) -> Tuple[dict, State]:
    result = {"counter": state["counter"] + 1}
    return result, state.update(counter=result["counter"])
```

2. **Mutating state directly:**
```python
# ❌ Bad - mutates state (doesn't work)
@action(reads=["items"], writes=["items"])
def add_item(state: State, item: str) -> State:
    state["items"].append(item)  # This doesn't work!
    return state

# ✅ Good - uses .append() method
@action(reads=["items"], writes=["items"])
def add_item(state: State, item: str) -> State:
    return state.append(items=item)
```

3. **Typo in state key:**
```python
# ❌ Bad - creates new key instead of updating existing
@action(reads=["counter"], writes=["counter"])
def increment(state: State) -> State:
    return state.update(couter=state["counter"] + 1)  # Typo!

# ✅ Good - correct key name
@action(reads=["counter"], writes=["counter"])
def increment(state: State) -> State:
    return state.update(counter=state["counter"] + 1)
```

### Issue: KeyError accessing state

**Problem:**
```python
KeyError: 'missing_key'
```

**Solutions:**

1. **Use `.get()` with default:**
```python
# ❌ Risky - may not exist
value = state["key"]

# ✅ Safe - provides default
value = state.get("key", default_value)
```

2. **Check if key exists:**
```python
if "key" in state:
    value = state["key"]
else:
    value = default
```

3. **Initialize state properly:**
```python
app = (
    ApplicationBuilder()
    .with_state(
        counter=0,  # Initialize all keys
        items=[],
        status="pending"
    )
    .build()
)
```

4. **Check reads declaration:**
```python
# ❌ Bad - tries to read undeclared key
@action(reads=[], writes=["result"])
def process(state: State) -> State:
    value = state["input"]  # Not in reads!
    return state.update(result=value)

# ✅ Good - declares what it reads
@action(reads=["input"], writes=["result"])
def process(state: State) -> State:
    value = state["input"]
    return state.update(result=value)
```

## Action Issues

### Issue: Action inputs not working

**Problem:**
```python
app.run(halt_after=["process"], inputs={"param": "value"})
# Error: unexpected keyword argument 'param'
```

**Solution:**

Add parameter to action function:
```python
# ❌ Bad - no parameter for input
@action(reads=[], writes=["result"])
def process(state: State) -> State:
    # How do I access the input?
    pass

# ✅ Good - accepts input parameter
@action(reads=[], writes=["result"])
def process(state: State, param: str) -> State:
    return state.update(result=param)
```

### Issue: Streaming action not working

**Problem:**
```python
# No intermediate results appear
for state in app.stream_result(halt_after=["end"]):
    print(state)  # Only prints final state
```

**Solution:**

Use generator pattern with yields:
```python
# ❌ Bad - regular action (no streaming)
@action(reads=["input"], writes=["output"])
def process(state: State) -> State:
    result = slow_operation()
    return state.update(output=result)

# ✅ Good - streaming action
@action(reads=["input"], writes=["output"])
def process(state: State) -> Generator[State, None, Tuple[dict, State]]:
    for chunk in slow_operation():
        # Yield intermediate states
        yield state.update(current_chunk=chunk)

    # Return final result
    result = {"output": "done"}
    return result, state.update(**result)
```

### Issue: Async action errors

**Problem:**
```
RuntimeError: Event loop is closed
```

**Solutions:**

1. **Use `arun()` for async applications:**
```python
# ❌ Bad - using sync run with async actions
app.run(halt_after=["async_action"])

# ✅ Good - using async run
await app.arun(halt_after=["async_action"])
```

2. **Make sure action is marked async:**
```python
# ✅ Async action
@action(reads=["url"], writes=["data"])
async def fetch_data(state: State) -> State:
    async with httpx.AsyncClient() as client:
        response = await client.get(state["url"])
    return state.update(data=response.json())
```

3. **Mix sync and async carefully:**
```python
# You can have both sync and async actions in the same app
# Burr handles this automatically
app = (
    ApplicationBuilder()
    .with_actions(
        sync_action,    # Regular action
        async_action    # Async action
    )
    .build()
)

# Use arun() if any action is async
await app.arun(halt_after=["async_action"])
```

## Persistence Issues

### Issue: State not persisting

**Problem:**
```python
# State is lost between runs
app = build_app()
app.run(halt_after=["step1"])
# Restart app
app = build_app()  # Starts from beginning, not step1
```

**Solution:**

Set up persistence properly:
```python
from burr.core.persistence import SQLitePersister

persister = SQLitePersister("app.db", "state")
persister.initialize()  # Don't forget to initialize!

app = (
    ApplicationBuilder()
    .with_actions(...)
    .with_identifiers(
        app_id="my-workflow",       # Required for persistence
        partition_key="user-123"     # Required for persistence
    )
    .with_state_persister(persister)
    .initialize_from(
        persister,
        resume_at_next_action=True,
        default_state={"step": 0},
        default_entrypoint="start"
    )
    .build()
)
```

### Issue: Multiple app instances conflict

**Problem:**
```python
# Both apps save to same location and conflict
app1 = build_app()
app2 = build_app()
```

**Solution:**

Use unique identifiers:
```python
app1 = (
    ApplicationBuilder()
    .with_identifiers(
        app_id="workflow-1",
        partition_key="user-alice"
    )
    .build()
)

app2 = (
    ApplicationBuilder()
    .with_identifiers(
        app_id="workflow-2",
        partition_key="user-bob"
    )
    .build()
)
```

## Tracking / UI Issues

### Issue: Application not appearing in UI

**Problem:**
```
Burr UI is running but my application doesn't show up
```

**Solutions:**

1. **Make sure tracking is enabled:**
```python
app = (
    ApplicationBuilder()
    .with_tracker("local", project="my_project")
    .build()
)
```

2. **Check storage directory:**
```python
# Specify storage directory
app = (
    ApplicationBuilder()
    .with_tracker(
        "local",
        project="my_project",
        params={"storage_dir": "~/.burr"}
    )
    .build()
)

# Then launch UI with same directory
# burr --storage-dir ~/.burr
```

3. **Run the application:**
```python
# Tracking data is only created when app runs
app.run(halt_after=["some_action"])
```

4. **Check UI is pointing to correct directory:**
```bash
burr --storage-dir ~/.burr
```

### Issue: Visualization not generating

**Problem:**
```python
app.visualize(output_file_path="graph.png")
# No file created, or error about graphviz
```

**Solutions:**

1. **Install graphviz:**
```bash
# macOS
brew install graphviz

# Ubuntu
sudo apt-get install graphviz

# Then install Python package
pip install graphviz
```

2. **Check file path:**
```python
# Use absolute path
app.visualize(
    output_file_path="/full/path/to/graph.png",
    format="png"
)
```

3. **Try different formats:**
```python
# Try PDF if PNG doesn't work
app.visualize(
    output_file_path="graph.pdf",
    format="pdf"
)
```

## Performance Issues

### Issue: Application runs slowly

**Problem:**
```
Application takes too long to execute
```

**Solutions:**

1. **Use parallel execution:**
```python
# Run independent actions in parallel using MapActions
from burr.core.parallelism import MapActions
from burr.core import ApplicationContext
from typing import Dict, Any

class ParallelActions(MapActions):
    def actions(self, state: State, context: ApplicationContext, inputs: Dict[str, Any]):
        yield action1.with_name("action1")
        yield action2.with_name("action2")

    def state(self, state: State, inputs: Dict[str, Any]) -> State:
        return state

    def reduce(self, state: State, states) -> State:
        results = [s for s in states]
        return state.update(parallel_results=results)

    @property
    def reads(self) -> list[str]:
        return []

    @property
    def writes(self) -> list[str]:
        return ["parallel_results"]

app = ApplicationBuilder().with_actions(
    parallel=ParallelActions(),
    action3=action3
).with_transitions(
    ("parallel", "action3")
).build()
```

2. **Profile actions:**
```python
import time

@action(reads=["input"], writes=["output"])
def slow_action(state: State) -> State:
    start = time.time()
    result = expensive_operation(state["input"])
    print(f"Action took {time.time() - start:.2f}s")
    return state.update(output=result)
```

3. **Check for unnecessary state copies:**
```python
# ❌ Slow - repeated state updates
new_state = state
for item in items:
    new_state = new_state.update(item=process(item))

# ✅ Faster - batch update
processed_items = [process(item) for item in items]
new_state = state.update(items=processed_items)
```

4. **Use async for I/O-bound operations:**
```python
# ❌ Slow - sequential I/O
def fetch_all(state: State) -> State:
    data1 = requests.get(url1).json()
    data2 = requests.get(url2).json()
    return state.update(data1=data1, data2=data2)

# ✅ Fast - parallel async I/O
async def fetch_all(state: State) -> State:
    async with httpx.AsyncClient() as client:
        data1, data2 = await asyncio.gather(
            client.get(url1),
            client.get(url2)
        )
    return state.update(data1=data1.json(), data2=data2.json())
```

## Testing Issues

### Issue: Tests fail with tracking enabled

**Problem:**
```python
# Tests create tracking data and clutter filesystem
```

**Solution:**

Disable tracking in tests:
```python
def build_app(enable_tracking: bool = True):
    builder = ApplicationBuilder().with_actions(...)

    if enable_tracking:
        builder = builder.with_tracker("local", project="my_app")

    return builder.build()

# In tests
def test_my_app():
    app = build_app(enable_tracking=False)
    # Test without creating tracking data
```

Or use temporary directory:
```python
import tempfile

def test_with_tracking():
    with tempfile.TemporaryDirectory() as tmpdir:
        app = (
            ApplicationBuilder()
            .with_tracker(
                "local",
                project="test",
                params={"storage_dir": tmpdir}
            )
            .build()
        )
        # Test runs, tracking data cleaned up automatically
```

## Type Checking Issues

### Issue: Type errors with State

**Problem:**
```python
# Type checker complains about state access
def my_function(state: State):
    value: int = state["key"]  # Type checker error
```

**Solution:**

State values are typed as `Any` by default. Use runtime checks or type assertions:
```python
def my_function(state: State):
    value = state["key"]
    assert isinstance(value, int)
    # Now type checker knows it's int
```

Or use Pydantic integration for type safety:
```python
from burr.core import action
from pydantic import BaseModel

class MyState(BaseModel):
    key: int

@action.pydantic(reads=["key"], writes=["result"])
def my_action(state: State, inputs: MyState) -> dict:
    # inputs.key is typed as int
    return {"result": inputs.key + 1}
```

## Getting Help

If you're still stuck:

1. **Check the documentation:** https://burr.apache.org/
2. **Search GitHub issues:** https://github.com/apache/burr/issues
3. **Ask on Discord:** https://discord.gg/6Zy2DwP4f3
4. **Enable debug logging:**
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

When asking for help, include:
- Apache Burr version: `pip show burr`
- Python version: `python --version`
- Minimal code example that reproduces the issue
- Full error message and traceback
- State machine visualization if relevant: `app.visualize()`
