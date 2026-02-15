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

import pandas as pd

from burr.core import serde, state


def test_serde_of_pandas_dataframe(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    og = state.State({"df": df})
    serialized = og.serialize(pandas_kwargs={"path": tmp_path})
    assert serialized["df"][serde.KEY] == "pandas.DataFrame"
    assert serialized["df"]["path"].startswith(str(tmp_path))

    # Verify filename pattern instead of exact hash (hash may change with pandas versions)
    filename = os.path.basename(serialized["df"]["path"])
    assert filename.startswith("df_")
    assert filename.endswith(".parquet")
    # Verify it's a valid SHA256 hash (64 hex characters)
    hash_part = filename[3:-8]  # Remove 'df_' prefix and '.parquet' suffix
    assert len(hash_part) == 64
    assert all(c in "0123456789abcdef" for c in hash_part)

    ng = state.State.deserialize(serialized, pandas_kwargs={"path": tmp_path})
    assert isinstance(ng["df"], pd.DataFrame)
    pd.testing.assert_frame_equal(ng["df"], df)
