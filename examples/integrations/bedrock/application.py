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

"""Minimal Burr apps using :class:`~burr.integrations.bedrock.BedrockAction`
and :class:`~burr.integrations.bedrock.BedrockStreamingAction`.

Configure AWS credentials (for example via ``aws configure`` or environment
variables) and optionally set ``BEDROCK_MODEL_ID`` and ``AWS_REGION`` /
``AWS_DEFAULT_REGION`` before running.
"""

from __future__ import annotations

import os

from burr.core import Application, ApplicationBuilder, State, default
from burr.core.action import action
from burr.integrations import BedrockAction, BedrockStreamingAction


def _default_model_id() -> str:
    return os.environ.get(
        "BEDROCK_MODEL_ID",
        "anthropic.claude-3-haiku-20240307-v1:0",
    )


def _aws_region() -> str | None:
    return os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION")


def prompt_mapper(state: State) -> dict:
    """Map Burr state to Bedrock Converse ``messages`` / ``system``."""
    return {
        "messages": [{"role": "user", "content": [{"text": state["user_input"]}]}],
        "system": [{"text": "You are a concise assistant."}],
    }


@action(reads=[], writes=["user_input"])
def set_user_input(state: State, user_input: str) -> State:
    return state.update(user_input=user_input)


def application(
    model_id: str | None = None,
    region: str | None = None,
) -> Application:
    """Builds a graph with :class:`~burr.integrations.bedrock.BedrockAction` (non-streaming)."""
    invoke = BedrockAction(
        model_id=model_id or _default_model_id(),
        input_mapper=prompt_mapper,
        reads=["user_input"],
        writes=["response"],
        name="invoke_bedrock",
        region=region if region is not None else _aws_region(),
        inference_config={"maxTokens": 512},
    )
    return (
        ApplicationBuilder()
        .with_actions(set_prompt=set_user_input, invoke_bedrock=invoke)
        .with_transitions(
            ("set_prompt", "invoke_bedrock", default),
        )
        .with_state(user_input="", response="")
        .with_entrypoint("set_prompt")
        .build()
    )


def streaming_application(
    model_id: str | None = None,
    region: str | None = None,
) -> Application:
    """Builds a graph with :class:`~burr.integrations.bedrock.BedrockStreamingAction`."""
    stream = BedrockStreamingAction(
        model_id=model_id or _default_model_id(),
        input_mapper=prompt_mapper,
        reads=["user_input"],
        writes=["response"],
        name="stream_bedrock",
        region=region if region is not None else _aws_region(),
        inference_config={"maxTokens": 512},
    )
    return (
        ApplicationBuilder()
        .with_actions(set_prompt=set_user_input, stream_bedrock=stream)
        .with_transitions(
            ("set_prompt", "stream_bedrock", default),
        )
        .with_state(user_input="", response="")
        .with_entrypoint("set_prompt")
        .build()
    )


def _demo_invoke() -> None:
    app = application()
    _, _, state = app.run(
        halt_after=["invoke_bedrock"],
        inputs={"user_input": "Explain what Burr is in one short sentence."},
    )
    print(state["response"])


def _demo_stream() -> None:
    app = streaming_application()
    _, streaming_result = app.stream_result(
        halt_after=["stream_bedrock"],
        inputs={"user_input": "Count from 1 to 3, separated by commas."},
    )
    for item in streaming_result:
        chunk = item.get("chunk") or ""
        if chunk:
            print(chunk, end="", flush=True)
    print()
    _, state = streaming_result.get()
    print("Final response:", state["response"])


if __name__ == "__main__":
    print("--- BedrockAction (converse) ---")
    _demo_invoke()
    print()
    print("--- BedrockStreamingAction (converse_stream) ---")
    _demo_stream()
