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

BIP-0042: This module provides Action classes for invoking Amazon Bedrock models
within Burr applications.

Example usage:
    from burr.integrations.bedrock import BedrockAction

    def prompt_mapper(state):
        return {
            "messages": [{"role": "user", "content": state["user_input"]}],
            "system": [{"text": "You are a helpful assistant."}],
        }

    action = BedrockAction(
        model_id="anthropic.claude-3-sonnet-20240229-v1:0",
        input_mapper=prompt_mapper,
        reads=["user_input"],
        writes=["response"],
    )
"""

import logging
from typing import Any, Dict, Generator, List, Optional, Protocol, Tuple

from burr.core.action import SingleStepAction, StreamingAction
from burr.core.state import State
from burr.integrations.base import require_plugin

logger = logging.getLogger(__name__)

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError as e:
    require_plugin(e, "bedrock")


class StateToPromptMapper(Protocol):
    """Protocol for mapping Burr state to Bedrock prompt format."""

    def __call__(self, state: State) -> Dict[str, Any]:
        ...


class BedrockAction(SingleStepAction):
    """Action that invokes Amazon Bedrock models using the Converse API."""

    def __init__(
        self,
        model_id: str,
        input_mapper: StateToPromptMapper,
        reads: List[str],
        writes: List[str],
        name: str = "bedrock_invoke",
        region: Optional[str] = None,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        inference_config: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ):
        super().__init__()
        self._model_id = model_id
        self._input_mapper = input_mapper
        self._reads = reads
        self._writes = writes
        self._name = name
        self._region = region
        self._guardrail_id = guardrail_id
        self._guardrail_version = guardrail_version or "DRAFT"
        self._inference_config = inference_config or {"maxTokens": 4096}

        config = Config(retries={"max_attempts": max_retries, "mode": "adaptive"})
        self._client = boto3.client("bedrock-runtime", region_name=region, config=config)

    @property
    def reads(self) -> List[str]:
        return self._reads

    @property
    def writes(self) -> List[str]:
        return self._writes

    @property
    def name(self) -> str:
        return self._name

    def run_and_update(self, state: State, **run_kwargs) -> Tuple[dict, State]:
        prompt = self._input_mapper(state)

        request: Dict[str, Any] = {
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

        try:
            response = self._client.converse(**request)
        except ClientError as e:
            logger.error(f"Bedrock API error: {e}")
            raise

        output_message = response["output"]["message"]
        content_blocks = output_message.get("content", [])
        text = content_blocks[0]["text"] if content_blocks else ""

        result: Dict[str, Any] = {
            "response": text,
            "usage": response.get("usage", {}),
            "stop_reason": response.get("stopReason"),
        }

        updates = {key: result[key] for key in self._writes if key in result}
        new_state = state.update(**updates)

        return result, new_state


class BedrockStreamingAction(StreamingAction):
    """Streaming variant of BedrockAction using Converse Stream API."""

    def __init__(
        self,
        model_id: str,
        input_mapper: StateToPromptMapper,
        reads: List[str],
        writes: List[str],
        name: str = "bedrock_stream",
        region: Optional[str] = None,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        inference_config: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ):
        super().__init__()
        self._model_id = model_id
        self._input_mapper = input_mapper
        self._reads = reads
        self._writes = writes
        self._name = name
        self._region = region
        self._guardrail_id = guardrail_id
        self._guardrail_version = guardrail_version or "DRAFT"
        self._inference_config = inference_config or {"maxTokens": 4096}

        config = Config(retries={"max_attempts": max_retries, "mode": "adaptive"})
        self._client = boto3.client("bedrock-runtime", region_name=region, config=config)

    @property
    def reads(self) -> List[str]:
        return self._reads

    @property
    def writes(self) -> List[str]:
        return self._writes

    @property
    def name(self) -> str:
        return self._name

    def stream_run(self, state: State, **run_kwargs) -> Generator[dict, None, None]:
        prompt = self._input_mapper(state)

        request: Dict[str, Any] = {
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

        try:
            response = self._client.converse_stream(**request)
        except ClientError as e:
            logger.error(f"Bedrock streaming API error: {e}")
            raise

        full_response = ""
        stream = response.get("stream", [])
        for event in stream:
            if "contentBlockDelta" in event:
                chunk = event["contentBlockDelta"]["delta"].get("text", "")
                full_response += chunk
                yield {"chunk": chunk, "response": full_response}

        yield {"chunk": "", "response": full_response, "complete": True}

    def update(self, result: dict, state: State) -> State:
        if result.get("complete"):
            updates = {"response": result.get("response", "")}
            filtered = {k: v for k, v in updates.items() if k in self._writes}
            return state.update(**filtered)
        return state
