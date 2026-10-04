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

# try to import to serialize Pandas Objects
#
# DataFrames are stored as parquet files under a configured directory
# (``pandas_kwargs["path"]``). The persisted state records the file name
# relative to that directory; on load the name is resolved against the
# configured directory and must land inside it.
import hashlib
import os
from typing import Optional, Union

import pandas as pd

from burr.core import serde


def _pandas_kwargs_with_path(pandas_kwargs: Optional[dict], operation: str) -> dict:
    """Returns a copy of ``pandas_kwargs``, requiring it to carry a ``path`` entry."""
    if not isinstance(pandas_kwargs, dict) or "path" not in pandas_kwargs:
        raise ValueError(
            f"{operation} a pandas DataFrame requires a `path` entry in `pandas_kwargs` -- "
            "this is the directory where the dataframe is stored as a parquet file. "
            "Pass it through whatever triggers serialization, e.g. "
            '`LocalTrackingClient(..., serde_kwargs={"pandas_kwargs": {"path": "/some/dir"}})` '
            'or `state.serialize(pandas_kwargs={"path": "/some/dir"})`. '
            f"Got pandas_kwargs={pandas_kwargs!r}."
        )
    return pandas_kwargs.copy()


def _resolve_within_base(base_path: Union[str, os.PathLike], stored_path: object) -> str:
    """Resolves a persisted parquet path against the configured directory.

    Serialization records the parquet file name relative to the configured directory.
    Earlier versions recorded the joined path instead, so an absolute value is still
    accepted as long as it resolves to a location inside the configured directory.
    URL-style values and anything resolving outside the directory are rejected.

    :param base_path: the configured directory (``pandas_kwargs["path"]``).
    :param stored_path: the ``path`` value read from persisted state.
    :return: the resolved absolute path of the parquet file.
    """
    if not isinstance(stored_path, str) or not stored_path:
        raise ValueError(f"Persisted parquet path must be a non-empty string, got {stored_path!r}.")
    if "://" in stored_path:
        raise ValueError(
            f"Persisted parquet path {stored_path!r} must be a file name relative to the "
            "configured directory, not a URL."
        )
    real_base = os.path.realpath(os.fspath(base_path))
    candidate = stored_path if os.path.isabs(stored_path) else os.path.join(real_base, stored_path)
    real_candidate = os.path.realpath(candidate)
    try:
        inside = (
            real_candidate != real_base
            and os.path.commonpath([real_base, real_candidate]) == real_base
        )
    except ValueError:
        # commonpath cannot compare the two (e.g. different drives on Windows)
        inside = False
    if not inside:
        raise ValueError(
            f"Persisted parquet path {stored_path!r} resolves outside the configured "
            f"directory {os.fspath(base_path)!r}."
        )
    return real_candidate


@serde.serialize.register(pd.DataFrame)
def serialize_pandas_df(
    value: pd.DataFrame, pandas_kwargs: Optional[dict] = None, **kwargs
) -> dict:
    """Custom serde for pandas dataframes.

    Saves the dataframe to a parquet file under ``pandas_kwargs["path"]`` and records the
    file name, relative to that directory, in the returned dictionary. Pass the same
    ``path`` when deserializing; the recorded name is resolved against it.
    Requires a `path` key in the `pandas_kwargs` dictionary.

    :param value: the pandas dataframe to serialize.
    :param pandas_kwargs: `path` key is required -- this is the directory to save the parquet \
    file in. As well as any other kwargs to pass to the pandas to_parquet function.
    :param kwargs:
    :return:
    """
    kwargs = _pandas_kwargs_with_path(pandas_kwargs, "Serializing")
    hash_object = hashlib.sha256()
    hash_value = str(value.columns) + str(value.shape) + str(value.dtypes)
    hash_object.update(hash_value.encode())

    # Return the hexadecimal representation of the hash
    file_name = f"df_{hash_object.hexdigest()}.parquet"
    base_path = kwargs.pop("path")
    os.makedirs(base_path, exist_ok=True)
    value.to_parquet(path=os.path.join(base_path, file_name), **kwargs)
    return {serde.KEY: "pandas.DataFrame", "path": file_name}


@serde.deserializer.register("pandas.DataFrame")
def deserialize_pandas_df(
    value: dict, pandas_kwargs: Optional[dict] = None, **kwargs
) -> pd.DataFrame:
    """Custom deserializer for pandas dataframes.

    The persisted ``path`` is resolved against ``pandas_kwargs["path"]`` -- the same
    directory used during serialization -- and must resolve to a file inside it.
    Values recorded by earlier versions as absolute paths are accepted when they resolve
    inside that directory. URL-style values and paths outside the directory raise
    ``ValueError``.

    :param value: the dictionary to pull the path from to load the parquet file.
    :param pandas_kwargs: `path` key is required -- the directory the parquet file was saved \
    in. As well as any other kwargs to pass to the pandas read_parquet function.
    :param kwargs:
    :return: pandas dataframe
    """
    kwargs = _pandas_kwargs_with_path(pandas_kwargs, "Deserializing")
    base_path = kwargs.pop("path")
    resolved = _resolve_within_base(base_path, value.get("path"))
    return pd.read_parquet(resolved, **kwargs)
