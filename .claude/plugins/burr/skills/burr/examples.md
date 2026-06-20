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

# Apache Burr Code Examples

Common patterns and working examples for building Apache Burr applications.

## Table of Contents
1. [Simple Counter](#simple-counter)
2. [Basic Chatbot](#basic-chatbot)
3. [Multi-Step Workflow](#multi-step-workflow)
4. [Conditional Branching](#conditional-branching)
5. [Looping with Conditions](#looping-with-conditions)
6. [Error Handling](#error-handling)
7. [Streaming Actions](#streaming-actions)
8. [Parallel Execution](#parallel-execution)
9. [State Persistence](#state-persistence)
10. [RAG Pattern](#rag-pattern)
11. [Using Action Binding](#using-action-binding)
12. [Testing Actions](#testing-actions)
13. [Pydantic Typed State](#pydantic-typed-state)

---

## Simple Counter

Minimal example showing state updates and transitions.

```python
from burr.core import action, State, ApplicationBuilder, default, expr

@action(reads=["counter"], writes=["counter"])
def increment(state: State) -> State:
    # Read from state using bracket notation
    result = {"counter": state["counter"] + 1}
    # State methods return new State objects
    return state.update(**result)

@action(reads=["counter"], writes=["result"])
def finish(state: State) -> State:
    # Access state values with state["key"]
    result = {"result": f"Final count: {state['counter']}"}
    return state.update(**result)

app = (
    ApplicationBuilder()
    .with_actions(increment, finish)
    .with_transitions(
        ("increment", "increment", expr("counter < 10")),
        ("increment", "finish", default)
    )
    .with_state(counter=0)
    .with_entrypoint("increment")
    .build()
)

# run() returns (action, result_dict, final_state)
action, result, final_state = app.run(halt_after=["finish"])
print(final_state["result"])  # "Final count: 10"
```

## Basic Chatbot

Classic chatbot pattern with user input and AI response.

```python
from burr.core import action, State, ApplicationBuilder, default
from typing import Tuple

@action(reads=[], writes=["chat_history", "prompt"])
def human_input(state: State, prompt: str) -> Tuple[dict, State]:
    """Capture user input."""
    # Build chat item
    chat_item = {"role": "user", "content": prompt}

    # Return (result_dict, new_state)
    # Chain state updates: update() returns State, then append() returns new State
    return {"prompt": prompt}, state.update(prompt=prompt).append(chat_history=chat_item)

@action(reads=["chat_history"], writes=["response", "chat_history"])
def ai_response(state: State) -> Tuple[dict, State]:
    """Generate AI response."""
    # Read from state using bracket notation
    chat_history = state["chat_history"]

    # Call your LLM
    response = call_llm(chat_history)
    chat_item = {"role": "assistant", "content": response}

    # Return result and chained state updates
    return {"response": response}, state.update(response=response).append(
        chat_history=chat_item
    )

app = (
    ApplicationBuilder()
    .with_actions(human_input, ai_response)
    .with_transitions(
        ("human_input", "ai_response"),
        ("ai_response", "human_input")
    )
    .with_state(chat_history=[])
    .with_entrypoint("human_input")
    .with_tracker("local", project="chatbot")
    .build()
)

# Run one turn of conversation
# run() returns (action, result_dict, final_state)
action, result, state = app.run(
    halt_after=["ai_response"],
    inputs={"prompt": "Hello, how are you?"}
)
print(result["response"])  # Access result from result dict
print(state["chat_history"])  # Access state using bracket notation
```

## Multi-Step Workflow

Chain multiple actions sequentially.

```python
@action(reads=["raw_text"], writes=["cleaned_text"])
def clean_text(state: State) -> State:
    """Remove special characters and normalize."""
    cleaned = state["raw_text"].lower().strip()
    return state.update(cleaned_text=cleaned)

@action(reads=["cleaned_text"], writes=["tokens"])
def tokenize(state: State) -> State:
    """Split into tokens."""
    tokens = state["cleaned_text"].split()
    return state.update(tokens=tokens)

@action(reads=["tokens"], writes=["summary"])
def summarize(state: State) -> State:
    """Generate summary."""
    summary = f"Processed {len(state['tokens'])} tokens"
    return state.update(summary=summary)

app = (
    ApplicationBuilder()
    .with_actions(clean_text, tokenize, summarize)
    .with_transitions(
        ("clean_text", "tokenize"),
        ("tokenize", "summarize")
    )
    .with_state(raw_text="  Hello World!  ")
    .with_entrypoint("clean_text")
    .build()
)

_, _, final_state = app.run(halt_after=["summarize"])
```

## Conditional Branching

Route execution based on state values.

```python
from burr.core import when

@action(reads=["user_type"], writes=["message"])
def check_user_type(state: State, user_type: str) -> State:
    return state.update(user_type=user_type)

@action(reads=[], writes=["greeting"])
def admin_greeting(state: State) -> State:
    return state.update(greeting="Welcome, Administrator!")

@action(reads=[], writes=["greeting"])
def user_greeting(state: State) -> State:
    return state.update(greeting="Welcome, User!")

@action(reads=[], writes=["greeting"])
def guest_greeting(state: State) -> State:
    return state.update(greeting="Welcome, Guest!")

app = (
    ApplicationBuilder()
    .with_actions(
        check_user_type,
        admin_greeting,
        user_greeting,
        guest_greeting
    )
    .with_transitions(
        ("check_user_type", "admin_greeting", when(user_type="admin")),
        ("check_user_type", "user_greeting", when(user_type="user")),
        ("check_user_type", "guest_greeting", default)
    )
    .with_entrypoint("check_user_type")
    .build()
)

_, _, state = app.run(
    halt_after=["admin_greeting", "user_greeting", "guest_greeting"],
    inputs={"user_type": "admin"}
)
```

## Looping with Conditions

Implement loops using recursive transitions.

```python
@action(reads=["items", "processed"], writes=["processed", "current_item"])
def process_item(state: State) -> State:
    """Process next item from list."""
    items = state["items"]
    processed_count = state.get("processed", 0)

    current_item = items[processed_count]
    # Process the item
    result = transform(current_item)

    return state.update(
        processed=processed_count + 1,
        current_item=result
    )

@action(reads=["processed"], writes=["done"])
def finish_processing(state: State) -> State:
    return state.update(done=True)

app = (
    ApplicationBuilder()
    .with_actions(process_item, finish_processing)
    .with_transitions(
        ("process_item", "process_item", expr("processed < len(items)")),
        ("process_item", "finish_processing", default)
    )
    .with_state(items=["a", "b", "c"], processed=0)
    .with_entrypoint("process_item")
    .build()
)
```

## Error Handling

Handle errors gracefully by routing to error actions.

```python
@action(reads=["data"], writes=["result", "error"])
def risky_operation(state: State) -> State:
    """Operation that might fail."""
    try:
        result = dangerous_function(state["data"])
        return state.update(result=result, error=None)
    except Exception as e:
        return state.update(result=None, error=str(e))

@action(reads=["result"], writes=["success_message"])
def handle_success(state: State) -> State:
    return state.update(success_message=f"Success: {state['result']}")

@action(reads=["error"], writes=["error_message"])
def handle_error(state: State) -> State:
    return state.update(error_message=f"Error: {state['error']}")

@action(reads=["data"], writes=["result", "retry_count"])
def retry_operation(state: State) -> State:
    """Retry the operation."""
    retry_count = state.get("retry_count", 0) + 1
    try:
        result = dangerous_function(state["data"])
        return state.update(result=result, error=None, retry_count=retry_count)
    except Exception as e:
        return state.update(result=None, error=str(e), retry_count=retry_count)

app = (
    ApplicationBuilder()
    .with_actions(
        risky_operation,
        handle_success,
        handle_error,
        retry_operation
    )
    .with_transitions(
        ("risky_operation", "handle_success", when(error=None)),
        ("risky_operation", "retry_operation",
         expr("error is not None and retry_count < 3")),
        ("risky_operation", "handle_error", default),
        ("retry_operation", "handle_success", when(error=None)),
        ("retry_operation", "retry_operation",
         expr("error is not None and retry_count < 3")),
        ("retry_operation", "handle_error", default)
    )
    .with_state(data="input", retry_count=0)
    .with_entrypoint("risky_operation")
    .build()
)
```

## Streaming Actions

Stream intermediate results as they're generated.

```python
from typing import Generator, Tuple

@action(reads=["prompt"], writes=["response", "chunks"])
def streaming_llm(state: State) -> Generator[State, None, Tuple[dict, State]]:
    """Stream LLM response token by token."""
    chunks = []

    # Stream tokens from LLM
    for token in llm_stream(state["prompt"]):
        chunks.append(token)
        # Yield intermediate state
        yield state.update(
            chunks=chunks,
            response="".join(chunks)
        )

    # Return final result
    final_response = "".join(chunks)
    result = {"response": final_response}
    return result, state.update(**result)

app = (
    ApplicationBuilder()
    .with_actions(streaming_llm)
    .with_state(prompt="Write a story")
    .with_entrypoint("streaming_llm")
    .build()
)

# Stream results
for state in app.stream_result(halt_after=["streaming_llm"]):
    print(state["response"], end="", flush=True)
```

## Parallel Execution

Execute multiple actions in parallel using Apache Burr's parallelism APIs.

```python
from burr.core.parallelism import MapActions, RunnableGraph
from burr.core import action, State, ApplicationContext, Result
from typing import Dict, Any

@action(reads=["text"], writes=["sentiment"])
def analyze_sentiment(state: State) -> State:
    sentiment = get_sentiment(state["text"])
    return state.update(sentiment=sentiment)

@action(reads=["text"], writes=["entities"])
def extract_entities(state: State) -> State:
    entities = extract_ner(state["text"])
    return state.update(entities=entities)

@action(reads=["text"], writes=["keywords"])
def extract_keywords(state: State) -> State:
    keywords = get_keywords(state["text"])
    return state.update(keywords=keywords)

# Run multiple actions in parallel on the same state
class ParallelTextAnalysis(MapActions):
    def actions(self, state: State, context: ApplicationContext, inputs: Dict[str, Any]):
        yield analyze_sentiment.with_name("sentiment_analysis")
        yield extract_entities.with_name("entity_extraction")
        yield extract_keywords.with_name("keyword_extraction")

    def state(self, state: State, inputs: Dict[str, Any]) -> State:
        return state  # Pass state as-is to all actions

    def reduce(self, state: State, states) -> State:
        """Combine all analysis results."""
        analysis = {}
        for sub_state in states:
            if "sentiment" in sub_state:
                analysis["sentiment"] = sub_state["sentiment"]
            if "entities" in sub_state:
                analysis["entities"] = sub_state["entities"]
            if "keywords" in sub_state:
                analysis["keywords"] = sub_state["keywords"]
        return state.update(analysis=analysis)

    @property
    def reads(self) -> list[str]:
        return ["text"]

    @property
    def writes(self) -> list[str]:
        return ["analysis"]

app = (
    ApplicationBuilder()
    .with_actions(
        parallel_analysis=ParallelTextAnalysis(),
        done=Result("analysis"),
    )
    .with_transitions(("parallel_analysis", "done"))
    .with_state(text="Sample text to analyze")
    .with_entrypoint("parallel_analysis")
    .build()
)
```

## State Persistence

Save and resume application state.

```python
from burr.core.persistence import SQLitePersister

@action(reads=["step"], writes=["step", "result"])
def long_running_step(state: State, step_name: str) -> State:
    """Simulate a long-running operation."""
    result = expensive_computation(step_name)
    return state.update(
        step=step_name,
        result=result
    )

# Set up persister
persister = SQLitePersister(
    db_path="~/.burr/my_app.db",
    table_name="app_state"
)
persister.initialize()

app = (
    ApplicationBuilder()
    .with_actions(
        step1=long_running_step.bind(step_name="step1"),
        step2=long_running_step.bind(step_name="step2"),
        step3=long_running_step.bind(step_name="step3")
    )
    .with_transitions(
        ("step1", "step2"),
        ("step2", "step3")
    )
    .with_identifiers(
        app_id="my-workflow-123",
        partition_key="user-456"
    )
    .with_state_persister(persister)
    .initialize_from(
        persister,
        resume_at_next_action=True,  # Resume from where it left off
        default_state={"step": "none"},
        default_entrypoint="step1"
    )
    .build()
)

# Run - will resume from last saved state if it exists
app.run(halt_after=["step3"])
```

## RAG Pattern

Retrieval-Augmented Generation workflow.

```python
@action(reads=[], writes=["query"])
def process_query(state: State, user_query: str) -> State:
    """Process and normalize user query."""
    return state.update(query=user_query)

@action(reads=["query"], writes=["documents"])
def retrieve_documents(state: State) -> State:
    """Retrieve relevant documents from vector store."""
    docs = vector_db.search(state["query"], top_k=5)
    return state.update(documents=docs)

@action(reads=["documents"], writes=["reranked_documents"])
def rerank_documents(state: State) -> State:
    """Rerank documents for relevance."""
    reranked = reranker.rerank(
        state["query"],
        state["documents"]
    )
    return state.update(reranked_documents=reranked)

@action(reads=["query", "reranked_documents"], writes=["response"])
def generate_response(state: State) -> State:
    """Generate response using LLM with context."""
    context = "\n".join([doc.content for doc in state["reranked_documents"]])
    prompt = f"Context:\n{context}\n\nQuestion: {state['query']}\nAnswer:"

    response = llm.generate(prompt)
    return state.update(response=response)

@action(reads=["response"], writes=["formatted_response", "sources"])
def format_response(state: State) -> State:
    """Format response with citations."""
    sources = [
        {"title": doc.title, "url": doc.url}
        for doc in state["reranked_documents"]
    ]
    formatted = {
        "answer": state["response"],
        "sources": sources
    }
    return state.update(
        formatted_response=formatted,
        sources=sources
    )

app = (
    ApplicationBuilder()
    .with_actions(
        process_query,
        retrieve_documents,
        rerank_documents,
        generate_response,
        format_response
    )
    .with_transitions(
        ("process_query", "retrieve_documents"),
        ("retrieve_documents", "rerank_documents"),
        ("rerank_documents", "generate_response"),
        ("generate_response", "format_response")
    )
    .with_entrypoint("process_query")
    .with_tracker("local", project="rag_chatbot")
    .build()
)

_, _, final_state = app.run(
    halt_after=["format_response"],
    inputs={"user_query": "What is Apache Burr?"}
)
print(final_state["formatted_response"])
```

## Using Action Binding

Reuse actions with different parameters.

```python
@action(reads=["text"], writes=["processed_text"])
def transform_text(state: State, operation: str, params: dict) -> State:
    """Generic text transformation action."""
    text = state["text"]

    if operation == "uppercase":
        result = text.upper()
    elif operation == "replace":
        result = text.replace(params["old"], params["new"])
    elif operation == "truncate":
        result = text[:params["length"]]

    return state.update(processed_text=result)

# Create specialized actions via binding
uppercase_action = transform_text.bind(operation="uppercase", params={})
replace_action = transform_text.bind(
    operation="replace",
    params={"old": "bad", "new": "good"}
)
truncate_action = transform_text.bind(
    operation="truncate",
    params={"length": 100}
)

app = (
    ApplicationBuilder()
    .with_actions(
        uppercase=uppercase_action,
        replace=replace_action,
        truncate=truncate_action
    )
    .with_transitions(
        ("uppercase", "replace"),
        ("replace", "truncate")
    )
    .with_state(text="This is bad text that is too long...")
    .with_entrypoint("uppercase")
    .build()
)
```

## Testing Actions

Actions are pure functions - easy to test!

```python
import pytest
from burr.core import State

def test_increment_action():
    """Test the increment action."""
    state = State({"counter": 5})
    new_state = increment(state)

    assert new_state["counter"] == 6
    assert state["counter"] == 5  # Original unchanged (immutable)

def test_chatbot_response():
    """Test AI response action."""
    state = State({
        "chat_history": [
            {"role": "user", "content": "Hello"}
        ]
    })

    new_state = ai_response(state)

    assert "response" in new_state
    assert len(new_state["chat_history"]) == 2
    assert new_state["chat_history"][-1]["role"] == "assistant"

def test_conditional_flow():
    """Test complete application flow."""
    app = build_conditional_app()

    _, _, state = app.run(
        halt_after=["admin_greeting"],
        inputs={"user_type": "admin"}
    )

    assert state["greeting"] == "Welcome, Administrator!"

@pytest.mark.asyncio
async def test_async_action():
    """Test async action."""
    state = State({"url": "https://api.example.com/data"})
    new_state = await fetch_data(state)

    assert "data" in new_state
```

---

## Pydantic Typed State

Use Pydantic models for type-safe state with IDE support and validation.

```python
from pydantic import BaseModel, Field
from typing import Optional
from burr.core import action, ApplicationBuilder
from burr.integrations.pydantic import PydanticTypingSystem

# Define state schema with Pydantic
class ChatState(BaseModel):
    prompt: Optional[str] = Field(default=None, description="User prompt")
    response: Optional[str] = Field(default=None, description="AI response")
    chat_history: list[dict] = Field(default_factory=list, description="Conversation history")

# Use @action.pydantic decorator
@action.pydantic(reads=[], writes=["prompt", "chat_history"])
def human_input_typed(state: ChatState, prompt: str) -> ChatState:
    """Capture user input with typed state."""
    # Access state as attributes (not brackets)
    state.prompt = prompt
    state.chat_history.append({"role": "user", "content": prompt})
    # Return the state object directly (not tuple)
    return state

@action.pydantic(reads=["chat_history"], writes=["response", "chat_history"])
def ai_response_typed(state: ChatState) -> ChatState:
    """Generate AI response with typed state."""
    # Read using attribute access
    chat_history = state.chat_history

    # Process
    response = call_llm(chat_history)

    # Mutate in-place (on internal copy) and return
    state.response = response
    state.chat_history.append({"role": "assistant", "content": response})
    return state

# Configure application with typing system
app = (
    ApplicationBuilder()
    .with_typing(PydanticTypingSystem(ChatState))
    .with_actions(human_input_typed, ai_response_typed)
    .with_transitions(
        ("human_input_typed", "ai_response_typed"),
        ("ai_response_typed", "human_input_typed")
    )
    .with_state(ChatState())  # Initialize with Pydantic model
    .with_entrypoint("human_input_typed")
    .build()
)

# Run and access typed state
action, result, state = app.run(
    halt_after=["ai_response_typed"],
    inputs={"prompt": "Hello!"}
)

# Access state data through .data property
print(state.data.response)  # IDE autocomplete!
print(state.data.chat_history)
```

**Key differences from regular state:**
- Use `@action.pydantic` decorator instead of `@action`
- State parameter type is your Pydantic model (`ChatState`), not `State`
- Access with attributes (`state.prompt`) not brackets (`state["prompt"]`)
- Return state object directly, not `Tuple[dict, State]`
- Mutations happen in-place (on internal copy)
- Full IDE support: autocomplete, type checking, validation

---

For more examples, see the `examples/` directory in the Apache Burr repository:
- `examples/hello-world-counter/`
- `examples/multi-modal-chatbot/`
- `examples/conversational-rag/`
- `examples/email-assistant/`
- `examples/typed-state/`
