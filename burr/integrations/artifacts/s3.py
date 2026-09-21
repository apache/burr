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
"""

from typing import Any, Optional

from burr.core.artifacts import ArtifactStore
from burr.integrations import base

try:
    import boto3
    import botocore.exceptions
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
