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

"""Blob/object storage abstraction for large values held in :py:class:`burr.core.state.State`.

Rather than embedding large binary payloads (files, dataframes, images, etc...) directly in
state -- which gets fully re-serialized to the persistence layer after every action -- store the
payload in an :py:class:`ArtifactStore` and keep a small, content-addressed :py:class:`ArtifactRef`
in state instead. Deserializing a ref does *not* eagerly fetch the underlying bytes -- callers
must explicitly call :py:meth:`ArtifactRef.read` (or ``store.get_artifact``) to do so.

See :doc:`../reference/serde` and :doc:`../concepts/state-persistence` for background on how
state serialization interacts with this module.
"""

import abc
import hashlib
import os
from dataclasses import dataclass
from typing import Optional

from burr.core import serde


@dataclass(frozen=True)
class ArtifactRef:
    """A lightweight, content-addressed reference to a blob stored in an :py:class:`ArtifactStore`.

    This is what you should store in :py:class:`burr.core.state.State` -- *not* the raw bytes/object.
    It is registered with :py:mod:`burr.core.serde` so it serializes/deserializes automatically as
    part of normal state (de)serialization; deserializing only recreates this reference, it never
    re-fetches the underlying bytes on its own.

    :param key: The store-specific key/path the blob is stored under.
    :param size_bytes: Size of the blob, in bytes.
    :param digest: SHA-256 hex digest of the blob's contents, used to verify integrity on read
        and to detect duplicate content.
    :param media_type: Optional MIME type (e.g. ``"application/pdf"``) for the caller's own use.
    """

    key: str
    size_bytes: int
    digest: str
    media_type: Optional[str] = None

    def read(self, store: "ArtifactStore", verify: bool = True) -> bytes:
        """Lazily fetches the underlying bytes for this reference from ``store``.

        :param store: The store this artifact was originally written to.
        :param verify: Whether to verify the fetched bytes match ``self.digest``. Defaults to True.
        :return: The raw bytes of the artifact.
        """
        return store.get_artifact(self, verify=verify)


class ArtifactStore(abc.ABC):
    """Base class for blob/object storage backends.

    Implement :py:meth:`put`, :py:meth:`get`, and :py:meth:`exists` for a new backend --
    :py:meth:`put_artifact` and :py:meth:`get_artifact` are provided for free on top of those,
    so digest computation/verification is not duplicated across backends.
    """

    @abc.abstractmethod
    def put(self, data: bytes, key: str) -> None:
        """Stores ``data`` under ``key``. Should be idempotent -- writing the same key twice
        with the same content should not error.

        :param data: The raw bytes to store.
        :param key: The key/path to store the data under.
        """

    @abc.abstractmethod
    def get(self, key: str) -> bytes:
        """Retrieves the raw bytes stored under ``key``.

        :param key: The key/path to load.
        :raises FileNotFoundError: If no data is stored under ``key``.
        """

    @abc.abstractmethod
    def exists(self, key: str) -> bool:
        """Returns whether ``key`` is present in the store."""

    def put_artifact(
        self, data: bytes, media_type: Optional[str] = None, key: Optional[str] = None
    ) -> ArtifactRef:
        """Computes the digest/size for ``data``, writes it to the store, and returns a
        fully-formed :py:class:`ArtifactRef`. This is the recommended way to write artifacts --
        it ensures every backend computes/verifies digests the same way.

        :param data: The raw bytes to store.
        :param media_type: Optional MIME type to record on the returned ref.
        :param key: Optional explicit key to store under. If not provided, a content-addressed
            key (the hex digest) is used -- so writing identical content twice is a no-op.
        :return: An :py:class:`ArtifactRef` describing the stored artifact.
        """
        digest = hashlib.sha256(data).hexdigest()
        resolved_key = key if key is not None else digest
        self.put(data, resolved_key)
        return ArtifactRef(
            key=resolved_key, size_bytes=len(data), digest=digest, media_type=media_type
        )

    def get_artifact(self, ref: ArtifactRef, verify: bool = True) -> bytes:
        """Fetches the bytes described by ``ref``, optionally verifying its digest.

        :param ref: The reference describing what to fetch.
        :param verify: Whether to verify the fetched bytes match ``ref.digest``. Defaults to True.
        :raises ValueError: If ``verify`` is True and the fetched bytes' digest does not match.
        """
        data = self.get(ref.key)
        if verify:
            actual_digest = hashlib.sha256(data).hexdigest()
            if actual_digest != ref.digest:
                raise ValueError(
                    f"Digest mismatch for artifact '{ref.key}': "
                    f"expected {ref.digest}, got {actual_digest}. The stored content may have "
                    f"been overwritten or corrupted."
                )
        return data


class LocalFileSystemArtifactStore(ArtifactStore):
    """An :py:class:`ArtifactStore` backed by a directory on the local filesystem.
    Has no third-party dependencies. For cloud-backed stores (S3, GCS, ...) see
    ``burr.integrations.artifacts``.
    """

    def __init__(self, root_dir: str):
        """Constructor.

        :param root_dir: Directory to store artifacts under. Created if it does not exist.
        """
        self.root_dir = root_dir
        os.makedirs(root_dir, exist_ok=True)

    def _path_for_key(self, key: str) -> str:
        root = os.path.abspath(self.root_dir)
        path = os.path.abspath(os.path.join(root, key))
        if os.path.commonpath([root, path]) != root:
            raise ValueError(
                f"Invalid artifact key '{key}': resolves outside of the store's root directory."
            )
        return path

    def put(self, data: bytes, key: str) -> None:
        path = self._path_for_key(key)
        if os.path.exists(path):
            # content-addressed keys make writes idempotent -- skip re-writing existing data.
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def get(self, key: str) -> bytes:
        path = self._path_for_key(key)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Artifact '{key}' not found in store at '{self.root_dir}'.")
        with open(path, "rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path_for_key(key))


_ARTIFACT_REF_SERDE_KEY = "ArtifactRef"


@serde.serialize.register(ArtifactRef)
def _serialize_artifact_ref(value: ArtifactRef, **kwargs) -> dict:
    return {
        serde.KEY: _ARTIFACT_REF_SERDE_KEY,
        "key": value.key,
        "size_bytes": value.size_bytes,
        "digest": value.digest,
        "media_type": value.media_type,
    }


@serde.deserializer.register(_ARTIFACT_REF_SERDE_KEY)
def _deserialize_artifact_ref(value: dict, **kwargs) -> ArtifactRef:
    return ArtifactRef(
        key=value["key"],
        size_bytes=value["size_bytes"],
        digest=value["digest"],
        media_type=value.get("media_type"),
    )
