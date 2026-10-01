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

"""Tests for S3ArtifactStore and AsyncS3ArtifactStore.

S3ArtifactStore's tests use botocore's built-in ``Stubber`` (a dependency of boto3, already
required by this module) to mock S3 responses. AsyncS3ArtifactStore's tests mock an aiobotocore
client directly with ``AsyncMock`` instead -- the same approach already used elsewhere in this
repo for aiobotocore-backed code (see tests/tracking/test_bip0042_s3_buffering.py). Neither needs
a live AWS account or network access.
"""

import hashlib
import io
from unittest.mock import AsyncMock, MagicMock

import boto3
import botocore.exceptions
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from burr.core.artifacts import ArtifactRef
from burr.integrations.artifacts.s3 import AsyncS3ArtifactStore, S3ArtifactStore


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


def test_put_artifact_explicit_key_identical_content_is_noop(store, s3_client):
    """Same collision-safety guarantee as the local backend: re-`put_artifact`-ing identical
    content under an explicit key that already exists must not re-upload."""
    _client, stubber = s3_client
    data = b"same content"

    stubber.add_response(
        "head_object",
        {},
        expected_params={"Bucket": "my-bucket", "Key": "artifacts/stable-key"},
    )
    stubber.add_response(
        "get_object",
        {"Body": _streaming_body(data)},
        expected_params={"Bucket": "my-bucket", "Key": "artifacts/stable-key"},
    )
    # no put_object stubbed -- if the store tried to re-upload, Stubber would raise.

    ref = store.put_artifact(data, key="stable-key")

    assert ref.key == "stable-key"
    stubber.assert_no_pending_responses()


def test_put_artifact_explicit_key_conflicting_content_raises(store, s3_client):
    """An explicit key that already holds *different* content must not be silently overwritten
    or skipped -- put_artifact must surface a clear conflict instead of returning a ref that
    doesn't describe what's actually stored."""
    _client, stubber = s3_client
    existing_data = b"first"
    new_data = b"second"

    stubber.add_response(
        "head_object",
        {},
        expected_params={"Bucket": "my-bucket", "Key": "artifacts/mutable"},
    )
    stubber.add_response(
        "get_object",
        {"Body": _streaming_body(existing_data)},
        expected_params={"Bucket": "my-bucket", "Key": "artifacts/mutable"},
    )
    # no put_object stubbed -- the conflicting write must be rejected before any upload attempt.

    with pytest.raises(ValueError, match="already exists with different content"):
        store.put_artifact(new_data, key="mutable")

    stubber.assert_no_pending_responses()


# --- AsyncS3ArtifactStore tests below ---


def _client_error(code: str, operation: str = "HeadObject") -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError({"Error": {"Code": code}}, operation)


def _async_streaming_body(data: bytes) -> MagicMock:
    stream = AsyncMock()
    stream.read = AsyncMock(return_value=data)
    body_cm = MagicMock()
    body_cm.__aenter__ = AsyncMock(return_value=stream)
    body_cm.__aexit__ = AsyncMock(return_value=None)
    return body_cm


@pytest.fixture
def async_client():
    return AsyncMock()


@pytest.fixture
def async_store(async_client):
    return AsyncS3ArtifactStore(bucket="my-bucket", prefix="artifacts", client=async_client)


def test_async_store_requires_already_open_client():
    with pytest.raises(ValueError, match="already-open aiobotocore client"):
        AsyncS3ArtifactStore(bucket="my-bucket")


async def test_async_put_uploads_when_key_does_not_exist(async_store, async_client):
    data = b"hello from async s3"
    async_client.head_object = AsyncMock(side_effect=_client_error("404"))
    async_client.put_object = AsyncMock(return_value={})

    await async_store.put(data, key="my-key")

    async_client.put_object.assert_awaited_once_with(
        Bucket="my-bucket", Key="artifacts/my-key", Body=data
    )


async def test_async_put_skips_upload_when_key_already_exists(async_store, async_client):
    async_client.head_object = AsyncMock(return_value={})
    async_client.put_object = AsyncMock()

    await async_store.put(b"hello from async s3", key="my-key")

    async_client.put_object.assert_not_awaited()


async def test_async_get_returns_object_bytes(async_store, async_client):
    data = b"the stored artifact bytes"
    async_client.get_object = AsyncMock(return_value={"Body": _async_streaming_body(data)})

    assert await async_store.get("my-key") == data
    async_client.get_object.assert_awaited_once_with(Bucket="my-bucket", Key="artifacts/my-key")


async def test_async_get_missing_key_raises_file_not_found(async_store, async_client):
    async_client.get_object = AsyncMock(
        side_effect=_client_error("NoSuchKey", operation="GetObject")
    )

    with pytest.raises(FileNotFoundError):
        await async_store.get("missing-key")


async def test_async_exists_true(async_store, async_client):
    async_client.head_object = AsyncMock(return_value={})

    assert await async_store.exists("my-key")


async def test_async_exists_false_for_missing_key(async_store, async_client):
    async_client.head_object = AsyncMock(side_effect=_client_error("404"))

    assert not await async_store.exists("missing-key")


async def test_async_put_artifact_and_get_artifact_end_to_end(async_store, async_client):
    """Exercises the shared AsyncArtifactStore.put_artifact/get_artifact helpers against S3."""
    data = b"end to end async artifact content"
    digest = hashlib.sha256(data).hexdigest()

    async_client.head_object = AsyncMock(side_effect=_client_error("404"))
    async_client.put_object = AsyncMock(return_value={})

    ref = await async_store.put_artifact(data, media_type="text/plain")
    assert isinstance(ref, ArtifactRef)
    assert ref.key == digest
    assert ref.digest == digest
    assert ref.size_bytes == len(data)
    async_client.put_object.assert_awaited_once_with(
        Bucket="my-bucket", Key=f"artifacts/{digest}", Body=data
    )

    async_client.get_object = AsyncMock(return_value={"Body": _async_streaming_body(data)})
    assert await async_store.get_artifact(ref) == data


async def test_async_put_artifact_explicit_key_identical_content_is_noop(async_store, async_client):
    """Same collision-safety guarantee as the sync backend: re-`put_artifact`-ing identical
    content under an explicit key that already exists must not re-upload."""
    data = b"same content"
    async_client.head_object = AsyncMock(return_value={})
    async_client.get_object = AsyncMock(return_value={"Body": _async_streaming_body(data)})
    async_client.put_object = AsyncMock()

    ref = await async_store.put_artifact(data, key="stable-key")

    assert ref.key == "stable-key"
    async_client.put_object.assert_not_awaited()


async def test_async_put_artifact_explicit_key_conflicting_content_raises(
    async_store, async_client
):
    """An explicit key that already holds *different* content must not be silently overwritten
    or skipped -- put_artifact must surface a clear conflict instead of returning a ref that
    doesn't describe what's actually stored."""
    existing_data = b"first"
    new_data = b"second"
    async_client.head_object = AsyncMock(return_value={})
    async_client.get_object = AsyncMock(return_value={"Body": _async_streaming_body(existing_data)})
    async_client.put_object = AsyncMock()

    with pytest.raises(ValueError, match="already exists with different content"):
        await async_store.put_artifact(new_data, key="mutable")

    async_client.put_object.assert_not_awaited()


async def test_async_store_acreate_opens_client_via_session_and_aclose_closes_it(monkeypatch):
    """`acreate` must open the aiobotocore client via the async-context-manager protocol (it
    can't just call the constructor directly, unlike boto3), and `aclose` must release it."""
    import burr.integrations.artifacts.s3 as s3_module

    fake_client = AsyncMock()
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=fake_client)
    client_cm.__aexit__ = AsyncMock(return_value=None)

    fake_session = MagicMock()
    fake_session.create_client = MagicMock(return_value=client_cm)

    monkeypatch.setattr(s3_module.aiobotocore.session, "get_session", lambda: fake_session)

    store = await AsyncS3ArtifactStore.acreate(bucket="my-bucket", prefix="artifacts")

    assert store.client is fake_client
    fake_session.create_client.assert_called_once_with("s3")

    await store.aclose()
    client_cm.__aexit__.assert_awaited_once()
