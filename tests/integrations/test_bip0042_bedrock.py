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

"""Tests for Bedrock integration."""

import inspect
from unittest.mock import MagicMock

import pytest

boto3 = pytest.importorskip("boto3", reason="boto3 required for Bedrock tests")


class TestBedrockImports:
    """Test that Bedrock classes can be imported via lazy loading."""

    def test_lazy_import_bedrock_action(self):
        """Verify BedrockAction can be imported from burr.integrations."""
        from burr.integrations import BedrockAction

        assert BedrockAction is not None

    def test_lazy_import_bedrock_streaming_action(self):
        """Verify BedrockStreamingAction can be imported from burr.integrations."""
        from burr.integrations import BedrockStreamingAction

        assert BedrockStreamingAction is not None

    def test_direct_import_bedrock_module(self):
        """Verify bedrock.py module exists and has expected classes."""
        from burr.integrations.bedrock import (
            BedrockAction,
            BedrockStreamingAction,
            StateToPromptMapper,
        )

        assert BedrockAction is not None
        assert BedrockStreamingAction is not None
        assert StateToPromptMapper is not None


class TestBedrockActionInterface:
    """Test BedrockAction class interface with mocked boto3."""

    def test_bedrock_action_extends_single_step_action(self):
        """Verify BedrockAction extends SingleStepAction."""
        from burr.core.action import SingleStepAction
        from burr.integrations.bedrock import BedrockAction

        assert issubclass(BedrockAction, SingleStepAction)

    def test_bedrock_streaming_action_extends_streaming_action(self):
        """Verify BedrockStreamingAction extends StreamingAction."""
        from burr.core.action import StreamingAction
        from burr.integrations.bedrock import BedrockStreamingAction

        assert issubclass(BedrockStreamingAction, StreamingAction)

    def test_bedrock_action_has_required_properties(self):
        """Verify BedrockAction has reads, writes, name properties."""
        from burr.integrations.bedrock import BedrockAction

        action = BedrockAction(
            model_id="test-model",
            input_mapper=lambda s: {"messages": []},
            reads=["input"],
            writes=["output"],
        )
        assert action.reads == ["input"]
        assert action.writes == ["output"]
        assert action.name == "bedrock_invoke"

    def test_bedrock_action_accepts_all_parameters(self):
        """Verify BedrockAction accepts all specified parameters."""
        from burr.integrations.bedrock import BedrockAction

        sig = inspect.signature(BedrockAction.__init__)
        params = list(sig.parameters.keys())
        assert "model_id" in params
        assert "input_mapper" in params
        assert "reads" in params
        assert "writes" in params
        assert "name" in params
        assert "region" in params
        assert "guardrail_id" in params
        assert "guardrail_version" in params
        assert "inference_config" in params
        assert "max_retries" in params
        assert "client" in params

    def test_bedrock_action_uses_injected_client(self):
        """Verify BedrockAction uses injected client when provided."""
        from burr.integrations.bedrock import BedrockAction

        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "hi"}]}},
            "usage": {},
            "stopReason": "end_turn",
        }

        action = BedrockAction(
            model_id="test-model",
            input_mapper=lambda s: {"messages": [{"role": "user", "content": "hi"}]},
            reads=[],
            writes=["response"],
            client=mock_client,
        )

        result, _ = action.run_and_update({})
        assert result["response"] == "hi"
        mock_client.converse.assert_called_once()


class TestBedrockStreamingActionInterface:
    """Test BedrockStreamingAction class interface with mocked boto3."""

    def test_bedrock_streaming_action_uses_injected_client(self):
        """Verify BedrockStreamingAction uses injected client when provided."""
        from burr.integrations.bedrock import BedrockStreamingAction

        mock_client = MagicMock()
        mock_client.converse_stream.return_value = {
            "stream": [
                {"contentBlockDelta": {"delta": {"text": "hello "}}},
                {"contentBlockDelta": {"delta": {"text": "world"}}},
            ]
        }

        action = BedrockStreamingAction(
            model_id="test-model",
            input_mapper=lambda s: {"messages": [{"role": "user", "content": "hi"}]},
            reads=[],
            writes=["response"],
            client=mock_client,
        )

        chunks = list(action.stream_run({}))
        assert len(chunks) == 3  # 2 content chunks + 1 complete
        assert chunks[0]["chunk"] == "hello "
        assert chunks[1]["chunk"] == "world"
        assert chunks[2]["complete"] is True
        assert chunks[2]["response"] == "hello world"
        mock_client.converse_stream.assert_called_once()


class TestStateToPromptMapperProtocol:
    """Test StateToPromptMapper Protocol exists."""

    def test_protocol_exists(self):
        """Verify StateToPromptMapper Protocol is defined."""
        from burr.integrations.bedrock import StateToPromptMapper

        assert StateToPromptMapper is not None
