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
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

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

    async def aread(self, store: "AsyncArtifactStore", verify: bool = True) -> bytes:
        """Asynchronous counterpart to :py:meth:`read`, for use with an
        :py:class:`AsyncArtifactStore` (e.g. from an async action).

        :param store: The async store this artifact was originally written to.
        :param verify: Whether to verify the fetched bytes match ``self.digest``. Defaults to True.
        :return: The raw bytes of the artifact.
        """
        return await store.get_artifact(self, verify=verify)


class ArtifactStore(abc.ABC):
    """Base class for blob/object storage backends.

    Implement :py:meth:`put`, :py:meth:`get`, and :py:meth:`exists` for a new backend --
    :py:meth:`put_artifact` and :py:meth:`get_artifact` are provided for free on top of those,
    so digest computation/verification is not duplicated across backends.
    """

    @abc.abstractmethod
    def put(self, data: bytes, key: str) -> Optional[bool]:
        """Stores ``data`` under ``key`` unless it already exists -- never overwrites.

        :param data: The raw bytes to store.
        :param key: The key/path to store the data under.
        :return: ``True`` if this call created the object, ``False`` if it already existed, or
            ``None`` if unknown (:py:meth:`put_artifact` then verifies the stored content).
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

    def digest(self, key: str) -> str:
        """Returns the SHA-256 hex digest of the content stored under ``key``. Override this if
        the backend can report it without downloading the content.

        :param key: The key/path to check.
        :raises FileNotFoundError: If no data is stored under ``key``.
        """
        return hashlib.sha256(self.get(key)).hexdigest()

    def is_async(self) -> bool:
        """Whether this store's I/O methods are async. Always False here -- see
        :py:class:`AsyncArtifactStore` for the async contract. Mirrors
        :py:meth:`burr.core.persistence.BaseStateSaver.is_async`."""
        return False

    def put_artifact(
        self, data: bytes, media_type: Optional[str] = None, key: Optional[str] = None
    ) -> ArtifactRef:
        """Computes the digest/size for ``data``, writes it to the store, and returns a
        fully-formed :py:class:`ArtifactRef`. This is the recommended way to write artifacts --
        it ensures every backend computes/verifies digests the same way.

        If the resolved key already holds content (including from a concurrent writer), it must
        match ``data`` -- identical content is a no-op, different content raises. So reusing an
        explicit ``key`` requires identical bytes; prefer the default key for non-deterministic
        output (e.g. an LLM response) that may be retried.

        :param data: The raw bytes to store.
        :param media_type: Optional MIME type to record on the returned ref.
        :param key: Optional explicit key to store under. If not provided, a content-addressed
            key (the hex digest) is used.
        :raises ValueError: If the resolved key already holds content whose digest does not match
            ``data``'s.
        :return: An :py:class:`ArtifactRef` describing the stored artifact.
        """
        digest = hashlib.sha256(data).hexdigest()
        resolved_key = key if key is not None else digest
        if self.exists(resolved_key) or self.put(data, resolved_key) is not True:
            _verify_stored_digest(resolved_key, self.digest(resolved_key), digest, key)
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
            _verify_fetched_digest(ref, data)
        return data


def _verify_stored_digest(
    resolved_key: str, existing_digest: str, digest: str, explicit_key: Optional[str]
) -> None:
    if existing_digest == digest:
        return  # identical content is already stored under this key -- nothing to do.
    if explicit_key is not None:
        raise ValueError(
            f"Key '{resolved_key}' already exists with different content (existing "
            f"digest {existing_digest}, new digest {digest}). Use a different explicit "
            f"key, or omit `key` to use content-addressed storage."
        )
    raise ValueError(
        f"Content stored under content-addressed key '{resolved_key}' has digest "
        f"{existing_digest}, which does not match its key. The store may have been corrupted or "
        f"modified out-of-band -- remove the object and retry."
    )


def _verify_fetched_digest(ref: ArtifactRef, data: bytes) -> None:
    actual_digest = hashlib.sha256(data).hexdigest()
    if actual_digest != ref.digest:
        raise ValueError(
            f"Digest mismatch for artifact '{ref.key}': "
            f"expected {ref.digest}, got {actual_digest}. The stored content may have "
            f"been overwritten or corrupted."
        )


class AsyncArtifactStore(abc.ABC):
    """Asynchronous counterpart to :py:class:`ArtifactStore`, for backends whose I/O should not
    block the event loop (e.g. network calls to a cloud object store). Implement this instead of
    :py:class:`ArtifactStore` if your backend's ``put``/``get``/``exists`` are I/O-bound and you
    want it to be usable from async actions without blocking other concurrent work -- mirrors the
    sync/async split already used for state persisters (see
    :py:class:`burr.core.persistence.BaseStateSaver` /
    :py:class:`burr.core.persistence.AsyncBaseStateSaver`).

    A synchronous store (e.g. :py:class:`LocalFileSystemArtifactStore`) can still be used from an
    async action, but its calls will block the event loop for their duration -- prefer an async
    store (e.g. an ``aiobotocore``-backed S3 store) for I/O-bound backends used from async code.
    """

    @abc.abstractmethod
    async def put(self, data: bytes, key: str) -> Optional[bool]:
        """Stores ``data`` under ``key`` unless it already exists -- see
        :py:meth:`ArtifactStore.put`.

        :param data: The raw bytes to store.
        :param key: The key/path to store the data under.
        :return: ``True`` if this call created the object, ``False`` if it already existed, or
            ``None`` if unknown.
        """

    @abc.abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieves the raw bytes stored under ``key``.

        :param key: The key/path to load.
        :raises FileNotFoundError: If no data is stored under ``key``.
        """

    @abc.abstractmethod
    async def exists(self, key: str) -> bool:
        """Returns whether ``key`` is present in the store."""

    async def digest(self, key: str) -> str:
        """Returns the SHA-256 hex digest of the content stored under ``key`` -- see
        :py:meth:`ArtifactStore.digest`.

        :param key: The key/path to check.
        :raises FileNotFoundError: If no data is stored under ``key``.
        """
        return hashlib.sha256(await self.get(key)).hexdigest()

    def is_async(self) -> bool:
        """Whether this store's I/O methods are async. Always True here -- see
        :py:class:`ArtifactStore` for the synchronous contract."""
        return True

    async def put_artifact(
        self, data: bytes, media_type: Optional[str] = None, key: Optional[str] = None
    ) -> ArtifactRef:
        """Asynchronous counterpart to :py:meth:`ArtifactStore.put_artifact` -- same digest
        computation and collision semantics, just awaited.

        :param data: The raw bytes to store.
        :param media_type: Optional MIME type to record on the returned ref.
        :param key: Optional explicit key to store under. If not provided, a content-addressed
            key (the hex digest) is used.
        :raises ValueError: If the resolved key already holds content whose digest does not match
            ``data``'s.
        :return: An :py:class:`ArtifactRef` describing the stored artifact.
        """
        digest = hashlib.sha256(data).hexdigest()
        resolved_key = key if key is not None else digest
        if await self.exists(resolved_key) or await self.put(data, resolved_key) is not True:
            _verify_stored_digest(resolved_key, await self.digest(resolved_key), digest, key)
        return ArtifactRef(
            key=resolved_key, size_bytes=len(data), digest=digest, media_type=media_type
        )

    async def get_artifact(self, ref: ArtifactRef, verify: bool = True) -> bytes:
        """Fetches the bytes described by ``ref``, optionally verifying its digest.

        :param ref: The reference describing what to fetch.
        :param verify: Whether to verify the fetched bytes match ``ref.digest``. Defaults to True.
        :raises ValueError: If ``verify`` is True and the fetched bytes' digest does not match.
        """
        data = await self.get(ref.key)
        if verify:
            _verify_fetched_digest(ref, data)
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
        # path -> (inode, mtime_ns, size, digest): re-verifying unchanged files skips re-reading
        self._digests: Dict[str, Tuple[int, int, int, str]] = {}

    def _path_for_key(self, key: str) -> str:
        # Resolve symlinks (os.path.realpath) rather than just normalizing (os.path.abspath) --
        # otherwise a symlink inside root_dir pointing outside of it would let a key escape the
        # store undetected. realpath resolves symlinks in existing path components even when the
        # final path segment (e.g. a not-yet-written artifact file) does not exist yet.
        root = os.path.realpath(self.root_dir)
        path = os.path.realpath(os.path.join(root, key))
        if os.path.commonpath([root, path]) != root:
            raise ValueError(
                f"Invalid artifact key '{key}': resolves outside of the store's root directory."
            )
        return path

    def put(self, data: bytes, key: str) -> Optional[bool]:
        path = self._path_for_key(key)
        if os.path.exists(path):
            return False
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        # temp file + hard link: atomic, and (unlike a rename) fails if `path` already exists.
        # Created with 0o666 so the umask applies, as for a regular file.
        tmp_path = os.path.join(directory, f".tmp-artifact-{uuid.uuid4().hex}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        fd = os.open(tmp_path, flags, 0o666)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(tmp_path, path)
            except FileExistsError:
                return False
            except OSError:
                # no hard-link support -- rename, and return None so put_artifact verifies
                os.replace(tmp_path, path)
                return None
            self._remember_digest(path, hashlib.sha256(data).hexdigest())
            return True
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def get(self, key: str) -> bytes:
        path = self._path_for_key(key)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Artifact '{key}' not found in store at '{self.root_dir}'.")
        with open(path, "rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path_for_key(key))

    def digest(self, key: str) -> str:
        path = self._path_for_key(key)
        try:
            stat = os.stat(path)
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Artifact '{key}' not found in store at '{self.root_dir}'."
            ) from e
        cached = self._digests.get(path)
        if cached is not None and cached[:3] == (stat.st_ino, stat.st_mtime_ns, stat.st_size):
            return cached[3]
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        self._digests[path] = (stat.st_ino, stat.st_mtime_ns, stat.st_size, digest)
        return digest

    def _remember_digest(self, path: str, digest: str) -> None:
        stat = os.stat(path)
        self._digests[path] = (stat.st_ino, stat.st_mtime_ns, stat.st_size, digest)


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
