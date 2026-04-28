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
from botocore.exceptions import ClientError

from burr.core.action import SingleStepAction, StreamingAction
from burr.core.state import State

boto3 = pytest.importorskip("boto3", reason="boto3 required for Bedrock tests")
import burr.integrations as integrations
from burr.integrations import bedrock
from burr.integrations.bedrock import BedrockAction, BedrockStreamingAction, StateToPromptMapper


class TestBedrockImports:
    """Test Bedrock import paths."""

    def test_import_bedrock_module_from_integrations(self):
        """Verify `from burr.integrations import bedrock` works."""
        assert bedrock is not None

    def test_bedrock_module_has_expected_classes(self):
        assert hasattr(bedrock, "BedrockAction")
        assert hasattr(bedrock, "BedrockStreamingAction")

    def test_direct_import_bedrock_module(self):
        """Verify bedrock.py module exists and has expected classes."""
        assert BedrockAction is not None
        assert BedrockStreamingAction is not None
        assert StateToPromptMapper is not None


class TestBedrockGuardrailValidation:
    """guardrail_id requires an explicit guardrail_version."""

    def test_raises_when_guardrail_id_without_version(self):
        with pytest.raises(ValueError, match="guardrail_version is required"):
            BedrockAction(
                model_id="test-model",
                input_mapper=lambda s: {"messages": []},
                reads=[],
                writes=["response"],
                guardrail_id="gr-123",
            )

    def test_accepts_explicit_draft_version(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "ok"}]}},
            "usage": {},
            "stopReason": "end_turn",
        }
        action = BedrockAction(
            model_id="test-model",
            input_mapper=lambda s: {"messages": [{"role": "user", "content": "hi"}]},
            reads=[],
            writes=["response"],
            guardrail_id="gr-123",
            guardrail_version="DRAFT",
            client=mock_client,
        )
        action.run_and_update({})
        call_kw = mock_client.converse.call_args[1]
        assert call_kw["guardrailConfig"]["guardrailVersion"] == "DRAFT"


class TestBedrockActionInterface:
    """Test BedrockAction class interface with mocked boto3."""

    def test_bedrock_action_extends_single_step_action(self):
        """Verify BedrockAction extends SingleStepAction."""
        assert issubclass(BedrockAction, SingleStepAction)

    def test_bedrock_streaming_action_extends_streaming_action(self):
        """Verify BedrockStreamingAction extends StreamingAction."""
        assert issubclass(BedrockStreamingAction, StreamingAction)

    def test_bedrock_action_has_required_properties(self):
        """Verify BedrockAction has reads, writes, name properties."""
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

    def test_empty_inference_config_passed_through(self):
        """inference_config={} must not be replaced by defaults (falsy dict bug)."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "x"}]}},
            "usage": {},
            "stopReason": "end_turn",
        }
        action = BedrockAction(
            model_id="test-model",
            input_mapper=lambda s: {"messages": [{"role": "user", "content": "hi"}]},
            reads=[],
            writes=["response"],
            inference_config={},
            client=mock_client,
        )
        action.run_and_update({})
        call_kw = mock_client.converse.call_args[1]
        assert call_kw["inferenceConfig"] == {}

    def test_default_inference_config_when_omitted(self):
        """When inference_config is None, Bedrock receives default maxTokens."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "ok"}]}},
            "usage": {},
            "stopReason": "end_turn",
        }
        action = BedrockAction(
            model_id="mid-1",
            input_mapper=lambda s: {"messages": [{"role": "user", "content": "hi"}]},
            reads=[],
            writes=["response"],
            client=mock_client,
        )
        action.run_and_update({})
        assert mock_client.converse.call_args[1]["inferenceConfig"] == {"maxTokens": 4096}

    def test_converse_request_includes_model_id_and_system(self):
        """Request passes modelId, messages, and optional system from input_mapper."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "x"}]}},
            "usage": {},
            "stopReason": "end_turn",
        }

        def mapper(s):
            return {
                "messages": [{"role": "user", "content": "hello"}],
                "system": [{"text": "You are concise."}],
            }

        action = BedrockAction(
            model_id="anthropic.claude-v2",
            input_mapper=mapper,
            reads=[],
            writes=["response"],
            client=mock_client,
        )
        action.run_and_update({})
        kw = mock_client.converse.call_args[1]
        assert kw["modelId"] == "anthropic.claude-v2"
        assert kw["messages"][0]["content"] == "hello"
        assert kw["system"] == [{"text": "You are concise."}]

    def test_empty_content_blocks_return_empty_string(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": []}},
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
        assert result["response"] == ""

    def test_multiple_text_blocks_joined_with_newline(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {"text": "first"},
                        {"text": "second"},
                    ]
                }
            },
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
        assert result["response"] == "first\nsecond"

    def test_custom_write_key_updates_state(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "hello"}]}},
            "usage": {},
            "stopReason": "end_turn",
        }
        action = BedrockAction(
            model_id="test-model",
            input_mapper=lambda s: {"messages": [{"role": "user", "content": "hi"}]},
            reads=[],
            writes=["answer"],
            client=mock_client,
        )
        _, new_state = action.run_and_update(State({}))
        assert new_state.get("answer") == "hello"

    def test_client_error_from_converse_propagates(self):
        err = ClientError({"Error": {"Code": "ValidationException", "Message": "bad"}}, "Converse")
        mock_client = MagicMock()
        mock_client.converse.side_effect = err

        action = BedrockAction(
            model_id="test-model",
            input_mapper=lambda s: {"messages": [{"role": "user", "content": "hi"}]},
            reads=[],
            writes=["response"],
            client=mock_client,
        )
        with pytest.raises(ClientError):
            action.run_and_update({})


class TestBedrockStreamingActionInterface:
    """Test BedrockStreamingAction class interface with mocked boto3."""

    def test_bedrock_streaming_action_uses_injected_client(self):
        """Verify BedrockStreamingAction uses injected client when provided."""
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

    def test_streaming_guardrail_requires_version(self):
        with pytest.raises(ValueError, match="guardrail_version is required"):
            BedrockStreamingAction(
                model_id="test-model",
                input_mapper=lambda s: {"messages": []},
                reads=[],
                writes=["response"],
                guardrail_id="gr-1",
            )

    def test_streaming_update_only_merges_on_complete(self):
        """Non-final chunks should not update state via update()."""
        action = BedrockStreamingAction(
            model_id="test-model",
            input_mapper=lambda s: {"messages": []},
            reads=[],
            writes=["response"],
        )
        s0 = State({"response": "old"})
        s1 = action.update({"chunk": "a", "response": "partial"}, s0)
        assert s1.get("response") == "old"
        s2 = action.update({"complete": True, "response": "final"}, s0)
        assert s2.get("response") == "final"

    def test_streaming_custom_write_key_updates_state(self):
        action = BedrockStreamingAction(
            model_id="test-model",
            input_mapper=lambda s: {"messages": []},
            reads=[],
            writes=["answer"],
        )
        s0 = State({})
        final = {
            "chunk": "",
            "complete": True,
            "response": "done",
            "usage": {},
            "stop_reason": None,
            "answer": "done",
        }
        s1 = action.update(final, s0)
        assert s1.get("answer") == "done"


class TestStateToPromptMapperProtocol:
    """Test StateToPromptMapper Protocol exists."""

    def test_protocol_exists(self):
        """Verify StateToPromptMapper Protocol is defined."""
        assert StateToPromptMapper is not None


class TestIntegrationsLazyExports:
    def test_unknown_attribute_raises(self):
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = integrations.NotARealBedrockClass  # noqa: SLF001
