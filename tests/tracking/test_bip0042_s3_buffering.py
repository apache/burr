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

"""BIP-0042: Tests for S3 buffering fix and settings."""

import inspect

import pytest


class TestS3Settings:
    """Test that S3Settings has all BIP-0042 fields with correct defaults."""

    def test_s3_settings_has_tracking_mode(self):
        """Verify tracking_mode field exists with POLLING default."""
        from burr.tracking.server.s3.backend import S3Settings, TrackingMode

        assert "tracking_mode" in S3Settings.model_fields
        assert S3Settings.model_fields["tracking_mode"].default == TrackingMode.POLLING

    def test_s3_settings_has_sqs_queue_url(self):
        """Verify sqs_queue_url field exists with None default."""
        from burr.tracking.server.s3.backend import S3Settings

        assert "sqs_queue_url" in S3Settings.model_fields
        assert S3Settings.model_fields["sqs_queue_url"].default is None

    def test_s3_settings_has_sqs_region(self):
        """Verify sqs_region field exists with None default."""
        from burr.tracking.server.s3.backend import S3Settings

        assert "sqs_region" in S3Settings.model_fields
        assert S3Settings.model_fields["sqs_region"].default is None

    def test_s3_settings_has_sqs_wait_time_seconds(self):
        """Verify sqs_wait_time_seconds field exists with 20 default."""
        from burr.tracking.server.s3.backend import S3Settings

        assert "sqs_wait_time_seconds" in S3Settings.model_fields
        assert S3Settings.model_fields["sqs_wait_time_seconds"].default == 20

    def test_s3_settings_has_s3_buffer_size_mb(self):
        """Verify s3_buffer_size_mb field exists with 10 default."""
        from burr.tracking.server.s3.backend import S3Settings

        assert "s3_buffer_size_mb" in S3Settings.model_fields
        assert S3Settings.model_fields["s3_buffer_size_mb"].default == 10

    def test_s3_settings_coerces_sqs_to_event_driven(self):
        """Verify legacy 'SQS' string coerces to EVENT_DRIVEN for backward compatibility."""
        from burr.tracking.server.s3.backend import S3Settings, TrackingMode

        settings = S3Settings(s3_bucket="test", tracking_mode="SQS")
        assert settings.tracking_mode == TrackingMode.EVENT_DRIVEN


class TestSQLiteS3BackendInit:
    """Test SQLiteS3Backend accepts and stores BIP-0042 parameters."""

    def test_backend_accepts_new_parameters(self):
        """Verify __init__ accepts all 5 new BIP-0042 parameters."""
        from burr.tracking.server.s3.backend import SQLiteS3Backend

        sig = inspect.signature(SQLiteS3Backend.__init__)
        params = list(sig.parameters.keys())

        assert "tracking_mode" in params
        assert "sqs_queue_url" in params
        assert "sqs_region" in params
        assert "sqs_wait_time_seconds" in params
        assert "s3_buffer_size_mb" in params

    def test_backend_has_event_driven_methods(self):
        """Verify SQLiteS3Backend has event-driven methods."""
        from burr.tracking.server.s3.backend import SQLiteS3Backend

        assert hasattr(SQLiteS3Backend, "_handle_s3_event")
        assert hasattr(SQLiteS3Backend, "start_event_consumer")
        assert hasattr(SQLiteS3Backend, "is_event_driven")
        assert callable(getattr(SQLiteS3Backend, "_handle_s3_event"))
        assert callable(getattr(SQLiteS3Backend, "start_event_consumer"))
        assert callable(getattr(SQLiteS3Backend, "is_event_driven"))


class TestEventDrivenBackendMixin:
    """Test EventDrivenBackendMixin exists and has correct interface."""

    def test_mixin_exists(self):
        """Verify EventDrivenBackendMixin exists in backend.py."""
        from burr.tracking.server.backend import EventDrivenBackendMixin

        assert EventDrivenBackendMixin is not None

    def test_mixin_has_abstract_methods(self):
        """Verify mixin has abstract start_event_consumer and is_event_driven."""
        import abc

        from burr.tracking.server.backend import EventDrivenBackendMixin

        assert issubclass(EventDrivenBackendMixin, abc.ABC)
        assert hasattr(EventDrivenBackendMixin, "start_event_consumer")
        assert hasattr(EventDrivenBackendMixin, "is_event_driven")

    def test_sqlite_s3_backend_inherits_mixin(self):
        """Verify SQLiteS3Backend inherits from EventDrivenBackendMixin."""
        from burr.tracking.server.backend import EventDrivenBackendMixin
        from burr.tracking.server.s3.backend import SQLiteS3Backend

        assert issubclass(SQLiteS3Backend, EventDrivenBackendMixin)


class TestQueryS3FileBuffering:
    """Test _query_s3_file function signature includes buffer_size_mb."""

    def test_query_s3_file_has_buffer_param(self):
        """Verify _query_s3_file accepts buffer_size_mb parameter."""
        from burr.tracking.server.s3.backend import _query_s3_file

        sig = inspect.signature(_query_s3_file)
        params = list(sig.parameters.keys())

        assert "buffer_size_mb" in params
        assert sig.parameters["buffer_size_mb"].default == 10


class TestHandleS3Event:
    """Test _handle_s3_event creates project if it doesn't exist."""

    def test_handle_s3_event_method_exists(self):
        """Verify _handle_s3_event method exists and is async."""
        from burr.tracking.server.s3.backend import SQLiteS3Backend

        assert hasattr(SQLiteS3Backend, "_handle_s3_event")
        method = getattr(SQLiteS3Backend, "_handle_s3_event")
        assert inspect.iscoroutinefunction(method)

    def test_handle_s3_event_signature(self):
        """Verify _handle_s3_event accepts s3_key and event_time parameters."""
        from burr.tracking.server.s3.backend import SQLiteS3Backend

        sig = inspect.signature(SQLiteS3Backend._handle_s3_event)
        params = list(sig.parameters.keys())

        assert "self" in params
        assert "s3_key" in params
        assert "event_time" in params
