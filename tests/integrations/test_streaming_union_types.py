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

"""
Tests for union type support in @streaming_action.pydantic() decorator.

This module tests that the stream_type parameter accepts union types,
including both | operator (Python 3.10+) and typing.Union syntax.
"""

import asyncio
import sys
from typing import AsyncGenerator, Generator, List, Optional, Tuple, Union

import pytest
from pydantic import BaseModel

from burr.core.action import FunctionBasedAction, streaming_action
from burr.core.state import State
from burr.integrations.pydantic import PydanticTypingSystem, pydantic_streaming_action


# ============================================================================
# Test Models
# ============================================================================


class TextChunk(BaseModel):
    """Represents a text chunk from a stream."""

    text: str
    chunk_id: int


class StructuredResult(BaseModel):
    """Represents a structured result."""

    summary: str
    confidence: float


class Token(BaseModel):
    """Represents a token from a stream."""

    value: str
    position: int


class StreamingInputState(BaseModel):
    """Input state for streaming tests."""

    prompt: str
    mode: str = "default"


class StreamingOutputState(BaseModel):
    """Output state for streaming tests."""

    result: str
    processing_time: float = 0.0


# ============================================================================
# Backward Compatibility Tests (Single Types)
# ============================================================================


def test_streaming_action_single_model_type_backward_compat():
    """Test that single model types still work (backward compatibility)."""

    @streaming_action.pydantic(
        reads=["prompt"],
        writes=["result"],
        state_input_type=StreamingInputState,
        state_output_type=StreamingOutputState,
        stream_type=TextChunk,  # Single type (should still work)
    )
    def act(
        state: State,
    ) -> Generator[Tuple[TextChunk, Optional[StreamingOutputState]], None, None]:
        yield TextChunk(text="Hello", chunk_id=1), None
        yield TextChunk(text="World", chunk_id=2), StreamingOutputState(result="Complete")

    # Verify the action was created successfully
    assert hasattr(act, "bind")
    assert hasattr(act, FunctionBasedAction.ACTION_FUNCTION)


def test_streaming_action_dict_type_backward_compat():
    """Test that dict type still works (backward compatibility)."""

    @streaming_action.pydantic(
        reads=["prompt"],
        writes=["result"],
        state_input_type=StreamingInputState,
        state_output_type=StreamingOutputState,
        stream_type=dict,  # dict type (should still work)
    )
    def act(
        state: State,
    ) -> Generator[Tuple[dict, Optional[StreamingOutputState]], None, None]:
        yield {"text": "Hello", "chunk_id": 1}, None
        yield {"text": "World", "chunk_id": 2}, StreamingOutputState(result="Complete")

    # Verify the action was created successfully
    assert hasattr(act, "bind")
    assert hasattr(act, FunctionBasedAction.ACTION_FUNCTION)


# ============================================================================
# Union Type Tests - typing.Union Syntax
# ============================================================================


def test_streaming_action_typing_union_two_models():
    """Test streaming action with Union[Model1, Model2] syntax."""

    @streaming_action.pydantic(
        reads=["prompt"],
        writes=["result"],
        state_input_type=StreamingInputState,
        state_output_type=StreamingOutputState,
        stream_type=Union[TextChunk, StructuredResult],  # Union syntax
    )
    def act(
        state: State,
    ) -> Generator[Tuple[Union[TextChunk, StructuredResult], Optional[StreamingOutputState]], None, None]:
        yield TextChunk(text="Hello", chunk_id=1), None
        yield StructuredResult(summary="Complete", confidence=0.95), StreamingOutputState(
            result="Done"
        )

    # Verify the action was created successfully
    assert hasattr(act, "bind")
    assert hasattr(act, FunctionBasedAction.ACTION_FUNCTION)


def test_streaming_action_typing_union_three_models():
    """Test streaming action with Union of three models."""

    @streaming_action.pydantic(
        reads=["prompt"],
        writes=["result"],
        state_input_type=StreamingInputState,
        state_output_type=StreamingOutputState,
        stream_type=Union[TextChunk, StructuredResult, Token],  # Union of 3 types
    )
    def act(
        state: State,
    ) -> Generator[
        Tuple[Union[TextChunk, StructuredResult, Token], Optional[StreamingOutputState]], None, None
    ]:
        yield TextChunk(text="Hello", chunk_id=1), None
        yield Token(value="world", position=2), None
        yield StructuredResult(summary="Complete", confidence=0.95), StreamingOutputState(
            result="Done"
        )

    # Verify the action was created successfully
    assert hasattr(act, "bind")
    assert hasattr(act, FunctionBasedAction.ACTION_FUNCTION)


@pytest.mark.skipif(sys.version_info < (3, 10), reason="requires python3.10+")
def test_streaming_action_pipe_union_two_models():
    """Test streaming action with Model1 | Model2 syntax (Python 3.10+)."""
    # Using exec to avoid syntax error on Python < 3.10
    code = """
@streaming_action.pydantic(
    reads=["prompt"],
    writes=["result"],
    state_input_type=StreamingInputState,
    state_output_type=StreamingOutputState,
    stream_type=TextChunk | StructuredResult,  # Pipe syntax
)
def act(
    state: State,
) -> Generator[Tuple[TextChunk | StructuredResult, Optional[StreamingOutputState]], None, None]:
    yield TextChunk(text="Hello", chunk_id=1), None
    yield StructuredResult(summary="Complete", confidence=0.95), StreamingOutputState(
        result="Done"
    )

result = (hasattr(act, "bind"), hasattr(act, FunctionBasedAction.ACTION_FUNCTION))
"""
    namespace = {
        "streaming_action": streaming_action,
        "TextChunk": TextChunk,
        "StructuredResult": StructuredResult,
        "StreamingInputState": StreamingInputState,
        "StreamingOutputState": StreamingOutputState,
        "State": State,
        "Generator": Generator,
        "Tuple": Tuple,
        "Optional": Optional,
        "FunctionBasedAction": FunctionBasedAction,
    }
    exec(code, namespace)
    has_bind, has_action_func = namespace["result"]
    assert has_bind
    assert has_action_func


@pytest.mark.skipif(sys.version_info < (3, 10), reason="requires python3.10+")
def test_streaming_action_pipe_union_three_models():
    """Test streaming action with Model1 | Model2 | Model3 syntax (Python 3.10+)."""
    code = """
@streaming_action.pydantic(
    reads=["prompt"],
    writes=["result"],
    state_input_type=StreamingInputState,
    state_output_type=StreamingOutputState,
    stream_type=TextChunk | StructuredResult | Token,  # Pipe syntax with 3 types
)
def act(
    state: State,
) -> Generator[Tuple[TextChunk | StructuredResult | Token, Optional[StreamingOutputState]], None, None]:
    yield TextChunk(text="Hello", chunk_id=1), None
    yield Token(value="world", position=2), None
    yield StructuredResult(summary="Complete", confidence=0.95), StreamingOutputState(
        result="Done"
    )

result = (hasattr(act, "bind"), hasattr(act, FunctionBasedAction.ACTION_FUNCTION))
"""
    namespace = {
        "streaming_action": streaming_action,
        "TextChunk": TextChunk,
        "StructuredResult": StructuredResult,
        "Token": Token,
        "StreamingInputState": StreamingInputState,
        "StreamingOutputState": StreamingOutputState,
        "State": State,
        "Generator": Generator,
        "Tuple": Tuple,
        "Optional": Optional,
        "FunctionBasedAction": FunctionBasedAction,
    }
    exec(code, namespace)
    has_bind, has_action_func = namespace["result"]
    assert has_bind
    assert has_action_func


# ============================================================================
# pydantic_streaming_action Tests
# ============================================================================


def test_pydantic_streaming_action_union_decorator():
    """Test that pydantic_streaming_action also accepts union types."""

    @pydantic_streaming_action(
        reads=["prompt"],
        writes=["result"],
        state_input_type=StreamingInputState,
        state_output_type=StreamingOutputState,
        stream_type=Union[TextChunk, StructuredResult],  # Union in decorator
    )
    def act(
        state: StreamingInputState,
    ) -> Generator[Tuple[Union[TextChunk, StructuredResult], Optional[StreamingOutputState]], None, None]:
        yield TextChunk(text="Hello", chunk_id=1), None
        yield StructuredResult(summary="Complete", confidence=0.95), StreamingOutputState(
            result="Done"
        )

    # Verify the action was created successfully
    assert hasattr(act, "bind")
    assert hasattr(act, FunctionBasedAction.ACTION_FUNCTION)


# ============================================================================
# Async Union Type Tests
# ============================================================================


@pytest.mark.asyncio
async def test_streaming_action_async_union():
    """Test async streaming action with union types."""

    @streaming_action.pydantic(
        reads=["prompt"],
        writes=["result"],
        state_input_type=StreamingInputState,
        state_output_type=StreamingOutputState,
        stream_type=Union[TextChunk, StructuredResult],
    )
    async def act(
        state: State,
    ) -> AsyncGenerator[Tuple[Union[TextChunk, StructuredResult], Optional[StreamingOutputState]], None]:
        yield TextChunk(text="Hello", chunk_id=1), None
        await asyncio.sleep(0.001)
        yield StructuredResult(summary="Complete", confidence=0.95), StreamingOutputState(
            result="Done"
        )

    # Verify the action was created successfully
    assert hasattr(act, "bind")
    assert hasattr(act, FunctionBasedAction.ACTION_FUNCTION)


# ============================================================================
# Runtime Execution Tests
# ============================================================================


def test_streaming_action_union_execution():
    """Test that union type streaming actions execute correctly."""

    @pydantic_streaming_action(
        reads=["prompt"],
        writes=["result"],
        state_input_type=StreamingInputState,
        state_output_type=StreamingOutputState,
        stream_type=Union[TextChunk, StructuredResult],
    )
    def act(
        state: StreamingInputState,
    ) -> Generator[Tuple[Union[TextChunk, StructuredResult], Optional[StreamingOutputState]], None, None]:
        # Yield both types
        yield TextChunk(text="chunk", chunk_id=1), None
        yield TextChunk(text="chunk2", chunk_id=2), None
        yield StructuredResult(summary="done", confidence=0.9), StreamingOutputState(
            result="Complete"
        )

    # Execute the action
    action_fn = getattr(act, FunctionBasedAction.ACTION_FUNCTION)
    state = State(
        {"prompt": "test", "mode": "default"},
        typing_system=PydanticTypingSystem(StreamingInputState),
    )
    gen = action_fn.fn(state)
    results = list(gen)

    # Verify results
    assert len(results) == 3
    assert isinstance(results[0][0], TextChunk)
    assert isinstance(results[1][0], TextChunk)
    assert isinstance(results[2][0], StructuredResult)
    assert results[0][1] is None
    assert results[1][1] is None
    assert isinstance(results[2][1], State)


def test_streaming_action_union_execution_three_types():
    """Test union type execution with three different model types."""

    @pydantic_streaming_action(
        reads=["prompt"],
        writes=["result"],
        state_input_type=StreamingInputState,
        state_output_type=StreamingOutputState,
        stream_type=Union[TextChunk, StructuredResult, Token],
    )
    def act(
        state: StreamingInputState,
    ) -> Generator[
        Tuple[Union[TextChunk, StructuredResult, Token], Optional[StreamingOutputState]], None, None
    ]:
        # Yield all three types
        yield TextChunk(text="hello", chunk_id=1), None
        yield Token(value="world", position=2), None
        yield StructuredResult(summary="complete", confidence=0.95), StreamingOutputState(
            result="Done"
        )

    # Execute the action
    action_fn = getattr(act, FunctionBasedAction.ACTION_FUNCTION)
    state = State(
        {"prompt": "test", "mode": "default"},
        typing_system=PydanticTypingSystem(StreamingInputState),
    )
    gen = action_fn.fn(state)
    results = list(gen)

    # Verify results
    assert len(results) == 3
    assert isinstance(results[0][0], TextChunk)
    assert isinstance(results[1][0], Token)
    assert isinstance(results[2][0], StructuredResult)
    assert all(item[1] is None for item in results[:-1])
    assert isinstance(results[2][1], State)
