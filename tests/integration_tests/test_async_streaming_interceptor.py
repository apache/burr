# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Integration tests for async streaming action interceptors."""
import asyncio
from typing import Any, AsyncGenerator, Dict, Optional, Tuple

import pytest

from burr.core import Action, ApplicationBuilder, State
from burr.core.action import streaming_action
from burr.lifecycle import (
    PostEndStreamHookWorkerAsync,
    PreStartStreamHookWorkerAsync,
    StreamingActionInterceptorHookAsync,
)


@streaming_action(reads=["prompt"], writes=["response"], tags=["async_streaming_intercepted"])
async def async_streaming_responder(
    state: State, prompt: str = ""
) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
    """Async streaming action that yields tokens one by one."""
    tokens = ["Hello", " ", "Async", " ", "World", "!"]
    buffer = []
    for token in tokens:
        # Simulate async work (e.g., API call)
        await asyncio.sleep(0.001)
        buffer.append(token)
        yield {"response": token}, None
    full_response = "".join(buffer)
    yield {"response": full_response}, state.update(response=full_response)


@streaming_action(reads=["count"], writes=["numbers"], tags=["async_streaming_intercepted"])
async def async_count_streamer(
    state: State, count: int = 5
) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
    """Async streaming action that counts from 1 to count."""
    numbers = []
    for i in range(1, count + 1):
        await asyncio.sleep(0.001)
        numbers.append(i)
        yield {"numbers": i}, None
    yield {"numbers": numbers}, state.update(numbers=numbers)


class AsyncStreamingWorkerPreHook(PreStartStreamHookWorkerAsync):
    """Async worker hook that runs before streaming action execution."""

    def __init__(self):
        self.called_actions = []
        self.call_count = 0

    async def pre_start_stream_worker(
        self, *, action: str, state: State, inputs: Dict[str, Any], **future_kwargs: Any
    ):
        self.called_actions.append(("pre_stream", action))
        self.call_count += 1


class AsyncStreamingWorkerPostHook(PostEndStreamHookWorkerAsync):
    """Async worker hook that runs after streaming action execution."""

    def __init__(self):
        self.called_actions = []
        self.call_count = 0

    async def post_end_stream_worker(
        self,
        *,
        action: str,
        result: Optional[Dict[str, Any]],
        exception: Exception,
        **future_kwargs: Any,
    ):
        self.called_actions.append(("post_stream", action))
        self.call_count += 1


class AsyncStreamingInterceptor(StreamingActionInterceptorHookAsync):
    """Async streaming interceptor that wraps streaming action execution."""

    def __init__(self):
        self.intercepted_actions = []
        self.intercept_count = 0
        self.stream_items_processed = []

    def should_intercept(self, *, action: Action, **future_kwargs: Any) -> bool:
        """Intercept actions tagged with 'async_streaming_intercepted'."""
        return "async_streaming_intercepted" in action.tags

    async def intercept_stream_run_and_update(
        self,
        *,
        action: Action,
        state: State,
        inputs: Dict[str, Any],
        **future_kwargs: Any,
    ) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
        """Intercept and wrap the streaming action execution."""
        self.intercepted_actions.append(action.name)
        self.intercept_count += 1

        # Extract worker_adapter_set if provided
        worker_adapter_set = future_kwargs.get("worker_adapter_set")

        # Call worker pre-stream-hooks if they exist
        if worker_adapter_set:
            await worker_adapter_set.call_all_lifecycle_hooks_async(
                "pre_start_stream_worker",
                action=action.name,
                state=state,
                inputs=inputs,
            )

        # Run the streaming action normally (simulating remote execution)
        # This is an async generator, so we need to iterate with async for
        generator = action.stream_run_and_update(state, **inputs)
        result = None
        async for item in generator:
            result = item
            self.stream_items_processed.append(item[0])  # Store the result dict
            yield item

        # Call worker post-stream-hooks if they exist
        if worker_adapter_set and result:
            await worker_adapter_set.call_all_lifecycle_hooks_async(
                "post_end_stream_worker",
                action=action.name,
                result=result[0] if result else None,
                exception=None,
            )


@pytest.mark.asyncio
async def test_async_streaming_interceptor_intercepts_action():
    """Test that async streaming interceptor intercepts tagged actions."""
    interceptor = AsyncStreamingInterceptor()

    app = (
        ApplicationBuilder()
        .with_state(prompt="test")
        .with_actions(async_streaming_responder)
        .with_entrypoint("async_streaming_responder")
        .with_hooks(interceptor)
        .build()
    )

    # Run async streaming action
    action, streaming_container = await app.astream_result(
        halt_after=["async_streaming_responder"],
    )

    # Consume the stream
    tokens = []
    async for item in streaming_container:
        tokens.append(item["response"])

    result, final_state = await streaming_container.get()

    # Verify interceptor ran
    assert "async_streaming_responder" in interceptor.intercepted_actions
    assert interceptor.intercept_count == 1

    # Verify streaming worked correctly
    assert tokens == ["Hello", " ", "Async", " ", "World", "!"]
    assert final_state["response"] == "Hello Async World!"
    assert result["response"] == "Hello Async World!"

    # Verify interceptor processed all stream items
    assert len(interceptor.stream_items_processed) == 7  # 6 intermediate + 1 final


@pytest.mark.asyncio
async def test_async_streaming_interceptor_with_worker_hooks():
    """Test that async streaming interceptor properly calls worker hooks."""
    interceptor = AsyncStreamingInterceptor()
    worker_pre = AsyncStreamingWorkerPreHook()
    worker_post = AsyncStreamingWorkerPostHook()

    app = (
        ApplicationBuilder()
        .with_state(prompt="test")
        .with_actions(async_streaming_responder)
        .with_entrypoint("async_streaming_responder")
        .with_hooks(interceptor, worker_pre, worker_post)
        .build()
    )

    # Run async streaming action
    action, streaming_container = await app.astream_result(
        halt_after=["async_streaming_responder"],
    )

    # Consume the stream
    async for item in streaming_container:
        pass  # Consume all items

    result, final_state = await streaming_container.get()

    # Verify interceptor ran
    assert "async_streaming_responder" in interceptor.intercepted_actions

    # Verify worker hooks were called
    assert ("pre_stream", "async_streaming_responder") in worker_pre.called_actions
    assert ("post_stream", "async_streaming_responder") in worker_post.called_actions
    assert worker_pre.call_count == 1
    assert worker_post.call_count == 1


@pytest.mark.asyncio
async def test_async_streaming_interceptor_only_intercepts_tagged_actions():
    """Test that interceptor only intercepts actions with the correct tag."""

    @streaming_action(reads=["x"], writes=["y"], tags=["not_intercepted"])
    async def non_intercepted_streaming(
        state: State,
    ) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
        """Streaming action that should NOT be intercepted."""
        yield {"y": "not intercepted"}, None
        yield {"y": "not intercepted"}, state.update(y="not intercepted")

    interceptor = AsyncStreamingInterceptor()

    app = (
        ApplicationBuilder()
        .with_state(x=5)
        .with_actions(async_streaming_responder, non_intercepted_streaming)
        .with_transitions(
            ("async_streaming_responder", "non_intercepted_streaming"),
        )
        .with_entrypoint("async_streaming_responder")
        .with_hooks(interceptor)
        .build()
    )

    # Run first action (should be intercepted)
    action1, streaming_container1 = await app.astream_result(
        halt_after=["async_streaming_responder"],
    )
    async for item in streaming_container1:
        pass
    await streaming_container1.get()

    # Run second action (should NOT be intercepted)
    action2, streaming_container2 = await app.astream_result(
        halt_after=["non_intercepted_streaming"],
    )
    async for item in streaming_container2:
        pass
    await streaming_container2.get()

    # Verify only tagged action was intercepted
    assert "async_streaming_responder" in interceptor.intercepted_actions
    assert "non_intercepted_streaming" not in interceptor.intercepted_actions
    assert interceptor.intercept_count == 1


@pytest.mark.asyncio
async def test_async_streaming_interceptor_with_multiple_stream_items():
    """Test async streaming interceptor with an action that yields many items."""
    interceptor = AsyncStreamingInterceptor()

    app = (
        ApplicationBuilder()
        .with_state(count=10)
        .with_actions(async_count_streamer)
        .with_entrypoint("async_count_streamer")
        .with_hooks(interceptor)
        .build()
    )

    # Run async streaming action
    action, streaming_container = await app.astream_result(
        halt_after=["async_count_streamer"],
        inputs={"count": 10},  # Pass count as input
    )

    # Consume the stream
    numbers = []
    async for item in streaming_container:
        numbers.append(item["numbers"])

    result, final_state = await streaming_container.get()

    # Verify interceptor ran
    assert "async_count_streamer" in interceptor.intercepted_actions

    # Verify all stream items were processed
    assert numbers == list(range(1, 11))  # 1 to 10
    assert final_state["numbers"] == list(range(1, 11))
    assert result["numbers"] == list(range(1, 11))

    # Verify interceptor processed all items (10 intermediate + 1 final)
    assert len(interceptor.stream_items_processed) == 11


@pytest.mark.asyncio
async def test_async_streaming_interceptor_preserves_state_updates():
    """Test that async streaming interceptor preserves state updates correctly."""
    interceptor = AsyncStreamingInterceptor()

    app = (
        ApplicationBuilder()
        .with_state(prompt="test", counter=0)
        .with_actions(async_streaming_responder)
        .with_entrypoint("async_streaming_responder")
        .with_hooks(interceptor)
        .build()
    )

    # Run async streaming action
    action, streaming_container = await app.astream_result(
        halt_after=["async_streaming_responder"],
    )

    # Consume the stream
    async for item in streaming_container:
        pass

    result, final_state = await streaming_container.get()

    # Verify state was updated correctly
    assert "response" in final_state
    assert final_state["response"] == "Hello Async World!"
    assert final_state["prompt"] == "test"  # Original state preserved
    assert final_state["counter"] == 0  # Original state preserved
