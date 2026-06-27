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

import pytest

from burr.core.serde import StringDispatch, deserialize, serialize


def test_serialize_primitive_types():
    assert serialize(1) == 1
    assert serialize(1.0) == 1.0
    assert serialize("test") == "test"
    assert serialize(True) is True


def test_serialize_list():
    assert serialize([1, 2, 3]) == [1, 2, 3]
    assert serialize(["a", "b", "c"]) == ["a", "b", "c"]


def test_serialize_dict():
    assert serialize({"key": "value"}) == {"key": "value"}
    assert serialize({"key1": 1, "key2": 2}) == {"key1": 1, "key2": 2}


def test_deserialize_primitive_types():
    assert deserialize(1) == 1
    assert deserialize(1.0) == 1.0
    assert deserialize("test") == "test"
    assert deserialize(True) is True


def test_deserialize_list():
    assert deserialize([1, 2, 3]) == [1, 2, 3]
    assert deserialize(["a", "b", "c"]) == ["a", "b", "c"]


def test_deserialize_dict():
    assert deserialize({"key": "value"}) == {"key": "value"}
    assert deserialize({"key1": 1, "key2": 2}) == {"key1": 1, "key2": 2}


def test_string_dispatch_no_key():
    dispatch = StringDispatch()
    with pytest.raises(ValueError):
        dispatch.call("nonexistent_key")


def test_string_dispatch_with_key():
    dispatch = StringDispatch()
    dispatch.register("test_key")(lambda x: x)
    assert dispatch.call("test_key", "test_value") == "test_value"


def test_string_dispatch_no_key_informative_message():
    dispatch = StringDispatch()
    dispatch.register("known_key")(lambda value: value)
    with pytest.raises(ValueError) as exc_info:
        dispatch.call("nonexistent_key")
    assert "nonexistent_key" in str(exc_info.value)
    assert "known_key" in str(exc_info.value)
    assert "imported" in str(exc_info.value)
