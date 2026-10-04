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

import contextvars
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pydantic
import pytest
from opentelemetry import context as otel_context
from opentelemetry.sdk.trace import Span, TracerProvider
from opentelemetry.trace import SpanContext

from burr.core import State, serde
from burr.core.action import Action
from burr.integrations.opentelemetry import (
    BurrTrackingSpanProcessor,
    FullSpanContext,
    OpenTelemetryTracker,
    convert_to_otel_attribute,
    span_map,
    tracker_context,
)
from burr.tracking.base import SyncTrackingClient
from burr.visibility import ActionSpan


class SampleModel(pydantic.BaseModel):
    foo: int
    bar: bool


@pytest.fixture(autouse=True)
def clear_span_map():
    """span_map is module-global, so keep a failing test from leaking entries into the next one."""
    span_map.clear()
    yield
    span_map.clear()


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
        mock_parent_context.tracker = None
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
        mock_cached_span.tracker = None
        mock_get_cached.return_value = mock_cached_span

        # Mock uncache_span
        with patch("burr.integrations.opentelemetry.uncache_span") as mock_uncache:
            # Set tracker_context to None (simulating no tracker in context)
            token = tracker_context.set(None)
            try:
                # This should not raise an error even though tracker is None
                processor.on_end(mock_span)
            finally:
                tracker_context.reset(token)
            # The span is still removed from the cache when no tracker is found
            mock_uncache.assert_called_once_with(mock_span)


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


def _tracker_with_local_provider():
    provider = TracerProvider()
    provider.add_span_processor(BurrTrackingSpanProcessor())
    tracer = provider.get_tracer("test")
    burr_tracker = Mock(spec=SyncTrackingClient)
    with patch("burr.integrations.opentelemetry.initialize_tracer"):
        otel_tracker = OpenTelemetryTracker(burr_tracker=burr_tracker)
    otel_tracker.tracer = tracer
    action = Mock(spec=Action)
    action.name = "work"
    return tracer, burr_tracker, otel_tracker, action


def _pre_run_step(otel_tracker, action):
    otel_tracker.pre_run_step(
        app_id="test_app",
        partition_key="test_partition",
        sequence_id=0,
        state=State({}),
        action=action,
        inputs={},
    )


def _post_run_step(otel_tracker, action):
    otel_tracker.post_run_step(
        app_id="test_app",
        partition_key="test_partition",
        sequence_id=0,
        state=State({}),
        action=action,
        result={},
        exception=None,
    )


@pytest.mark.parametrize("on_worker_thread", [False, True])
def test_burr_tracking_span_processor_child_span_reaches_tracker_and_is_uncached(on_worker_thread):
    """Spans started inside an action are logged to the Burr tracker and removed from the span
    cache, whether they end on the action's thread or on a worker thread that only carries the
    OpenTelemetry context (thread pools don't copy context vars, so tracker_context is unset there).
    """
    tracer, burr_tracker, otel_tracker, action = _tracker_with_local_provider()
    child_span_ids = []

    def child():
        with tracer.start_as_current_span("llm_call") as span:
            span.set_attribute("model", "test-model")
            child_span_ids.append(span.get_span_context().span_id)
            assert child_span_ids[-1] in span_map

    def run_step():
        _pre_run_step(otel_tracker, action)
        if on_worker_thread:
            ctx = otel_context.get_current()

            def run_with_otel_context():
                token = otel_context.attach(ctx)
                try:
                    child()
                finally:
                    otel_context.detach(token)

            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(run_with_otel_context).result()
        else:
            child()
        _post_run_step(otel_tracker, action)

    contextvars.copy_context().run(run_step)

    assert len(child_span_ids) == 1
    assert child_span_ids[0] not in span_map
    assert len(span_map) == 0
    burr_tracker.pre_start_span.assert_called_once()
    assert burr_tracker.pre_start_span.call_args.kwargs["span"].name == "llm_call"
    # one for the child span, one for the action span itself
    assert burr_tracker.post_end_span.call_count == 2
    burr_tracker.do_log_attributes.assert_called_once()
    assert burr_tracker.do_log_attributes.call_args.kwargs["attributes"] == {"model": "test-model"}


def test_burr_tracking_span_processor_child_span_ending_after_step_is_uncached():
    """A span started during an action but ended after post_run_step (which clears
    tracker_context) is still logged to the owning tracker and removed from the span cache."""
    tracer, burr_tracker, otel_tracker, action = _tracker_with_local_provider()

    def run_step():
        _pre_run_step(otel_tracker, action)
        span = tracer.start_span("background_call")
        _post_run_step(otel_tracker, action)
        assert tracker_context.get() is None
        span.end()
        return span.get_span_context().span_id

    span_id = contextvars.copy_context().run(run_step)

    assert span_id not in span_map
    assert len(span_map) == 0
    assert burr_tracker.post_end_span.call_args.kwargs["span"].name == "background_call"


def test_burr_tracking_span_processor_uncaches_span_when_tracker_raises():
    """A failing tracker callback in on_end must not leave the span in the cache."""
    tracer, burr_tracker, otel_tracker, action = _tracker_with_local_provider()
    burr_tracker.post_end_span.side_effect = RuntimeError("tracker failed")
    span_ids = []

    def run_step():
        _pre_run_step(otel_tracker, action)
        span = tracer.start_span("llm_call")
        span_ids.append(span.get_span_context().span_id)
        with pytest.raises(RuntimeError, match="tracker failed"):
            span.end()
        burr_tracker.post_end_span.side_effect = None
        _post_run_step(otel_tracker, action)

    contextvars.copy_context().run(run_step)

    assert span_ids[0] not in span_map
    assert len(span_map) == 0
