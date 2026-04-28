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

"""Amazon Bedrock integration for Burr.

This module provides Action classes for invoking Amazon Bedrock models
within Burr applications.

Example usage:
    from burr.integrations.bedrock import BedrockAction

    def prompt_mapper(state):
        return {
            "messages": [{"role": "user", "content": [{"text": state["user_input"]}]}],
            "system": [{"text": "You are a helpful assistant."}],
        }

    # With default client (created lazily on first use):
    action = BedrockAction(
        model_id="anthropic.claude-3-sonnet-20240229-v1:0",
        input_mapper=prompt_mapper,
        reads=["user_input"],
        writes=["response"],
    )

    # With injected client (for tests or distributed execution):
    # client = boto3.client("bedrock-runtime", region_name="us-east-1")
    # action = BedrockAction(..., client=client)

If ``guardrail_id`` is set, you must pass an explicit ``guardrail_version``
(including the string ``DRAFT`` if you intend to use the unpublished draft).
"""

import logging
from typing import Any, Generator, Optional, Protocol

from burr.core.action import SingleStepAction, StreamingAction
from burr.core.state import State
from burr.integrations.base import require_plugin

logger = logging.getLogger(__name__)

# Type for injected Bedrock client (avoids boto3 import at type-check time)
BedrockClient = Any

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError as e:
    require_plugin(e, "bedrock")


class StateToPromptMapper(Protocol):
    """Protocol for mapping Burr state to Bedrock prompt format."""

    def __call__(self, state: State) -> dict[str, Any]:
        ...  # noqa: E704


def _text_from_content_blocks(content_blocks: list[Any]) -> str:
    """Join text from every content block (multi-block replies, tool use + text, etc.)."""
    parts: list[str] = []
    for block in content_blocks:
        if isinstance(block, dict) and "text" in block:
            parts.append(block["text"])
    return "\n".join(parts)


def _model_result_for_writes(
    text: str,
    usage: dict[str, Any],
    stop_reason: Any,
    writes: list[str],
) -> dict[str, Any]:
    """Build the result dict and ensure each ``writes`` key maps to the right value."""
    result: dict[str, Any] = {
        "response": text,
        "usage": usage,
        "stop_reason": stop_reason,
    }
    for w in writes:
        if w == "usage":
            result[w] = usage
        elif w == "stop_reason":
            result[w] = stop_reason
        else:
            result[w] = text
    return result


class _BedrockCore:
    """Shared Bedrock client, inference config, and Converse request shape."""

    def __init__(
        self,
        model_id: str,
        input_mapper: StateToPromptMapper,
        reads: list[str],
        writes: list[str],
        name: str,
        region: Optional[str],
        guardrail_id: Optional[str],
        guardrail_version: Optional[str],
        inference_config: Optional[dict[str, Any]],
        max_retries: int,
        client: Optional[BedrockClient],
    ):
        if guardrail_id is not None and guardrail_version is None:
            raise ValueError(
                "guardrail_version is required when guardrail_id is set "
                '(pass an explicit published version, or "DRAFT" for the draft).'
            )
        self._model_id = model_id
        self._input_mapper = input_mapper
        self._reads = reads
        self._writes = writes
        self._name = name
        self._region = region
        self._guardrail_id = guardrail_id
        self._guardrail_version = guardrail_version
        self._inference_config = (
            {"maxTokens": 4096} if inference_config is None else inference_config
        )
        self._max_retries = max_retries
        self._client = client

    @property
    def reads(self) -> list[str]:
        return self._reads

    @property
    def writes(self) -> list[str]:
        return self._writes

    @property
    def name(self) -> str:
        return self._name

    def get_client(self) -> BedrockClient:
        """Return the Bedrock runtime client, creating it lazily if not injected."""
        if self._client is not None:
            return self._client
        config = Config(retries={"max_attempts": self._max_retries, "mode": "adaptive"})
        self._client = boto3.client("bedrock-runtime", region_name=self._region, config=config)
        return self._client

    def build_converse_request(self, state: State) -> dict[str, Any]:
        """Build the kwargs dict for ``converse`` / ``converse_stream`` from current state."""
        prompt = self._input_mapper(state)
        request: dict[str, Any] = {
            "modelId": self._model_id,
            "messages": prompt["messages"],
            "inferenceConfig": self._inference_config,
        }
        if "system" in prompt:
            request["system"] = prompt["system"]
        if self._guardrail_id:
            request["guardrailConfig"] = {
                "guardrailIdentifier": self._guardrail_id,
                "guardrailVersion": self._guardrail_version,
            }
        return request


class _BedrockBase:
    """Shared Bedrock wiring: core state and reads/writes/name for action subclasses."""

    _bedrock: _BedrockCore

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def _init_bedrock_core(
        self,
        model_id: str,
        input_mapper: StateToPromptMapper,
        reads: list[str],
        writes: list[str],
        name: str,
        region: Optional[str],
        guardrail_id: Optional[str],
        guardrail_version: Optional[str],
        inference_config: Optional[dict[str, Any]],
        max_retries: int,
        client: Optional[BedrockClient],
    ) -> None:
        self._bedrock = _BedrockCore(
            model_id=model_id,
            input_mapper=input_mapper,
            reads=reads,
            writes=writes,
            name=name,
            region=region,
            guardrail_id=guardrail_id,
            guardrail_version=guardrail_version,
            inference_config=inference_config,
            max_retries=max_retries,
            client=client,
        )

    @property
    def reads(self) -> list[str]:
        return self._bedrock.reads

    @property
    def writes(self) -> list[str]:
        return self._bedrock.writes

    @property
    def name(self) -> str:
        return self._bedrock.name


class BedrockAction(_BedrockBase, SingleStepAction):
    """Action that invokes Amazon Bedrock models using the Converse API.

    :param model_id: Bedrock model identifier (e.g. Anthropic Claude on Bedrock).
    :param input_mapper: Callable mapping :class:`~burr.core.state.State` to Bedrock
        ``messages`` / optional ``system`` keys.
    :param reads: State keys this action reads.
    :param writes: State keys to update (typically include ``response``).
    :param name: Action name for the graph.
    :param region: AWS region for the Bedrock runtime client (optional).
    :param guardrail_id: If set, ``guardrail_version`` must also be set explicitly.
    :param guardrail_version: Guardrail version string (use ``DRAFT`` only when intended).
    :param inference_config: Passed as ``inferenceConfig``; if omitted, defaults to
        a ``maxTokens`` limit. Pass an empty dict explicitly to send an empty config.
    :param max_retries: Botocore retry configuration for the runtime client.
    :param client: Optional pre-built ``bedrock-runtime`` client (for tests or injection).

    Use :meth:`run_and_update` to run the model and merge outputs into state.
    """

    def __init__(
        self,
        model_id: str,
        input_mapper: StateToPromptMapper,
        reads: list[str],
        writes: list[str],
        name: str = "bedrock_invoke",
        region: Optional[str] = None,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        inference_config: Optional[dict[str, Any]] = None,
        max_retries: int = 3,
        client: Optional[BedrockClient] = None,
    ):
        super().__init__()
        self._init_bedrock_core(
            model_id=model_id,
            input_mapper=input_mapper,
            reads=reads,
            writes=writes,
            name=name,
            region=region,
            guardrail_id=guardrail_id,
            guardrail_version=guardrail_version,
            inference_config=inference_config,
            max_retries=max_retries,
            client=client,
        )

    def run_and_update(self, state: State, **run_kwargs) -> tuple[dict, State]:
        request = self._bedrock.build_converse_request(state)

        try:
            response = self._bedrock.get_client().converse(**request)
        except ClientError as e:
            logger.error("Bedrock API error: %s", e)
            raise

        output_message = response["output"]["message"]
        content_blocks = output_message.get("content", [])
        text = _text_from_content_blocks(content_blocks)

        result = _model_result_for_writes(
            text,
            response.get("usage", {}),
            response.get("stopReason"),
            self._bedrock.writes,
        )

        updates = {key: result[key] for key in self._bedrock.writes if key in result}
        new_state = state.update(**updates)

        return result, new_state


class BedrockStreamingAction(_BedrockBase, StreamingAction):
    """Streaming Bedrock action using the Converse Stream API.

    Parameters match :class:`BedrockAction` except the default ``name`` is
    ``bedrock_stream``. Yields chunk dicts from :meth:`stream_run` and merges the
    final response in :meth:`update`.
    """

    def __init__(
        self,
        model_id: str,
        input_mapper: StateToPromptMapper,
        reads: list[str],
        writes: list[str],
        name: str = "bedrock_stream",
        region: Optional[str] = None,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        inference_config: Optional[dict[str, Any]] = None,
        max_retries: int = 3,
        client: Optional[BedrockClient] = None,
    ):
        super().__init__()
        self._init_bedrock_core(
            model_id=model_id,
            input_mapper=input_mapper,
            reads=reads,
            writes=writes,
            name=name,
            region=region,
            guardrail_id=guardrail_id,
            guardrail_version=guardrail_version,
            inference_config=inference_config,
            max_retries=max_retries,
            client=client,
        )

    def stream_run(self, state: State, **run_kwargs) -> Generator[dict, None, None]:
        request = self._bedrock.build_converse_request(state)

        try:
            response = self._bedrock.get_client().converse_stream(**request)
        except ClientError as e:
            logger.error("Bedrock streaming API error: %s", e)
            raise

        text_parts: list[str] = []
        stream = response.get("stream", [])
        for event in stream:
            if "contentBlockDelta" in event:
                chunk = event["contentBlockDelta"]["delta"].get("text", "")
                text_parts.append(chunk)
                full_response = "".join(text_parts)
                yield {"chunk": chunk, "response": full_response}

        full_text = "".join(text_parts)
        payload = _model_result_for_writes(full_text, {}, None, self._bedrock.writes)
        yield {"chunk": "", "complete": True, **payload}

    def update(self, result: dict, state: State) -> State:
        if result.get("complete"):
            updates = {key: result[key] for key in self._bedrock.writes if key in result}
            return state.update(**updates)
        return state
