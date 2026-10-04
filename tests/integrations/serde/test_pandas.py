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

import os
import sys

import pandas as pd
import pytest

from burr.core import serde, state


def _write_parquet(path, df) -> str:
    """Writes ``df`` to ``path`` (creating parent dirs) and returns the path as a string."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_parquet(path)
    assert os.path.exists(path)
    return str(path)


def _persisted(path) -> dict:
    """Builds a persisted-state dict pointing the dataframe field at ``path``."""
    return {"df": {serde.KEY: "pandas.DataFrame", "path": path}}


def test_serde_of_pandas_dataframe(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    og = state.State({"df": df})
    serialized = og.serialize(pandas_kwargs={"path": tmp_path})
    assert serialized["df"][serde.KEY] == "pandas.DataFrame"

    # The recorded path is the file name relative to the configured directory.
    stored = serialized["df"]["path"]
    assert not os.path.isabs(stored)
    assert os.path.basename(stored) == stored
    assert os.path.exists(tmp_path / stored)

    # Verify filename pattern instead of exact hash (hash may change with pandas versions)
    assert stored.startswith("df_")
    assert stored.endswith(".parquet")
    # Verify it's a valid SHA256 hash (64 hex characters)
    hash_part = stored[3:-8]  # Remove 'df_' prefix and '.parquet' suffix
    assert len(hash_part) == 64
    assert all(c in "0123456789abcdef" for c in hash_part)

    ng = state.State.deserialize(serialized, pandas_kwargs={"path": tmp_path})
    assert isinstance(ng["df"], pd.DataFrame)
    pd.testing.assert_frame_equal(ng["df"], df)


def test_serde_of_pandas_dataframe_with_relative_base_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    df = pd.DataFrame({"a": [1, 2, 3]})
    serialized = state.State({"df": df}).serialize(pandas_kwargs={"path": "data"})
    assert os.path.exists(tmp_path / "data" / serialized["df"]["path"])
    ng = state.State.deserialize(serialized, pandas_kwargs={"path": "data"})
    pd.testing.assert_frame_equal(ng["df"], df)


def test_serialize_pandas_df_without_pandas_kwargs_raises_informative_error():
    df = pd.DataFrame({"a": [1, 2, 3]})
    og = state.State({"df": df})
    with pytest.raises(ValueError) as exc_info:
        og.serialize()
    assert "Failed to serialize state field 'df'" in str(exc_info.value)
    assert "pandas_kwargs" in str(exc_info.value)
    assert "path" in str(exc_info.value)


def test_serialize_pandas_df_without_path_raises_informative_error():
    df = pd.DataFrame({"a": [1, 2, 3]})
    og = state.State({"df": df})
    with pytest.raises(ValueError) as exc_info:
        og.serialize(pandas_kwargs={"compression": "snappy"})
    assert "path" in str(exc_info.value)


def test_deserialize_pandas_df_without_path_raises_informative_error(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    serialized = state.State({"df": df}).serialize(pandas_kwargs={"path": tmp_path})
    for pandas_kwargs in ({}, None, {"columns": ["a"]}):
        with pytest.raises(ValueError) as exc_info:
            state.State.deserialize(serialized, pandas_kwargs=pandas_kwargs)
        assert "Failed to deserialize state field 'df'" in str(exc_info.value)
        assert "pandas_kwargs" in str(exc_info.value)
        assert "path" in str(exc_info.value)


def test_deserialize_pandas_df_passes_through_read_kwargs(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    serialized = state.State({"df": df}).serialize(pandas_kwargs={"path": tmp_path})
    ng = state.State.deserialize(serialized, pandas_kwargs={"path": tmp_path, "columns": ["a"]})
    pd.testing.assert_frame_equal(ng["df"], df[["a"]])


def test_deserialize_pandas_df_accepts_legacy_absolute_path_inside_base(tmp_path):
    # Earlier versions recorded the joined path; it still loads when it is inside the base.
    df = pd.DataFrame({"a": [1, 2, 3]})
    legacy = _write_parquet(tmp_path / "df_legacy.parquet", df)
    assert os.path.isabs(legacy)
    ng = state.State.deserialize(_persisted(legacy), pandas_kwargs={"path": tmp_path})
    pd.testing.assert_frame_equal(ng["df"], df)


def test_deserialize_pandas_df_accepts_nested_relative_path_inside_base(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3]})
    _write_parquet(tmp_path / "nested" / "df.parquet", df)
    ng = state.State.deserialize(
        _persisted(os.path.join("nested", "df.parquet")), pandas_kwargs={"path": tmp_path}
    )
    pd.testing.assert_frame_equal(ng["df"], df)


def test_deserialize_pandas_df_rejects_parent_directory_path(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3]})
    base = tmp_path / "base"
    base.mkdir()
    # The target exists, so the failure is the resolution rule rather than a missing file.
    _write_parquet(tmp_path / "outside.parquet", df)
    with pytest.raises(ValueError) as exc_info:
        state.State.deserialize(_persisted("../outside.parquet"), pandas_kwargs={"path": base})
    assert "resolves outside the configured directory" in str(exc_info.value)


def test_deserialize_pandas_df_rejects_absolute_path_outside_base(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3]})
    base = tmp_path / "base"
    base.mkdir()
    outside = _write_parquet(tmp_path / "outside.parquet", df)
    with pytest.raises(ValueError) as exc_info:
        state.State.deserialize(_persisted(outside), pandas_kwargs={"path": base})
    assert "resolves outside the configured directory" in str(exc_info.value)


def test_deserialize_pandas_df_rejects_base_directory_itself(tmp_path):
    for stored in (".", "", str(tmp_path)):
        with pytest.raises(ValueError):
            state.State.deserialize(_persisted(stored), pandas_kwargs={"path": tmp_path})


@pytest.mark.parametrize(
    "stored",
    [
        "http://example.com/df.parquet",
        "https://example.com/df.parquet",
        "s3://bucket/df.parquet",
        "gs://bucket/df.parquet",
        "file:///tmp/df.parquet",
    ],
)
def test_deserialize_pandas_df_rejects_url_paths(tmp_path, stored):
    with pytest.raises(ValueError) as exc_info:
        state.State.deserialize(_persisted(stored), pandas_kwargs={"path": tmp_path})
    assert "not a URL" in str(exc_info.value)


@pytest.mark.parametrize("stored", [None, 123, ["df.parquet"]])
def test_deserialize_pandas_df_rejects_non_string_path(tmp_path, stored):
    with pytest.raises(ValueError) as exc_info:
        state.State.deserialize(_persisted(stored), pandas_kwargs={"path": tmp_path})
    assert "non-empty string" in str(exc_info.value)


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privileges on Windows")
def test_deserialize_pandas_df_rejects_symlink_escaping_base(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3]})
    base = tmp_path / "base"
    base.mkdir()
    outside = _write_parquet(tmp_path / "outside.parquet", df)
    os.symlink(outside, base / "link.parquet")
    with pytest.raises(ValueError) as exc_info:
        state.State.deserialize(_persisted("link.parquet"), pandas_kwargs={"path": base})
    assert "resolves outside the configured directory" in str(exc_info.value)
