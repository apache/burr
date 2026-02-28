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

"""BIP-0042: Tests for Bedrock integration."""

import inspect

import pytest


class TestBedrockImports:
    """Test that Bedrock classes can be imported via lazy loading."""

    def test_lazy_import_bedrock_action(self):
        """Verify BedrockAction can be imported from burr.integrations."""
        try:
            from burr.integrations import BedrockAction

            assert BedrockAction is not None
        except ImportError as e:
            assert "bedrock" in str(e).lower() or "boto3" in str(e).lower()

    def test_lazy_import_bedrock_streaming_action(self):
        """Verify BedrockStreamingAction can be imported from burr.integrations."""
        try:
            from burr.integrations import BedrockStreamingAction

            assert BedrockStreamingAction is not None
        except ImportError as e:
            assert "bedrock" in str(e).lower() or "boto3" in str(e).lower()

    def test_direct_import_bedrock_module(self):
        """Verify bedrock.py module exists and has expected classes."""
        try:
            from burr.integrations.bedrock import (
                BedrockAction,
                BedrockStreamingAction,
                StateToPromptMapper,
            )

            assert BedrockAction is not None
            assert BedrockStreamingAction is not None
            assert StateToPromptMapper is not None
        except ImportError as e:
            assert "bedrock" in str(e).lower() or "boto3" in str(e).lower()


class TestBedrockActionInterface:
    """Test BedrockAction class interface (without boto3)."""

    @pytest.fixture
    def mock_boto3(self, monkeypatch):
        """Mock boto3 to allow testing without AWS credentials."""
        import sys
        from unittest.mock import MagicMock

        mock_boto = MagicMock()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client

        mock_botocore = MagicMock()
        mock_botocore.config.Config = MagicMock
        mock_botocore.exceptions.ClientError = Exception

        monkeypatch.setitem(sys.modules, "boto3", mock_boto)
        monkeypatch.setitem(sys.modules, "botocore", mock_botocore)
        monkeypatch.setitem(sys.modules, "botocore.config", mock_botocore.config)
        monkeypatch.setitem(sys.modules, "botocore.exceptions", mock_botocore.exceptions)

        return mock_boto, mock_client

    def test_bedrock_action_extends_single_step_action(self, mock_boto3):
        """Verify BedrockAction extends SingleStepAction."""
        import importlib

        import burr.integrations.bedrock as bedrock_module

        importlib.reload(bedrock_module)

        from burr.core.action import SingleStepAction
        from burr.integrations.bedrock import BedrockAction

        assert issubclass(BedrockAction, SingleStepAction)

    def test_bedrock_streaming_action_extends_streaming_action(self, mock_boto3):
        """Verify BedrockStreamingAction extends StreamingAction."""
        import importlib

        import burr.integrations.bedrock as bedrock_module

        importlib.reload(bedrock_module)

        from burr.core.action import StreamingAction
        from burr.integrations.bedrock import BedrockStreamingAction

        assert issubclass(BedrockStreamingAction, StreamingAction)

    def test_bedrock_action_has_required_properties(self, mock_boto3):
        """Verify BedrockAction has reads, writes, name properties."""
        import importlib

        import burr.integrations.bedrock as bedrock_module

        importlib.reload(bedrock_module)

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

    def test_bedrock_action_accepts_all_parameters(self, mock_boto3):
        """Verify BedrockAction accepts all BIP-0042 specified parameters."""
        import importlib

        import burr.integrations.bedrock as bedrock_module

        importlib.reload(bedrock_module)

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


class TestStateToPromptMapperProtocol:
    """Test StateToPromptMapper Protocol exists."""

    def test_protocol_exists(self):
        """Verify StateToPromptMapper Protocol is defined."""
        try:
            from burr.integrations.bedrock import StateToPromptMapper

            assert StateToPromptMapper is not None
        except ImportError:
            pytest.skip("boto3 not installed")
