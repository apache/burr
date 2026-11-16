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

import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from burr.core import serde, state
from burr.core.artifacts import ArtifactRef, AsyncArtifactStore, LocalFileSystemArtifactStore


@pytest.fixture
def store(tmp_path):
    return LocalFileSystemArtifactStore(root_dir=str(tmp_path))


def _symlink_or_skip(target, link):
    """Create a symlink, or skip the test when the platform cannot.

    Two distinct failure modes have to be handled, both of them environmental rather than a
    defect of the store:

    * Windows without ``SeCreateSymbolicLinkPrivilege`` (developer mode or an elevated shell)
      raises ``OSError`` with ``WinError 1314``;
    * some sandboxed/intercepted filesystems accept the call without raising but do not create a
      reparse point, so the path is not actually a symlink and the escape scenario never exists.

    Verifying the result covers both: the test only runs where a real symlink exists, and it still
    runs on Linux, macOS and CI.
    """
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"cannot create symlinks in this environment: {e}")
    if not link.is_symlink():
        pytest.skip("symlink_to did not create a real symlink in this environment")


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
    _symlink_or_skip(outside_dir, tmp_path / "link")

    with pytest.raises(ValueError):
        store.put(b"malicious", key="link/escape.txt")
    assert not (outside_dir / "escape.txt").exists()


def test_get_rejects_symlinked_escape(store, tmp_path):
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir()
    (outside_dir / "escape.txt").write_bytes(b"outside data")
    _symlink_or_skip(outside_dir, tmp_path / "link")

    with pytest.raises(ValueError):
        store.get("link/escape.txt")


def test_exists_rejects_symlinked_escape(store, tmp_path):
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir()
    _symlink_or_skip(outside_dir, tmp_path / "link")

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


def test_put_falls_back_to_rename_without_hard_link_support(store, monkeypatch, tmp_path):
    """A filesystem without hard links must still be usable -- or fail loudly, never clobber.

    Regression for the P0 fallback race: the old ``except OSError: os.replace(...)``
    silently overwrote a concurrently published artifact. On Windows ``os.rename`` is
    itself an atomic no-replace operation, so the fallback is safe. On POSIX,
    ``rename(2)`` replaces the destination, so there is no safe stdlib fallback and
    the store must refuse the write rather than risk corrupting another writer.
    """

    def no_links(src, dst):
        raise PermissionError("hard links not supported on this filesystem")

    monkeypatch.setattr("os.link", no_links)

    if os.name == "nt":
        assert store.put(b"data", key="k") is None  # unknown -- put_artifact verifies instead
        assert store.get("k") == b"data"
        assert store.put_artifact(b"data", key="k").key == "k"
    else:
        with pytest.raises(OSError, match="hard links are unavailable"):
            store.put(b"data", key="k")
        # A refused write must leave neither a (possibly empty) artifact nor a temp file.
        assert not store.exists("k")

    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".tmp-artifact-")] == []


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


# ---------------------------------------------------------------------------
# P0 regression: atomic create-if-absent publication on the no-hard-link path.
#
# The historical ``except OSError: os.replace(...)`` fallback silently replaced a
# target published by a concurrent writer, invalidating an ArtifactRef that had
# already been returned to its caller. The fix publishes only via os.link() (an
# atomic create-if-absent on every platform) or, on Windows, os.rename() -- which
# is MoveFileExW *without* MOVEFILE_REPLACE_EXISTING and therefore also refuses an
# existing destination. On POSIX rename(2) replaces the destination, so no safe
# stdlib fallback exists and the store fails loudly instead.
#
# ``_FALLBACK_WRITES`` is True only where a safe no-replace publication primitive
# is available, so the whole matrix runs unchanged on Linux/macOS CI as well.
# ---------------------------------------------------------------------------

_FALLBACK_WRITES = os.name == "nt"
_REAL_IO_ERRNOS = (errno.ENOSPC, errno.EIO, errno.EROFS, errno.EDQUOT, errno.EMLINK)
_CAPABILITY_ERRNOS = (
    errno.EPERM,
    errno.EACCES,
    errno.EOPNOTSUPP,
    errno.ENOSYS,
    errno.EXDEV,
)


def _force_no_hard_links(monkeypatch, code=errno.EPERM):
    """Make os.link() fail as it does on a filesystem without hard-link support."""

    def no_links(src, dst, **kwargs):
        raise OSError(code, "hard links not supported on this filesystem")

    monkeypatch.setattr("os.link", no_links)


def _no_temp_leftovers(root):
    return [name for name in os.listdir(root) if name.startswith(".tmp-artifact-")]


# --- A. normal hard-link path -------------------------------------------------


def test_hard_link_path_never_calls_replace(store, monkeypatch, tmp_path):
    """The ordinary path must publish with os.link() alone -- no overwriting primitive."""
    from unittest import mock

    with mock.patch("os.replace") as replace, mock.patch("os.rename") as rename:
        assert store.put(b"link-path", key="k") is True

    replace.assert_not_called()
    rename.assert_not_called()
    assert store.get("k") == b"link-path"
    assert _no_temp_leftovers(str(tmp_path)) == []


def test_hard_link_path_existing_key_conflict_never_replaces(store, monkeypatch, tmp_path):
    from unittest import mock

    assert store.put(b"original", key="k") is True
    with mock.patch("os.replace") as replace:
        assert store.put(b"different", key="k") is False

    replace.assert_not_called()
    assert store.get("k") == b"original"
    assert _no_temp_leftovers(str(tmp_path)) == []


def test_hard_link_path_concurrent_writers_deterministic(store, tmp_path):
    """Barrier-forced race on the normal path: exactly one winner, no stale refs."""
    from unittest import mock

    key = "contended"
    payloads = [b"A" * 4096, b"B" * 4096]
    # Synchronise at the END of the temp-file write, not at os.link: put_artifact()
    # short-circuits on exists(), so a barrier at publish time could deadlock if
    # one writer saw the other's file. At fsync time nobody has published yet, so
    # both writers are guaranteed to reach it.
    barrier = threading.Barrier(2)
    real_fsync = os.fsync
    outcome = {}

    def gated_fsync(fd):
        real_fsync(fd)
        barrier.wait(timeout=20)

    def writer(name, data):
        try:
            outcome[name] = ("ok", store.put_artifact(data, key=key))
        except BaseException as exc:  # noqa: BLE001
            outcome[name] = ("error", exc)

    with mock.patch("os.fsync", gated_fsync):
        threads = [
            threading.Thread(target=writer, args=(f"w{i}", payloads[i]), name=f"w{i}")
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert all(not t.is_alive() for t in threads), "deadlock in deterministic harness"

    winners = [(name, ref) for name, (status, ref) in outcome.items() if status == "ok"]
    assert len(winners) == 1, f"expected exactly one winner, got {outcome}"
    losers = [exc for status, exc in outcome.values() if status == "error"]
    assert len(losers) == 1 and isinstance(losers[0], ValueError), outcome
    _, ref = winners[0]
    assert store.get_artifact(ref)  # the returned ref still verifies
    assert hashlib.sha256(store.get(key)).hexdigest() == ref.digest
    assert _no_temp_leftovers(str(tmp_path)) == []


# --- B. no-hard-link fallback path -------------------------------------------


def test_fallback_single_writer_roundtrip_and_digest(store, monkeypatch, tmp_path):
    _force_no_hard_links(monkeypatch)

    if _FALLBACK_WRITES:
        result = store.put(b"fallback-bytes", key="k")
        assert result is None  # "unknown" -> put_artifact verifies what landed on disk
        assert store.get("k") == b"fallback-bytes"
        ref = store.put_artifact(b"fallback-bytes", key="k")
        assert ref.digest == hashlib.sha256(b"fallback-bytes").hexdigest()
        assert store.get_artifact(ref) == b"fallback-bytes"
    else:
        with pytest.raises(OSError, match="hard links are unavailable"):
            store.put(b"fallback-bytes", key="k")
        assert not store.exists("k")

    assert _no_temp_leftovers(str(tmp_path)) == []


def test_fallback_never_overwrites_target_appearing_after_existence_check(
    store, monkeypatch, tmp_path
):
    """TOCTOU case: a competitor publishes in the window between our check and publish."""
    competitor = b"CONCURRENT-WINNER"
    target = tmp_path / "contended"

    def link_fails_after_competitor_publishes(src, dst, **kwargs):
        # Runs strictly after put()'s existence check. Another writer wins the race here.
        target.write_bytes(competitor)
        raise OSError(errno.EPERM, "hard links not supported on this filesystem")

    monkeypatch.setattr("os.link", link_fails_after_competitor_publishes)

    if _FALLBACK_WRITES:
        assert store.put(b"OUR-BYTES", key="contended") is False
        with pytest.raises(ValueError, match="already exists with different content"):
            store.put_artifact(b"OUR-BYTES", key="contended")
    else:
        with pytest.raises(OSError, match="hard links are unavailable"):
            store.put(b"OUR-BYTES", key="contended")

    assert target.read_bytes() == competitor, "concurrent winner's bytes were clobbered"
    assert _no_temp_leftovers(str(tmp_path)) == []


def test_fallback_concurrent_writers_never_both_succeed(store, tmp_path):
    """The deterministic P0 repro, as a permanent regression test.

    Two writers, same explicit key, different content, hard links unavailable.
    A Barrier forces both past the existence checks before either publishes;
    an Event lets writer-a fully return (including digest verification) before
    writer-b publishes. No sleeps, no reliance on thread scheduling.

    With the old ``os.replace`` fallback both writers returned a successful ref
    and writer-a's ref was silently invalidated. The fixed implementation must
    never allow that.
    """
    from unittest import mock

    key = "contended"
    payloads = {"writer-a": b"A" * 8192, "writer-b": b"B" * 8192}
    real_rename, real_replace = os.rename, os.replace
    link_barrier = threading.Barrier(2)
    a_returned = threading.Event()
    outcome = {}

    def no_hardlinks(src, dst, **kwargs):
        link_barrier.wait(timeout=20)  # both writers are now at the publish point
        raise OSError(errno.EPERM, "hard links not supported")

    def controlled_publish(real):
        def _publish(src, dst, **kwargs):
            if threading.current_thread().name == "writer-a":
                return real(src, dst)
            # writer-a has fully returned (ref already handed to its caller).
            assert a_returned.wait(timeout=20), "writer-a never returned"
            return real(src, dst)

        return _publish

    def writer(name, data):
        try:
            outcome[name] = ("ok", store.put_artifact(data, key=key))
        except BaseException as exc:  # noqa: BLE001
            outcome[name] = ("error", exc)
        finally:
            if name == "writer-a":
                a_returned.set()

    # Patch both primitives: the buggy code published via os.replace, the fixed
    # code publishes via os.rename. This test fails on either implementation if
    # the publication is allowed to clobber an existing target.
    with mock.patch("os.link", no_hardlinks), mock.patch(
        "os.rename", controlled_publish(real_rename)
    ), mock.patch("os.replace", controlled_publish(real_replace)):
        threads = [
            threading.Thread(target=writer, args=(name, data), name=name)
            for name, data in payloads.items()
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert all(not t.is_alive() for t in threads), "deadlock in deterministic harness"

    successes = [(name, ref) for name, (status, ref) in outcome.items() if status == "ok"]
    errors = [exc for status, exc in outcome.values() if status == "error"]

    # Property 2 & 5: at most one success, and every returned ref stays valid.
    assert len(successes) <= 1, f"both writers succeeded: {outcome}"
    for _, ref in successes:
        assert store.get_artifact(ref), "a returned ArtifactRef was invalidated"
        assert hashlib.sha256(store.get(key)).hexdigest() == ref.digest

    if _FALLBACK_WRITES:
        assert len(successes) == 1, f"expected exactly one winner: {outcome}"
        assert len(errors) == 1 and isinstance(errors[0], ValueError), outcome
        assert "already exists with different content" in str(errors[0])
        assert store.get(key) in payloads.values()
    else:
        assert successes == [], outcome
        assert len(errors) == 2
        assert all(isinstance(e, OSError) for e in errors), outcome
        assert not store.exists(key)

    assert _no_temp_leftovers(str(tmp_path)) == []


@pytest.mark.parametrize("code", _REAL_IO_ERRNOS)
def test_fallback_real_io_errors_propagate_and_write_nothing(store, monkeypatch, tmp_path, code):
    """Property 8: ENOSPC/EIO/EROFS/EDQUOT/EMLINK are not 'no hard link support'."""

    def link_fails(src, dst, **kwargs):
        raise OSError(code, "simulated real I/O failure")

    monkeypatch.setattr("os.link", link_fails)

    with pytest.raises(OSError) as exc_info:
        store.put(b"payload", key="fresh-key")
    assert exc_info.value.errno == code, "the original errno must not be masked"
    assert not store.exists("fresh-key")
    assert _no_temp_leftovers(str(tmp_path)) == []


def test_fallback_existing_key_conflict_preserves_original(store, monkeypatch, tmp_path):
    """With hard links unavailable, a conflicting explicit key still cannot be replaced."""
    original = b"PRECIOUS-EXISTING-CONTENT"
    store.put_artifact(original, key="precious")
    _force_no_hard_links(monkeypatch)

    with pytest.raises(ValueError, match="already exists with different content"):
        store.put_artifact(b"NEW-CONTENT", key="precious")

    assert (tmp_path / "precious").read_bytes() == original
    assert _no_temp_leftovers(str(tmp_path)) == []


def test_fallback_real_io_error_never_destroys_existing_artifact(store, monkeypatch, tmp_path):
    """A genuine I/O failure must never be laundered into a clobbering write.

    Regression for the old ``except OSError`` behaviour, which treated ENOSPC as
    "no hard links" and published via os.replace(). With a pre-existing artifact,
    the existence check short-circuits put(), so we assert both that the error is
    propagated on a fresh key and that the previously stored object is untouched.
    """
    original = b"PRECIOUS-EXISTING-CONTENT"
    ref = store.put_artifact(original, key="precious")

    def link_enospc(src, dst, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("os.link", link_enospc)

    # A conflicting write on the existing key must still be rejected, not replaced.
    with pytest.raises(ValueError, match="already exists with different content"):
        store.put_artifact(b"NEW-CONTENT", key="precious")

    # On a fresh key the real I/O error reaches the publish step and propagates.
    with pytest.raises(OSError) as exc_info:
        store.put_artifact(b"NEW-CONTENT", key="fresh-under-enospc")
    assert exc_info.value.errno == errno.ENOSPC

    assert store.get_artifact(ref) == original
    assert not store.exists("fresh-under-enospc")
    assert _no_temp_leftovers(str(tmp_path)) == []


@pytest.mark.parametrize("code", _CAPABILITY_ERRNOS)
def test_fallback_capability_errnos_take_safe_path(store, monkeypatch, tmp_path, code):
    """Capability errors are handled safely, on every platform's errno flavour."""
    _force_no_hard_links(monkeypatch, code=code)

    if _FALLBACK_WRITES:
        assert store.put(b"data", key="k") is None
        assert store.get("k") == b"data"
    else:
        with pytest.raises(OSError, match="hard links are unavailable"):
            store.put(b"data", key="k")
        assert not store.exists("k")
    assert _no_temp_leftovers(str(tmp_path)) == []


def test_fallback_plain_oserror_without_errno_takes_safe_path(store, monkeypatch, tmp_path):
    """Filesystem shims may raise OSError without an errno; still never clobber."""

    def no_links(src, dst):
        raise PermissionError("hard links not supported on this filesystem")

    monkeypatch.setattr("os.link", no_links)

    if _FALLBACK_WRITES:
        assert store.put(b"data", key="k") is None
        assert store.get("k") == b"data"
    else:
        with pytest.raises(OSError, match="hard links are unavailable"):
            store.put(b"data", key="k")
        assert not store.exists("k")
    assert _no_temp_leftovers(str(tmp_path)) == []


def test_fallback_interrupted_write_cleans_temp_files(store, monkeypatch, tmp_path):
    """A failure during the write must not leave a target OR a temp file behind."""
    from unittest import mock

    def failing_fsync(fd):
        raise OSError("simulated crash mid-write")

    _force_no_hard_links(monkeypatch)
    with mock.patch("os.fsync", failing_fsync):
        with pytest.raises(OSError):
            store.put(b"x" * 1000, key="flaky")

    assert not store.exists("flaky")
    assert _no_temp_leftovers(str(tmp_path)) == []
    monkeypatch.undo()
    assert store.put(b"good", key="flaky") is True
    assert store.get("flaky") == b"good"


# --- cross-process atomicity (real OS processes, file gate, no sleeps) --------

_CROSS_PROCESS_CHILD = textwrap.dedent(
    """
    import errno
    import json
    import os
    import sys
    import time

    repo, store_dir, gate_dir, name, force_fallback = sys.argv[1:6]
    sys.path.insert(0, repo)
    from burr.core.artifacts import LocalFileSystemArtifactStore

    if force_fallback == "1":
        def no_links(src, dst, **kwargs):
            raise OSError(errno.EPERM, "hard links not supported")
        os.link = no_links

    data = bytes([65 + int(name)]) * 4096
    with open(os.path.join(gate_dir, "ready-" + name), "w") as f:
        f.write("ready")
    go = os.path.join(gate_dir, "go")
    deadline = time.monotonic() + 30
    while not os.path.exists(go):
        if time.monotonic() > deadline:
            raise SystemExit("gate timeout")

    store = LocalFileSystemArtifactStore(root_dir=store_dir)
    try:
        ref = store.put_artifact(data, key="contended")
        result = {"status": "ok", "digest": ref.digest, "data": data.hex()}
    except BaseException as exc:
        result = {"status": "error", "type": type(exc).__name__, "msg": str(exc)[:200]}
    with open(os.path.join(gate_dir, "out-" + name + ".json"), "w") as f:
        json.dump(result, f)
    """
)


@pytest.mark.parametrize(
    "force_fallback", [False, True], ids=["hard-link-path", "no-hard-link-fallback"]
)
def test_cross_process_publish_is_atomic(tmp_path, force_fallback):
    """N independent OS processes race on one key; publication must be atomic.

    The gate file releases every process at the same instant, so this is a real
    cross-process race, not a threaded approximation. No sleeps are used.
    """
    n = 8
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    store_dir = tmp_path / "store"
    gate_dir = tmp_path / "gate"
    store_dir.mkdir()
    gate_dir.mkdir()

    procs = []
    for i in range(n):
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _CROSS_PROCESS_CHILD,
                    repo_root,
                    str(store_dir),
                    str(gate_dir),
                    str(i),
                    "1" if force_fallback else "0",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    try:
        deadline = time.monotonic() + 30
        while len([p for p in os.listdir(gate_dir) if p.startswith("ready-")]) < n:
            assert time.monotonic() < deadline, "children never became ready"
        with open(gate_dir / "go", "w") as f:
            f.write("go")
        for p in procs:
            _, err = p.communicate(timeout=30)
            assert p.returncode == 0, f"child failed rc={p.returncode}: {err.strip()[:300]}"
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()

    results = []
    for i in range(n):
        with open(gate_dir / f"out-{i}.json") as f:
            results.append(json.load(f))

    winners = [r for r in results if r["status"] == "ok"]
    errors = [r for r in results if r["status"] == "error"]
    verify_store = LocalFileSystemArtifactStore(root_dir=str(store_dir))
    target = store_dir / "contended"

    # On POSIX + no-hard-link there is no safe stdlib fallback: all writers must
    # refuse loudly, and nothing may be published. Everywhere else exactly one wins.
    expect_winner = (not force_fallback) or _FALLBACK_WRITES
    if expect_winner:
        assert len(winners) == 1, f"expected exactly one cross-process winner: {results}"
        assert len(errors) == n - 1
        assert all(e["type"] == "ValueError" for e in errors), results
        on_disk = target.read_bytes()
        assert hashlib.sha256(on_disk).hexdigest() == winners[0]["digest"]
        assert on_disk == bytes.fromhex(winners[0]["data"])
        ref = ArtifactRef(
            key="contended",
            size_bytes=len(on_disk),
            digest=winners[0]["digest"],
        )
        assert verify_store.get_artifact(ref) == on_disk
    else:
        assert winners == [], results
        assert len(errors) == n
        assert all(e["type"] == "OSError" for e in errors), results
        assert not target.exists()

    assert _no_temp_leftovers(str(store_dir)) == []


# --- C/D. data integrity, API & file-format compatibility --------------------


def test_public_api_and_tri_state_contract_unchanged(store):
    """The fix must not change the ArtifactStore API or put()'s documented tri-state."""
    import inspect

    from burr.core.artifacts import ArtifactStore

    assert isinstance(store, ArtifactStore)
    assert store.is_async() is False
    assert list(inspect.signature(store.put).parameters) == ["data", "key"]
    assert list(inspect.signature(store.put_artifact).parameters) == [
        "data",
        "media_type",
        "key",
    ]
    assert store.put(b"first", key="k") is True
    assert store.put(b"second", key="k") is False
    ref = store.put_artifact(b"third", media_type="text/plain", key="k2")
    assert ref.key == "k2"
    assert ref.size_bytes == len(b"third")
    assert ref.digest == hashlib.sha256(b"third").hexdigest()
    assert ref.media_type == "text/plain"


def test_stored_artifact_is_a_regular_file_with_unchanged_format(store, tmp_path):
    """On-disk format must remain a plain file holding exactly the raw bytes."""
    data = b"\x00\x01binary\xffpayload"
    ref = store.put_artifact(data, key="blob")
    path = tmp_path / "blob"

    assert path.is_file() and not path.is_symlink()
    assert path.read_bytes() == data
    assert os.stat(path).st_size == ref.size_bytes
    assert store.digest("blob") == ref.digest


def test_other_artifact_store_implementations_unaffected():
    """The base class contract is untouched: a third-party sync store still works."""
    from burr.core.artifacts import ArtifactStore

    class DictStore(ArtifactStore):
        def __init__(self):
            self.data = {}

        def put(self, data, key):
            if key in self.data:
                return False
            self.data[key] = data
            return True

        def get(self, key):
            return self.data[key]

        def exists(self, key):
            return key in self.data

    store = DictStore()
    ref = store.put_artifact(b"payload", key="k")
    assert store.put_artifact(b"payload", key="k") == ref
    with pytest.raises(ValueError, match="already exists with different content"):
        store.put_artifact(b"other", key="k")
    assert store.get_artifact(ref) == b"payload"


# ---------------------------------------------------------------------------------------------
# PHASE 7-F: the refusal must not blame the filesystem when a policy may be the cause
# ---------------------------------------------------------------------------------------------


@pytest.mark.skipif(
    os.name == "nt", reason="Windows takes the no-replace rename fallback instead of refusing"
)
@pytest.mark.parametrize("code", [errno.EACCES, errno.EPERM, errno.EOPNOTSUPP])
def test_publish_refusal_names_both_possible_causes(store, monkeypatch, tmp_path, code):
    """Refusing to publish must not assert a single cause.

    The temp file is created in the destination directory, so directory write permission is
    already proven; what remains is either a filesystem without hard-link support or a security
    policy blocking the link itself. The message names the actual errno and both possibilities,
    so an operator is not sent after the wrong fix.
    """
    _force_no_hard_links(monkeypatch, code=code)

    with pytest.raises(OSError) as exc_info:
        store.put(b"data", key="k")

    message = str(exc_info.value)
    assert "hard links are unavailable" in message
    assert "security policy" in message
    assert errno.errorcode.get(code, "") in message
    assert not store.exists("k")
    assert _no_temp_leftovers(str(tmp_path)) == []


@pytest.mark.skipif(
    os.name == "nt", reason="Windows takes the no-replace rename fallback instead of refusing"
)
def test_publish_refusal_never_uses_os_replace(store, monkeypatch, tmp_path):
    """The refusal path must not fall back to a clobbering replace."""
    _force_no_hard_links(monkeypatch, code=errno.EOPNOTSUPP)

    def _forbidden(*args, **kwargs):
        raise AssertionError("os.replace must never be used to publish")

    monkeypatch.setattr("os.replace", _forbidden)
    with pytest.raises(OSError, match="hard links are unavailable"):
        store.put(b"data", key="k")
    assert not store.exists("k")


@pytest.mark.skipif(
    os.name == "nt", reason="Windows takes the no-replace rename fallback instead of refusing"
)
@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EIO, errno.EROFS, errno.EDQUOT, errno.EMLINK])
def test_real_io_errors_propagate_unchanged(store, monkeypatch, tmp_path, code):
    """Genuine I/O failures are not capability errors and must not be relabelled."""
    _force_no_hard_links(monkeypatch, code=code)

    with pytest.raises(OSError) as exc_info:
        store.put(b"data", key="k")

    assert exc_info.value.errno == code
    assert "hard links are unavailable" not in str(exc_info.value)
    assert not store.exists("k")
    assert _no_temp_leftovers(str(tmp_path)) == []
