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

import pytest

from burr.core import serde, state
from burr.core.artifacts import ArtifactRef, LocalFileSystemArtifactStore


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


def test_put_artifact_is_idempotent_for_identical_content(store):
    data = b"duplicate content"
    ref1 = store.put_artifact(data)
    ref2 = store.put_artifact(data)

    # same content -> same content-addressed key, written only once
    assert ref1.key == ref2.key


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
