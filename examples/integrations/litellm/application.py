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

"""Minimal Burr apps using :class:`~burr.integrations.litellm.LiteLLMAction`
and :class:`~burr.integrations.litellm.LiteLLMStreamingAction`.

LiteLLM supports 100+ LLM providers through a unified interface.
Set the appropriate provider API key (e.g. ``OPENAI_API_KEY``,
``ANTHROPIC_API_KEY``) and optionally ``LITELLM_MODEL`` before running.
"""

from __future__ import annotations

import os

from burr.core import Application, ApplicationBuilder, State, default
from burr.core.action import action
from burr.integrations.litellm import LiteLLMAction, LiteLLMStreamingAction


def _default_model() -> str:
    return os.environ.get("LITELLM_MODEL", "openai/gpt-4o-mini")


def prompt_mapper(state: State) -> dict:
    """Map Burr state to LiteLLM messages format (OpenAI chat format)."""
    return {
        "messages": [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": state["user_input"]},
        ],
    }


@action(reads=[], writes=["user_input"])
def set_user_input(state: State, user_input: str) -> State:
    return state.update(user_input=user_input)


def application(model: str | None = None) -> Application:
    """Builds a graph with :class:`~burr.integrations.litellm.LiteLLMAction` (non-streaming)."""
    invoke = LiteLLMAction(
        model=model or _default_model(),
        input_mapper=prompt_mapper,
        reads=["user_input"],
        writes=["response"],
        name="invoke_litellm",
        max_tokens=512,
    )
    return (
        ApplicationBuilder()
        .with_actions(set_prompt=set_user_input, invoke_litellm=invoke)
        .with_transitions(
            ("set_prompt", "invoke_litellm", default),
        )
        .with_state(user_input="", response="")
        .with_entrypoint("set_prompt")
        .build()
    )


def streaming_application(model: str | None = None) -> Application:
    """Builds a graph with :class:`~burr.integrations.litellm.LiteLLMStreamingAction`."""
    stream = LiteLLMStreamingAction(
        model=model or _default_model(),
        input_mapper=prompt_mapper,
        reads=["user_input"],
        writes=["response"],
        name="stream_litellm",
        max_tokens=512,
    )
    return (
        ApplicationBuilder()
        .with_actions(set_prompt=set_user_input, stream_litellm=stream)
        .with_transitions(
            ("set_prompt", "stream_litellm", default),
        )
        .with_state(user_input="", response="")
        .with_entrypoint("set_prompt")
        .build()
    )


def _demo_invoke() -> None:
    app = application()
    _, _, state = app.run(
        halt_after=["invoke_litellm"],
        inputs={"user_input": "Explain what Burr is in one short sentence."},
    )
    print(state["response"])


def _demo_stream() -> None:
    app = streaming_application()
    _, streaming_result = app.stream_result(
        halt_after=["stream_litellm"],
        inputs={"user_input": "Count from 1 to 5, separated by commas."},
    )
    for item in streaming_result:
        chunk = item.get("chunk") or ""
        if chunk:
            print(chunk, end="", flush=True)
    print()
    _, state = streaming_result.get()
    print("Final response:", state["response"])


if __name__ == "__main__":
    print("--- LiteLLMAction (non-streaming) ---")
    _demo_invoke()
    print()
    print("--- LiteLLMStreamingAction (streaming) ---")
    _demo_stream()
