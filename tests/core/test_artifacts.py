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

import hashlib
import os
import stat
import subprocess
import sys
import textwrap

import pytest

from burr.core import serde, state
from burr.core.artifacts import ArtifactRef, AsyncArtifactStore, LocalFileSystemArtifactStore


@pytest.fixture
def store(tmp_path):
    return LocalFileSystemArtifactStore(root_dir=str(tmp_path))


def test_put_and_get_roundtrip(store):
    data = b"hello world large payload"
    store.put(data, key="my-key")

    assert store.exists("my-key")
    assert store.get("my-key") == data


def test_get_missing_key_raises(store):
    with pytest.raises(FileNotFoundError):
        store.get("does-not-exist")


def test_exists_false_for_missing_key(store):
    assert not store.exists("does-not-exist")


def test_put_and_get_nested_key_creates_parent_dirs(store):
    data = b"nested payload"
    store.put(data, key="sub/dir/file.txt")

    assert store.exists("sub/dir/file.txt")
    assert store.get("sub/dir/file.txt") == data


@pytest.mark.parametrize(
    "bad_key",
    ["../escape.txt", "../../etc/passwd", "sub/../../escape.txt"],
)
def test_put_rejects_keys_that_escape_root_dir(store, bad_key):
    with pytest.raises(ValueError):
        store.put(b"malicious", key=bad_key)


def test_get_rejects_keys_that_escape_root_dir(store):
    with pytest.raises(ValueError):
        store.get("../escape.txt")


def test_put_rejects_symlinked_escape(store, tmp_path):
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir()
    (tmp_path / "link").symlink_to(outside_dir)

    with pytest.raises(ValueError):
        store.put(b"malicious", key="link/escape.txt")
    assert not (outside_dir / "escape.txt").exists()


def test_get_rejects_symlinked_escape(store, tmp_path):
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir()
    (outside_dir / "escape.txt").write_bytes(b"outside data")
    (tmp_path / "link").symlink_to(outside_dir)

    with pytest.raises(ValueError):
        store.get("link/escape.txt")


def test_exists_rejects_symlinked_escape(store, tmp_path):
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir()
    (tmp_path / "link").symlink_to(outside_dir)

    with pytest.raises(ValueError):
        store.exists("link/escape.txt")


def test_put_writes_atomically_and_recovers_from_interrupted_write(store, tmp_path, monkeypatch):
    def failing_fsync(fd):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr("os.fsync", failing_fsync)

    with pytest.raises(OSError):
        store.put(b"x" * 1000, key="flaky-key")

    # the destination must not exist -- the write failed before the atomic rename into place
    assert not store.exists("flaky-key")
    # no leftover temp files should be left behind in the store directory
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".tmp-artifact-")]
    assert leftovers == []

    monkeypatch.undo()

    # a subsequent, uninterrupted write for the same key must succeed normally
    store.put(b"good data", key="flaky-key")
    assert store.get("flaky-key") == b"good data"


def test_put_artifact_computes_digest_and_size(store):
    data = b"some binary content"
    ref = store.put_artifact(data, media_type="application/octet-stream")

    assert isinstance(ref, ArtifactRef)
    assert ref.size_bytes == len(data)
    assert ref.digest == hashlib.sha256(data).hexdigest()
    assert ref.media_type == "application/octet-stream"
    # content-addressed by default -- key derived from digest
    assert ref.key == ref.digest


def test_put_artifact_with_explicit_key(store):
    data = b"some binary content"
    ref = store.put_artifact(data, key="explicit-key")

    assert ref.key == "explicit-key"
    assert store.get("explicit-key") == data


def test_put_artifact_explicit_key_identical_content_is_noop(store):
    data = b"same content, written twice"
    ref1 = store.put_artifact(data, key="stable-key")
    ref2 = store.put_artifact(data, key="stable-key")

    assert ref1 == ref2
    assert store.get("stable-key") == data


def test_put_artifact_explicit_key_conflicting_content_raises(store):
    store.put_artifact(b"first", key="mutable")

    with pytest.raises(ValueError, match="already exists with different content"):
        store.put_artifact(b"second", key="mutable")

    # the original content must be left untouched -- a rejected write must not corrupt the key
    assert store.get("mutable") == b"first"


def test_put_artifact_is_idempotent_for_identical_content(store):
    data = b"duplicate content"
    ref1 = store.put_artifact(data)
    ref2 = store.put_artifact(data)

    # same content -> same content-addressed key, written only once
    assert ref1.key == ref2.key


def test_put_reports_whether_it_created_the_object(store):
    assert store.put(b"first", key="k") is True
    # an existing object is never overwritten
    assert store.put(b"second", key="k") is False
    assert store.get("k") == b"first"


def test_put_artifact_default_key_with_corrupted_content_raises(store, tmp_path):
    """A content-addressed key that already holds bytes not matching its digest must not be
    treated as a dedup hit -- that would return a ref that fails verification."""
    data = b"expected"
    (tmp_path / hashlib.sha256(data).hexdigest()).write_bytes(b"wrong")

    with pytest.raises(ValueError, match="does not match its key"):
        store.put_artifact(data)


def test_put_artifact_lost_race_with_different_content_raises(store, monkeypatch):
    """Race: the key is absent when put_artifact checks, but a concurrent writer publishes
    different bytes before our create-if-absent write. We must not return a ref for our bytes."""
    real_exists = store.exists

    def exists_then_lose_race(key):
        result = real_exists(key)
        if not result:
            store.put(b"concurrent writer's bytes", key)
        return result

    monkeypatch.setattr(store, "exists", exists_then_lose_race)

    with pytest.raises(ValueError, match="already exists with different content"):
        store.put_artifact(b"our bytes", key="contended")
    assert store.get("contended") == b"concurrent writer's bytes"


def test_put_artifact_concurrent_writers_exactly_one_wins(store):
    """Many threads writing different content under the same explicit key: exactly one succeeds,
    every other gets a ValueError, and the stored bytes match the winner's ref."""
    import concurrent.futures

    def write(i):
        try:
            return store.put_artifact(f"writer-{i}".encode() * 1000, key="contended")
        except ValueError:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(write, range(32)))

    winners = [ref for ref in results if ref is not None]
    assert len(winners) == 1
    assert store.get_artifact(winners[0])  # verifies the digest matches what's stored


def test_put_falls_back_to_rename_without_hard_link_support(store, monkeypatch):
    def no_links(src, dst):
        raise PermissionError("hard links not supported on this filesystem")

    monkeypatch.setattr("os.link", no_links)

    assert store.put(b"data", key="k") is None  # unknown -- put_artifact verifies instead
    assert store.get("k") == b"data"
    assert store.put_artifact(b"data", key="k").key == "k"


def test_put_creates_files_with_umask_default_permissions(store, tmp_path):
    reference = tmp_path / "reference-file"
    reference.write_bytes(b"")  # a regular file gets the umask-default mode
    ref = store.put_artifact(b"readable by other processes")

    mode = stat.S_IMODE(os.stat(tmp_path / ref.key).st_mode)
    assert mode == stat.S_IMODE(os.stat(reference).st_mode)


def test_repeated_put_artifact_does_not_reread_unchanged_files(store, monkeypatch):
    """State is re-serialized every step, so re-putting an existing artifact must not re-read
    and re-hash the whole stored file each time."""
    import burr.core.artifacts as artifacts_module

    ref = store.put_artifact(b"large payload" * 1000)

    def no_reads(*args, **kwargs):
        raise AssertionError("stored file was re-read")

    monkeypatch.setattr(artifacts_module, "open", no_reads, raising=False)
    assert store.put_artifact(b"large payload" * 1000) == ref


def test_digest_cache_is_invalidated_when_file_changes(store, tmp_path):
    ref = store.put_artifact(b"original")
    (tmp_path / ref.key).write_bytes(b"modified out of band")

    with pytest.raises(ValueError, match="does not match its key"):
        store.put_artifact(b"original")


def test_digest_cache_is_invalidated_when_file_is_replaced(store, tmp_path):
    """A same-size replacement with the original mtime (e.g. `cp -p`) is caught via the inode."""
    ref = store.put_artifact(b"original")
    path = tmp_path / ref.key
    original = os.stat(path)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"tampered")  # same length as b"original"
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    os.replace(replacement, path)

    with pytest.raises(ValueError, match="does not match its key"):
        store.put_artifact(b"original")


def test_digest_defaults_to_hashing_stored_content(store):
    store.put(b"hash me", key="k")
    assert store.digest("k") == hashlib.sha256(b"hash me").hexdigest()


def test_get_artifact_roundtrip(store):
    data = b"round trip me"
    ref = store.put_artifact(data)

    assert store.get_artifact(ref) == data


def test_get_artifact_verifies_digest_by_default(store, tmp_path):
    data = b"original content"
    ref = store.put_artifact(data, key="mutable-key")

    # simulate corruption/tampering of the underlying stored bytes on disk directly --
    # store.put() is a no-op for an already-existing key, so we bypass it here.
    (tmp_path / "mutable-key").write_bytes(b"tampered content")

    with pytest.raises(ValueError, match="Digest mismatch"):
        store.get_artifact(ref)


def test_get_artifact_skips_verification_when_disabled(store, tmp_path):
    data = b"original content"
    ref = store.put_artifact(data, key="mutable-key")
    (tmp_path / "mutable-key").write_bytes(b"tampered content")

    # no error, just returns the (tampered) bytes as-is
    assert store.get_artifact(ref, verify=False) == b"tampered content"


def test_artifact_ref_read_delegates_to_store(store):
    data = b"delegate read"
    ref = store.put_artifact(data)

    assert ref.read(store) == data


def test_artifact_ref_serde_roundtrip():
    ref = ArtifactRef(key="abc", size_bytes=10, digest="0" * 64, media_type="text/plain")

    serialized = serde.serialize(ref)
    assert serialized[serde.KEY] == "ArtifactRef"
    assert serialized["key"] == "abc"

    deserialized = serde.deserialize(serialized)
    assert deserialized == ref


def test_state_with_artifact_ref_serializes_as_reference_only(store):
    data = b"a very large file we do not want in the DB"
    ref = store.put_artifact(data, media_type="application/pdf")
    s = state.State({"document": ref})

    serialized_state = s.serialize()
    # state.serialize() must only contain the lightweight reference, not the raw bytes
    assert serialized_state["document"] == {
        serde.KEY: "ArtifactRef",
        "key": ref.key,
        "size_bytes": ref.size_bytes,
        "digest": ref.digest,
        "media_type": "application/pdf",
    }


def test_state_deserialize_restores_ref_without_fetching_bytes(store):
    data = b"a very large file we do not want eagerly loaded"
    ref = store.put_artifact(data)
    s = state.State({"document": ref})
    serialized_state = s.serialize()

    restored_state = state.State.deserialize(serialized_state)

    restored_ref = restored_state["document"]
    assert isinstance(restored_ref, ArtifactRef)
    assert restored_ref == ref
    # deserializing state must not read artifact bytes -- only .read()/get_artifact() should
    restored_ref.read(store)  # exercised separately/explicitly, proving it's a distinct step


def test_artifact_ref_deserializes_in_fresh_process_without_explicit_import():
    """Regression test: the ArtifactRef (de)serializer must be registered as a side effect of
    importing ``burr.core`` (transitively, e.g. via ``burr.core.state``) -- not only when a
    caller happens to import ``burr.core.artifacts`` directly first. Runs in a fresh subprocess
    so no other test in this process can have already triggered the registration."""
    script = textwrap.dedent(
        """
        import sys
        assert "burr.core.artifacts" not in sys.modules, (
            "burr.core.artifacts must not already be imported for this to be a valid regression "
            "test"
        )

        from burr.core import serde
        from burr.core.state import State

        serialized = {
            "document": {
                serde.KEY: "ArtifactRef",
                "key": "abc123",
                "size_bytes": 5,
                "digest": "abc123",
                "media_type": "text/plain",
            }
        }
        restored = State.deserialize(serialized)
        ref = restored["document"]
        assert type(ref).__name__ == "ArtifactRef"
        assert ref.key == "abc123"
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


class InMemoryAsyncArtifactStore(AsyncArtifactStore):
    """Minimal in-memory `AsyncArtifactStore` used to exercise the async base-class contract
    (digest computation, explicit-key collision semantics, verification) without needing a real
    I/O-bound backend."""

    def __init__(self):
        self._data: dict = {}

    async def put(self, data: bytes, key: str) -> None:
        # deliberately returns None ("unknown") and overwrites, like a minimal third-party
        # backend -- put_artifact must still verify what's stored rather than trust the write.
        self._data[key] = data

    async def get(self, key: str) -> bytes:
        if key not in self._data:
            raise FileNotFoundError(key)
        return self._data[key]

    async def exists(self, key: str) -> bool:
        return key in self._data


@pytest.fixture
def async_store():
    return InMemoryAsyncArtifactStore()


def test_artifact_store_is_async_false(store):
    assert store.is_async() is False


def test_async_artifact_store_is_async_true(async_store):
    assert async_store.is_async() is True


async def test_async_put_artifact_computes_digest_and_size(async_store):
    data = b"async payload"
    ref = await async_store.put_artifact(data)

    assert ref.digest == hashlib.sha256(data).hexdigest()
    assert ref.size_bytes == len(data)
    assert ref.key == ref.digest  # content-addressed by default


async def test_async_put_artifact_explicit_key_identical_content_is_noop(async_store):
    data = b"same bytes"
    first = await async_store.put_artifact(data, key="mutable")
    second = await async_store.put_artifact(data, key="mutable")

    assert first == second
    assert await async_store.get("mutable") == data


async def test_async_put_artifact_explicit_key_conflicting_content_raises(async_store):
    await async_store.put_artifact(b"first", key="mutable")

    with pytest.raises(ValueError, match="already exists with different content"):
        await async_store.put_artifact(b"second", key="mutable")

    # the original content must be untouched after the rejected write
    assert await async_store.get("mutable") == b"first"


async def test_async_get_artifact_roundtrip(async_store):
    data = b"async roundtrip"
    ref = await async_store.put_artifact(data)

    assert await async_store.get_artifact(ref) == data


async def test_async_get_artifact_verifies_digest_by_default(async_store):
    ref = await async_store.put_artifact(b"original")
    await async_store.put(b"tampered", ref.key)  # simulate corruption/overwrite out-of-band

    with pytest.raises(ValueError, match="Digest mismatch"):
        await async_store.get_artifact(ref)


async def test_async_put_artifact_default_key_with_corrupted_content_raises(async_store):
    data = b"expected"
    async_store._data[hashlib.sha256(data).hexdigest()] = b"wrong"

    with pytest.raises(ValueError, match="does not match its key"):
        await async_store.put_artifact(data)


async def test_async_put_artifact_verifies_when_backend_cannot_confirm_write(async_store):
    """A backend whose put() returns None gets its stored content verified after the write."""
    calls = []
    real_digest = async_store.digest

    async def tracking_digest(key):
        calls.append(key)
        return await real_digest(key)

    async_store.digest = tracking_digest
    ref = await async_store.put_artifact(b"payload", key="k")

    assert calls == ["k"]
    assert ref.key == "k"


async def test_artifact_ref_aread_delegates_to_async_store(async_store):
    data = b"delegate aread"
    ref = await async_store.put_artifact(data)

    assert await ref.aread(async_store) == data
