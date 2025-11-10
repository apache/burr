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

import json
from unittest.mock import Mock, patch

import pydantic
import pytest
from opentelemetry.sdk.trace import Span
from opentelemetry.trace import SpanContext

from burr.core import serde
from burr.integrations.opentelemetry import (
    BurrTrackingSpanProcessor,
    FullSpanContext,
    convert_to_otel_attribute,
    tracker_context,
)
from burr.tracking.base import SyncTrackingClient
from burr.visibility import ActionSpan


class SampleModel(pydantic.BaseModel):
    foo: int
    bar: bool


@pytest.mark.parametrize(
    "value, expected",
    [
        ("hello", "hello"),
        (1, 1),
        ((1, 1), [1, 1]),
        ((1.0, 1.0), [1.0, 1.0]),
        ((True, True), [True, True]),
        (("hello", "hello"), ["hello", "hello"]),
        (SampleModel(foo=1, bar=True), json.dumps(serde.serialize(SampleModel(foo=1, bar=True)))),
    ],
)
def test_convert_to_otel_attribute(value, expected):
    assert convert_to_otel_attribute(value) == expected


def test_burr_tracking_span_processor_on_start_with_none_tracker():
    """Test that on_start handles None tracker gracefully without raising an error."""
    processor = BurrTrackingSpanProcessor()

    # Mock a span with a parent
    mock_span = Mock(spec=Span)
    mock_span.parent = Mock()
    mock_span.parent.span_id = 12345
    mock_span.name = "test_span"

    # Mock the get_cached_span to return a parent span context
    with patch("burr.integrations.opentelemetry.get_cached_span") as mock_get_cached:
        mock_parent_context = Mock(spec=FullSpanContext)
        mock_parent_context.action_span = Mock(spec=ActionSpan)
        mock_spawned_span = Mock(spec=ActionSpan)
        mock_parent_context.action_span.spawn = Mock(return_value=mock_spawned_span)
        mock_parent_context.partition_key = "test_partition"
        mock_parent_context.app_id = "test_app"
        mock_get_cached.return_value = mock_parent_context

        # Mock cache_span
        with patch("burr.integrations.opentelemetry.cache_span"):
            # Set tracker_context to None (simulating no tracker in context)
            token = tracker_context.set(None)
            try:
                # This should not raise an error even though tracker is None
                processor.on_start(mock_span, parent_context=None)
            finally:
                tracker_context.reset(token)


def test_burr_tracking_span_processor_on_end_with_none_tracker():
    """Test that on_end handles None tracker gracefully without raising an error."""
    processor = BurrTrackingSpanProcessor()

    # Mock a span
    mock_span = Mock(spec=Span)
    mock_span_context = Mock(spec=SpanContext)
    mock_span_context.span_id = 67890
    mock_span.get_span_context = Mock(return_value=mock_span_context)
    mock_span.attributes = {}

    # Mock the get_cached_span to return a cached span
    with patch("burr.integrations.opentelemetry.get_cached_span") as mock_get_cached:
        mock_cached_span = Mock(spec=FullSpanContext)
        mock_cached_span.action_span = Mock(spec=ActionSpan)
        mock_cached_span.action_span.action = "test_action"
        mock_cached_span.action_span.action_sequence_id = 1
        mock_cached_span.app_id = "test_app"
        mock_cached_span.partition_key = "test_partition"
        mock_get_cached.return_value = mock_cached_span

        # Mock uncache_span
        with patch("burr.integrations.opentelemetry.uncache_span"):
            # Set tracker_context to None (simulating no tracker in context)
            token = tracker_context.set(None)
            try:
                # This should not raise an error even though tracker is None
                processor.on_end(mock_span)
            finally:
                tracker_context.reset(token)


def test_burr_tracking_span_processor_on_start_with_valid_tracker():
    """Test that on_start calls tracker methods when tracker is available."""
    processor = BurrTrackingSpanProcessor()

    # Mock a span with a parent
    mock_span = Mock(spec=Span)
    mock_span.parent = Mock()
    mock_span.parent.span_id = 12345
    mock_span.name = "test_span"

    # Mock tracker
    mock_tracker = Mock(spec=SyncTrackingClient)

    # Mock the get_cached_span to return a parent span context
    with patch("burr.integrations.opentelemetry.get_cached_span") as mock_get_cached:
        mock_parent_context = Mock(spec=FullSpanContext)
        mock_parent_action_span = Mock(spec=ActionSpan)
        mock_spawned_span = Mock(spec=ActionSpan)
        mock_spawned_span.action = "test_action"
        mock_spawned_span.action_sequence_id = 1
        mock_parent_action_span.spawn = Mock(return_value=mock_spawned_span)
        mock_parent_context.action_span = mock_parent_action_span
        mock_parent_context.partition_key = "test_partition"
        mock_parent_context.app_id = "test_app"
        mock_get_cached.return_value = mock_parent_context

        # Mock cache_span
        with patch("burr.integrations.opentelemetry.cache_span"):
            # Set tracker_context to a valid tracker
            token = tracker_context.set(mock_tracker)
            try:
                processor.on_start(mock_span, parent_context=None)

                # Verify that pre_start_span was called on the tracker
                assert mock_tracker.pre_start_span.called
            finally:
                tracker_context.reset(token)


def test_burr_tracking_span_processor_on_end_with_valid_tracker():
    """Test that on_end calls tracker methods when tracker is available."""
    processor = BurrTrackingSpanProcessor()

    # Mock a span
    mock_span = Mock(spec=Span)
    mock_span_context = Mock(spec=SpanContext)
    mock_span_context.span_id = 67890
    mock_span.get_span_context = Mock(return_value=mock_span_context)
    mock_span.attributes = {}

    # Mock tracker
    mock_tracker = Mock(spec=SyncTrackingClient)

    # Mock the get_cached_span to return a cached span
    with patch("burr.integrations.opentelemetry.get_cached_span") as mock_get_cached:
        mock_cached_span = Mock(spec=FullSpanContext)
        mock_cached_span.action_span = Mock(spec=ActionSpan)
        mock_cached_span.action_span.action = "test_action"
        mock_cached_span.action_span.action_sequence_id = 1
        mock_cached_span.app_id = "test_app"
        mock_cached_span.partition_key = "test_partition"
        mock_get_cached.return_value = mock_cached_span

        # Mock uncache_span
        with patch("burr.integrations.opentelemetry.uncache_span"):
            # Set tracker_context to a valid tracker
            token = tracker_context.set(mock_tracker)
            try:
                processor.on_end(mock_span)

                # Verify that post_end_span was called on the tracker
                assert mock_tracker.post_end_span.called
            finally:
                tracker_context.reset(token)
