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
import hashlib
import os
from typing import Optional

import pandas as pd

from burr.core import serde


@serde.serialize.register(pd.DataFrame)
def serialize_pandas_df(
    value: pd.DataFrame, pandas_kwargs: Optional[dict] = None, **kwargs
) -> dict:
    """Custom serde for pandas dataframes.

    Saves the dataframe to a parquet file and returns the path to the file.
    Requires a `path` key in the `pandas_kwargs` dictionary.

    :param value: the pandas dataframe to serialize.
    :param pandas_kwargs: `path` key is required -- this is the base path to save the parquet file. As \
    well as any other kwargs to pass to the pandas to_parquet function.
    :param kwargs:
    :return:
    """
    if not isinstance(pandas_kwargs, dict) or "path" not in pandas_kwargs:
        raise ValueError(
            "Serializing a pandas DataFrame requires a `path` entry in `pandas_kwargs` -- "
            "this is the base path where the dataframe is saved as a parquet file. "
            "Pass it through whatever triggers serialization, e.g. "
            '`LocalTrackingClient(..., serde_kwargs={"pandas_kwargs": {"path": "/some/dir"}})` '
            'or `state.serialize(pandas_kwargs={"path": "/some/dir"})`. '
            f"Got pandas_kwargs={pandas_kwargs!r}."
        )
    hash_object = hashlib.sha256()
    hash_value = str(value.columns) + str(value.shape) + str(value.dtypes)
    hash_object.update(hash_value.encode())

    # Return the hexadecimal representation of the hash
    file_name = f"df_{hash_object.hexdigest()}.parquet"
    kwargs = pandas_kwargs.copy()
    base_path: str = kwargs.pop("path")
    if not os.path.exists(base_path):
        os.makedirs(base_path)
    saved_to = os.path.join(base_path, file_name)
    value.to_parquet(path=saved_to, **kwargs)
    return {serde.KEY: "pandas.DataFrame", "path": saved_to}


@serde.deserializer.register("pandas.DataFrame")
def deserialize_pandas_df(
    value: dict, pandas_kwargs: Optional[dict] = None, **kwargs
) -> pd.DataFrame:
    """Custom deserializer for pandas dataframes.

    :param value: the dictionary to pull the path from to load the parquet file.
    :param pandas_kwargs: other args to pass to the pandas read_parquet function. Optional.
    :param kwargs:
    :return: pandas dataframe
    """
    kwargs = pandas_kwargs.copy() if pandas_kwargs is not None else {}
    if "path" in kwargs:
        # remove this to not clash; we already have the full path.
        kwargs.pop("path")
    return pd.read_parquet(value["path"], **kwargs)
