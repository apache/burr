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

"""Tests for S3ArtifactStore.

These use botocore's built-in ``Stubber`` (a dependency of boto3, already required by this
module) to mock S3 responses -- no live AWS account, network access, or extra test
dependency is required.
"""

import hashlib
import io

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from burr.core.artifacts import ArtifactRef
from burr.integrations.artifacts.s3 import S3ArtifactStore


def _streaming_body(data: bytes) -> StreamingBody:
    return StreamingBody(io.BytesIO(data), len(data))


@pytest.fixture
def s3_client():
    # dummy credentials/region -- Stubber intercepts calls before any network access happens.
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    with Stubber(client) as stubber:
        yield client, stubber


@pytest.fixture
def store(s3_client):
    client, _stubber = s3_client
    return S3ArtifactStore(bucket="my-bucket", prefix="artifacts", client=client)


def test_put_uploads_when_key_does_not_exist(store, s3_client):
    _client, stubber = s3_client
    data = b"hello from s3"

    stubber.add_client_error("head_object", service_error_code="404")
    stubber.add_response(
        "put_object",
        {},
        expected_params={"Bucket": "my-bucket", "Key": "artifacts/my-key", "Body": data},
    )

    store.put(data, key="my-key")

    stubber.assert_no_pending_responses()


def test_put_skips_upload_when_key_already_exists(store, s3_client):
    _client, stubber = s3_client
    data = b"hello from s3"

    stubber.add_response(
        "head_object",
        {},
        expected_params={"Bucket": "my-bucket", "Key": "artifacts/my-key"},
    )
    # no put_object stubbed -- if the store tried to upload, Stubber would raise.

    store.put(data, key="my-key")

    stubber.assert_no_pending_responses()


def test_get_returns_object_bytes(store, s3_client):
    _client, stubber = s3_client
    data = b"the stored artifact bytes"

    stubber.add_response(
        "get_object",
        {"Body": _streaming_body(data)},
        expected_params={"Bucket": "my-bucket", "Key": "artifacts/my-key"},
    )

    assert store.get("my-key") == data
    stubber.assert_no_pending_responses()


def test_get_missing_key_raises_file_not_found(store, s3_client):
    _client, stubber = s3_client
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)

    with pytest.raises(FileNotFoundError):
        store.get("missing-key")


def test_exists_true(store, s3_client):
    _client, stubber = s3_client
    stubber.add_response(
        "head_object",
        {},
        expected_params={"Bucket": "my-bucket", "Key": "artifacts/my-key"},
    )

    assert store.exists("my-key")


def test_exists_false_for_missing_key(store, s3_client):
    _client, stubber = s3_client
    stubber.add_client_error("head_object", service_error_code="404")

    assert not store.exists("missing-key")


def test_no_prefix_uses_bare_key(s3_client):
    client, stubber = s3_client
    store = S3ArtifactStore(bucket="my-bucket", client=client)

    stubber.add_client_error("head_object", service_error_code="404")
    stubber.add_response(
        "put_object",
        {},
        expected_params={"Bucket": "my-bucket", "Key": "my-key", "Body": b"data"},
    )

    store.put(b"data", key="my-key")
    stubber.assert_no_pending_responses()


def test_put_artifact_and_get_artifact_end_to_end(store, s3_client):
    """Exercises the shared ArtifactStore.put_artifact/get_artifact helpers against S3."""
    _client, stubber = s3_client
    data = b"end to end artifact content"
    digest = hashlib.sha256(data).hexdigest()

    # put_artifact() -> content-addressed key == digest
    stubber.add_client_error("head_object", service_error_code="404")
    stubber.add_response(
        "put_object",
        {},
        expected_params={"Bucket": "my-bucket", "Key": f"artifacts/{digest}", "Body": data},
    )

    ref = store.put_artifact(data, media_type="text/plain")
    assert isinstance(ref, ArtifactRef)
    assert ref.key == digest
    assert ref.digest == digest
    assert ref.size_bytes == len(data)

    # get_artifact() -> verifies digest matches after fetch
    stubber.add_response(
        "get_object",
        {"Body": _streaming_body(data)},
        expected_params={"Bucket": "my-bucket", "Key": f"artifacts/{digest}"},
    )
    assert store.get_artifact(ref) == data
    stubber.assert_no_pending_responses()
