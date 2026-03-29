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

"""BIP-0042: Tests for S3 buffering, settings, and SQS message parsing."""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("aiobotocore")

from burr.tracking.server.backend import EventDrivenBackendMixin
from burr.tracking.server.s3.backend import (
    S3Settings,
    SQLiteS3Backend,
    TrackingMode,
    _parse_sqs_message_events,
    _query_s3_file,
)


def _minimal_backend(**kwargs):
    defaults = dict(
        s3_bucket="test-bucket",
        update_interval_milliseconds=60_000,
        aws_max_concurrency=10,
        snapshot_interval_milliseconds=3_600_000,
        load_snapshot_on_start=False,
        prior_snapshots_to_keep=1,
        tracking_mode=TrackingMode.POLLING,
        sqs_queue_url=None,
        sqs_region=None,
    )
    defaults.update(kwargs)
    return SQLiteS3Backend(**defaults)


class TestS3Settings:
    """S3Settings BIP-0042 fields and coercion."""

    def test_s3_settings_has_tracking_mode(self):
        assert "tracking_mode" in S3Settings.model_fields
        assert S3Settings.model_fields["tracking_mode"].default == TrackingMode.POLLING

    def test_s3_settings_has_sqs_queue_url(self):
        assert "sqs_queue_url" in S3Settings.model_fields
        assert S3Settings.model_fields["sqs_queue_url"].default is None

    def test_s3_settings_has_sqs_region(self):
        assert "sqs_region" in S3Settings.model_fields
        assert S3Settings.model_fields["sqs_region"].default is None

    def test_s3_settings_has_sqs_wait_time_seconds(self):
        assert "sqs_wait_time_seconds" in S3Settings.model_fields
        assert S3Settings.model_fields["sqs_wait_time_seconds"].default == 20

    def test_s3_settings_has_s3_buffer_size_mb(self):
        assert "s3_buffer_size_mb" in S3Settings.model_fields
        assert S3Settings.model_fields["s3_buffer_size_mb"].default == 10

    def test_s3_settings_coerces_sqs_string_to_event_driven(self):
        settings = S3Settings(s3_bucket="test", tracking_mode="SQS")
        assert settings.tracking_mode == TrackingMode.EVENT_DRIVEN


class TestSQLiteS3BackendInit:
    """SQLiteS3Backend constructor and mixins."""

    def test_backend_accepts_new_parameters(self):
        sig = inspect.signature(SQLiteS3Backend.__init__)
        params = list(sig.parameters.keys())
        assert "tracking_mode" in params
        assert "sqs_queue_url" in params
        assert "sqs_region" in params
        assert "sqs_wait_time_seconds" in params
        assert "s3_buffer_size_mb" in params

    def test_backend_has_event_driven_methods(self):
        assert hasattr(SQLiteS3Backend, "_handle_s3_event")
        assert hasattr(SQLiteS3Backend, "start_event_consumer")
        assert hasattr(SQLiteS3Backend, "is_event_driven")
        assert callable(getattr(SQLiteS3Backend, "_handle_s3_event"))
        assert callable(getattr(SQLiteS3Backend, "start_event_consumer"))
        assert callable(getattr(SQLiteS3Backend, "is_event_driven"))


class TestIsEventDriven:
    def test_true_when_event_driven_and_queue_url_set(self):
        b = _minimal_backend(
            tracking_mode=TrackingMode.EVENT_DRIVEN,
            sqs_queue_url="https://sqs.us-east-1.amazonaws.com/123/test",
        )
        assert b.is_event_driven() is True

    def test_false_when_polling(self):
        b = _minimal_backend(tracking_mode=TrackingMode.POLLING, sqs_queue_url=None)
        assert b.is_event_driven() is False

    def test_false_when_event_driven_but_no_queue_url(self):
        b = _minimal_backend(tracking_mode=TrackingMode.EVENT_DRIVEN, sqs_queue_url=None)
        assert b.is_event_driven() is False


class TestParseSqsMessageEvents:
    def test_eventbridge_wrapped_s3(self):
        body = {
            "detail": {"object": {"key": "data/proj/2024/01/01/00/00/pk/app/log.jsonl"}},
            "time": "2024-06-01T12:34:56Z",
        }
        events = _parse_sqs_message_events(body)
        assert events is not None
        assert len(events) == 1
        key, t = events[0]
        assert key.endswith(".jsonl")
        assert t.tzinfo is not None

    def test_native_s3_notification_multiple_records(self):
        body = {
            "Records": [
                {
                    "s3": {"object": {"key": "data/a.jsonl"}},
                    "eventTime": "2024-01-01T00:00:00.000Z",
                },
                {
                    "s3": {"object": {"key": "data/b.jsonl"}},
                    "eventTime": "2024-01-02T00:00:00.000Z",
                },
            ]
        }
        events = _parse_sqs_message_events(body)
        assert events is not None
        assert len(events) == 2
        assert events[0][0].endswith("a.jsonl")
        assert events[1][0].endswith("b.jsonl")

    def test_unknown_format_returns_none(self):
        assert _parse_sqs_message_events({"foo": "bar"}) is None


class TestEventDrivenBackendMixin:
    def test_mixin_exists(self):
        assert EventDrivenBackendMixin is not None

    def test_mixin_has_abstract_methods(self):
        import abc

        assert issubclass(EventDrivenBackendMixin, abc.ABC)
        assert hasattr(EventDrivenBackendMixin, "start_event_consumer")
        assert hasattr(EventDrivenBackendMixin, "is_event_driven")

    def test_sqlite_s3_backend_inherits_mixin(self):
        assert issubclass(SQLiteS3Backend, EventDrivenBackendMixin)


class TestQueryS3FileBuffering:
    def test_query_s3_file_has_buffer_param(self):
        sig = inspect.signature(_query_s3_file)
        assert "buffer_size_mb" in sig.parameters
        assert sig.parameters["buffer_size_mb"].default == 10

    @pytest.mark.asyncio
    async def test_query_s3_file_reads_via_buffer(self):
        chunk = b"x" * 4096
        stream = AsyncMock()
        stream.read = AsyncMock(side_effect=[chunk, chunk, b""])

        body_cm = MagicMock()
        body_cm.__aenter__ = AsyncMock(return_value=stream)
        body_cm.__aexit__ = AsyncMock(return_value=None)

        client = AsyncMock()
        client.get_object = AsyncMock(return_value={"Body": body_cm})

        data = await _query_s3_file("bucket", "key", client, buffer_size_mb=1)
        assert data == chunk + chunk
        client.get_object.assert_called_once_with(Bucket="bucket", Key="key")


class TestHandleS3Event:
    def test_handle_s3_event_method_exists(self):
        assert hasattr(SQLiteS3Backend, "_handle_s3_event")
        method = getattr(SQLiteS3Backend, "_handle_s3_event")
        assert inspect.iscoroutinefunction(method)

    def test_handle_s3_event_signature(self):
        sig = inspect.signature(SQLiteS3Backend._handle_s3_event)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "s3_key" in params
        assert "event_time" in params
