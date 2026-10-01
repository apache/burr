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

"""An :py:class:`~burr.core.artifacts.ArtifactStore` backed by AWS S3.

Requires the ``boto3`` package -- install with ``pip install "apache-burr[s3]"``.

Also provides :py:class:`AsyncS3ArtifactStore`, a non-blocking counterpart backed by
``aiobotocore`` (installed alongside ``boto3`` via the same ``s3`` extra) for use from async
actions -- ``S3ArtifactStore`` performs blocking network I/O and should not be called from async
actions, since it would block the event loop for the duration of each upload/download.
"""

from typing import Any, Optional

from burr.core.artifacts import ArtifactStore, AsyncArtifactStore
from burr.integrations import base

try:
    import boto3
    import botocore.exceptions
except ImportError as e:
    base.require_plugin(e, "s3")

try:
    import aiobotocore.session
except ImportError as e:
    base.require_plugin(e, "s3")


class S3ArtifactStore(ArtifactStore):
    """Stores artifacts as objects in an S3 bucket, optionally under a key prefix."""

    @classmethod
    def from_config(cls, config: dict) -> "S3ArtifactStore":
        """Creates a new instance from a configuration dictionary. See :py:meth:`from_values`
        for the accepted keys."""
        return cls.from_values(**config)

    @classmethod
    def from_values(
        cls,
        bucket: str,
        prefix: str = "",
        client_kwargs: Optional[dict] = None,
    ) -> "S3ArtifactStore":
        """Creates a new instance, constructing its own boto3 S3 client.

        :param bucket: Name of the S3 bucket to store artifacts in.
        :param prefix: Optional key prefix (e.g. ``"my-app/artifacts"``) applied to every key.
        :param client_kwargs: Optional kwargs passed to ``boto3.client("s3", ...)``.
        """
        client = boto3.client("s3", **(client_kwargs or {}))
        return cls(bucket, prefix=prefix, client=client)

    def __init__(self, bucket: str, prefix: str = "", client: Optional[Any] = None):
        """Constructor.

        :param bucket: Name of the S3 bucket to store artifacts in.
        :param prefix: Optional key prefix (e.g. ``"my-app/artifacts"``) applied to every key.
        :param client: An existing boto3 S3 client. If not provided, one is created with
            default credentials/region resolution (``boto3.client("s3")``).
        """
        self.bucket = bucket
        self.prefix = prefix
        self.client = client if client is not None else boto3.client("s3")

    def _object_key(self, key: str) -> str:
        if self.prefix:
            return f"{self.prefix.rstrip('/')}/{key}"
        return key

    def put(self, data: bytes, key: str) -> None:
        # content-addressed keys make writes idempotent -- skip re-uploading existing data.
        if self.exists(key):
            return
        self.client.put_object(Bucket=self.bucket, Key=self._object_key(key), Body=data)

    def get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._object_key(key))
        except botocore.exceptions.ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code in ("NoSuchKey", "404"):
                raise FileNotFoundError(
                    f"Artifact '{key}' not found in bucket '{self.bucket}' "
                    f"(prefix='{self.prefix}')."
                ) from e
            raise
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._object_key(key))
            return True
        except botocore.exceptions.ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code in ("404", "NoSuchKey"):
                return False
            raise


class AsyncS3ArtifactStore(AsyncArtifactStore):
    """Non-blocking counterpart to :py:class:`S3ArtifactStore`, backed by ``aiobotocore`` so it
    can safely be used from async actions without blocking the event loop. Prefer this over
    :py:class:`S3ArtifactStore` whenever the store is configured on an application built with
    :py:meth:`~burr.core.application.ApplicationBuilder.abuild`.
    """

    @classmethod
    async def acreate(
        cls,
        bucket: str,
        prefix: str = "",
        client_kwargs: Optional[dict] = None,
    ) -> "AsyncS3ArtifactStore":
        """Async factory that opens its own ``aiobotocore`` session/client. Must be awaited --
        unlike ``boto3.client(...)``, an ``aiobotocore`` client is opened via an async context
        manager, so this can't be done in a plain (synchronous) constructor/``from_values``.

        :param bucket: Name of the S3 bucket to store artifacts in.
        :param prefix: Optional key prefix (e.g. ``"my-app/artifacts"``) applied to every key.
        :param client_kwargs: Optional kwargs passed to ``session.create_client("s3", ...)``.
        """
        session = aiobotocore.session.get_session()
        client_cm = session.create_client("s3", **(client_kwargs or {}))
        client = await client_cm.__aenter__()
        return cls(bucket, prefix=prefix, client=client, _client_cm=client_cm)

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        client: Optional[Any] = None,
        _client_cm: Optional[Any] = None,
    ):
        """Constructor.

        :param bucket: Name of the S3 bucket to store artifacts in.
        :param prefix: Optional key prefix (e.g. ``"my-app/artifacts"``) applied to every key.
        :param client: An already-open ``aiobotocore`` S3 client (e.g. entered via
            ``async with session.create_client("s3") as client``). Prefer :py:meth:`acreate` if
            you don't already have one -- this is intentionally not optional/self-constructing
            since opening an ``aiobotocore`` client requires an ``await``.
        """
        if client is None:
            raise ValueError(
                "AsyncS3ArtifactStore requires an already-open aiobotocore client. Use "
                "`await AsyncS3ArtifactStore.acreate(...)` to construct one, or open your own "
                "and pass it as `client`."
            )
        self.bucket = bucket
        self.prefix = prefix
        self.client = client
        self._client_cm = _client_cm

    async def aclose(self) -> None:
        """Closes the underlying client, if this instance opened one itself via
        :py:meth:`acreate`. No-op if a pre-opened ``client`` was passed to the constructor
        directly -- that client is owned by the caller."""
        if self._client_cm is not None:
            await self._client_cm.__aexit__(None, None, None)

    def _object_key(self, key: str) -> str:
        if self.prefix:
            return f"{self.prefix.rstrip('/')}/{key}"
        return key

    async def put(self, data: bytes, key: str) -> None:
        # content-addressed keys make writes idempotent -- skip re-uploading existing data.
        if await self.exists(key):
            return
        await self.client.put_object(Bucket=self.bucket, Key=self._object_key(key), Body=data)

    async def get(self, key: str) -> bytes:
        try:
            response = await self.client.get_object(Bucket=self.bucket, Key=self._object_key(key))
        except botocore.exceptions.ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code in ("NoSuchKey", "404"):
                raise FileNotFoundError(
                    f"Artifact '{key}' not found in bucket '{self.bucket}' "
                    f"(prefix='{self.prefix}')."
                ) from e
            raise
        async with response["Body"] as stream:
            return await stream.read()

    async def exists(self, key: str) -> bool:
        try:
            await self.client.head_object(Bucket=self.bucket, Key=self._object_key(key))
            return True
        except botocore.exceptions.ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code in ("404", "NoSuchKey"):
                return False
            raise
