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

"""LiteLLM integration for Burr.

This module provides Action classes for invoking LLM models through
the LiteLLM AI gateway within Burr applications. LiteLLM supports
100+ providers (OpenAI, Anthropic, Google, Azure, AWS Bedrock, Ollama,
Groq, Mistral, and more) through a unified interface.

Example usage:
    from burr.integrations.litellm import LiteLLMAction

    def prompt_mapper(state):
        return {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": state["user_input"]},
            ],
        }

    action = LiteLLMAction(
        model="anthropic/claude-sonnet-4-6",
        input_mapper=prompt_mapper,
        reads=["user_input"],
        writes=["response"],
    )
"""

import logging
from typing import Any, Generator, Optional, Protocol

from burr.core.action import SingleStepAction, StreamingAction
from burr.core.state import State
from burr.integrations.base import require_plugin

logger = logging.getLogger(__name__)

try:
    import litellm
except ImportError as e:
    require_plugin(e, "litellm")


class StateToMessagesMapper(Protocol):
    """Protocol for mapping Burr state to LiteLLM messages format."""

    def __call__(self, state: State) -> dict[str, Any]:
        ...  # noqa: E704


class _LiteLLMCore:
    """Shared LiteLLM configuration and request building."""

    def __init__(
        self,
        model: str,
        input_mapper: StateToMessagesMapper,
        reads: list[str],
        writes: list[str],
        name: str,
        api_key: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        extra_kwargs: Optional[dict[str, Any]],
    ):
        self._model = model
        self._input_mapper = input_mapper
        self._reads = reads
        self._writes = writes
        self._name = name
        self._api_key = api_key
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._extra_kwargs = extra_kwargs or {}

    @property
    def reads(self) -> list[str]:
        return self._reads

    @property
    def writes(self) -> list[str]:
        return self._writes

    @property
    def name(self) -> str:
        return self._name

    def build_completion_kwargs(self, state: State, stream: bool = False) -> dict[str, Any]:
        """Build kwargs for litellm.completion from current state."""
        prompt = self._input_mapper(state)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": prompt["messages"],
            "stream": stream,
            "drop_params": True,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if self._max_tokens is not None:
            kwargs["max_tokens"] = self._max_tokens
        kwargs.update(self._extra_kwargs)
        return kwargs


def _result_for_writes(
    text: str,
    usage: dict[str, Any],
    writes: list[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "response": text,
        "usage": usage,
    }
    for w in writes:
        if w == "usage":
            result[w] = usage
        else:
            result[w] = text
    return result


class _LiteLLMBase:
    """Shared LiteLLM wiring for action subclasses."""

    _llm: _LiteLLMCore

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def _init_litellm_core(
        self,
        model: str,
        input_mapper: StateToMessagesMapper,
        reads: list[str],
        writes: list[str],
        name: str,
        api_key: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        extra_kwargs: Optional[dict[str, Any]],
    ) -> None:
        self._llm = _LiteLLMCore(
            model=model,
            input_mapper=input_mapper,
            reads=reads,
            writes=writes,
            name=name,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_kwargs=extra_kwargs,
        )

    @property
    def reads(self) -> list[str]:
        return self._llm.reads

    @property
    def writes(self) -> list[str]:
        return self._llm.writes

    @property
    def name(self) -> str:
        return self._llm.name


class LiteLLMAction(_LiteLLMBase, SingleStepAction):
    """Action that invokes LLM models through the LiteLLM AI gateway.

    :param model: LiteLLM model string (e.g. ``anthropic/claude-sonnet-4-6``,
        ``openai/gpt-4o``, ``groq/llama-4-scout-17b-16e-instruct``).
    :param input_mapper: Callable mapping :class:`~burr.core.state.State` to
        a dict with a ``messages`` key (OpenAI chat format).
    :param reads: State keys this action reads.
    :param writes: State keys to update (typically include ``response``).
    :param name: Action name for the graph.
    :param api_key: Optional API key (falls back to provider env vars).
    :param temperature: Optional sampling temperature.
    :param max_tokens: Optional max tokens for the response.
    :param extra_kwargs: Additional kwargs passed to ``litellm.completion``.
    """

    def __init__(
        self,
        model: str,
        input_mapper: StateToMessagesMapper,
        reads: list[str],
        writes: list[str],
        name: str = "litellm_invoke",
        api_key: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        extra_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__()
        self._init_litellm_core(
            model=model,
            input_mapper=input_mapper,
            reads=reads,
            writes=writes,
            name=name,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_kwargs=extra_kwargs,
        )

    def run_and_update(self, state: State, **run_kwargs) -> tuple[dict, State]:
        kwargs = self._llm.build_completion_kwargs(state)
        response = litellm.completion(**kwargs)

        text = response.choices[0].message.content or ""
        usage = dict(response.usage) if response.usage else {}

        result = _result_for_writes(text, usage, self._llm.writes)
        updates = {key: result[key] for key in self._llm.writes if key in result}
        new_state = state.update(**updates)

        return result, new_state


class LiteLLMStreamingAction(_LiteLLMBase, StreamingAction):
    """Streaming LiteLLM action.

    Parameters match :class:`LiteLLMAction` except the default ``name`` is
    ``litellm_stream``. Yields chunk dicts from :meth:`stream_run` and merges
    the final response in :meth:`update`.
    """

    def __init__(
        self,
        model: str,
        input_mapper: StateToMessagesMapper,
        reads: list[str],
        writes: list[str],
        name: str = "litellm_stream",
        api_key: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        extra_kwargs: Optional[dict[str, Any]] = None,
    ):
        super().__init__()
        self._init_litellm_core(
            model=model,
            input_mapper=input_mapper,
            reads=reads,
            writes=writes,
            name=name,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_kwargs=extra_kwargs,
        )

    def stream_run(self, state: State, **run_kwargs) -> Generator[dict, None, None]:
        kwargs = self._llm.build_completion_kwargs(state, stream=True)
        response = litellm.completion(**kwargs)

        text_parts: list[str] = []
        for chunk in response:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            content = getattr(delta, "content", None)
            if isinstance(content, str) and content:
                text_parts.append(content)
                full_response = "".join(text_parts)
                yield {"chunk": content, "response": full_response}

        full_text = "".join(text_parts)
        payload = _result_for_writes(full_text, {}, self._llm.writes)
        yield {"chunk": "", "complete": True, **payload}

    def update(self, result: dict, state: State) -> State:
        if result.get("complete"):
            updates = {key: result[key] for key in self._llm.writes if key in result}
            return state.update(**updates)
        return state
