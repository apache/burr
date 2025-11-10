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

from typing import Any

import pytest

from burr.core import Action, Graph
from burr.core.state import State, register_field_serde
from burr.core.typing import TypingSystem


def test_state_access():
    state = State({"foo": "bar"})
    assert state["foo"] == "bar"


def test_state_access_missing():
    state = State({"foo": "bar"})
    with pytest.raises(KeyError):
        _ = state["baz"]


def test_state_get():
    state = State({"foo": "bar"})
    assert state.get("foo") == "bar"


def test_state_get_missing():
    state = State({"foo": "bar"})
    assert state.get("baz") is None


def test_state_get_missing_default():
    state = State({"foo": "bar"})
    assert state.get("baz", "qux") == "qux"


def test_state_in():
    state = State({"foo": "bar"})
    assert "foo" in state
    assert "baz" not in state


def test_state_get_all():
    state = State({"foo": "bar", "baz": "qux"})
    assert state.get_all() == {"foo": "bar", "baz": "qux"}


def test_state_merge():
    state = State({"foo": "bar", "baz": "qux"})
    other = State({"foo": "baz", "quux": "corge"})
    merged = state.merge(other)
    assert merged.get_all() == {"foo": "baz", "baz": "qux", "quux": "corge"}


def test_state_subset():
    state = State({"foo": "bar", "baz": "qux"})
    subset = state.subset("foo")
    assert subset.get_all() == {"foo": "bar"}


def test_state_append():
    state = State({"foo": ["bar"]})
    appended = state.append(foo="baz")
    assert appended.get_all() == {"foo": ["bar", "baz"]}


def test_state_extend():
    state = State({"foo": ["bar"]})
    extended = state.extend(foo=["baz", "qux"])
    assert extended.get_all() == {"foo": ["bar", "baz", "qux"]}


def test_state_append_multiple_keys():
    state = State({"foo": ["bar"], "baz": [1]})
    appended = state.append(foo="baz", baz=2)
    assert appended.get_all() == {"foo": ["bar", "baz"], "baz": [1, 2]}


def test_state_extend_multiple_keys():
    state = State({"foo": ["bar"], "baz": [1]})
    extended = state.extend(foo=["baz"], baz=[2, 3])
    assert extended.get_all() == {"foo": ["bar", "baz"], "baz": [1, 2, 3]}


def test_state_update():
    state = State({"foo": "bar", "baz": "qux"})
    updated = state.update(foo="baz")
    assert updated.get_all() == {"foo": "baz", "baz": "qux"}


def test_state_init():
    state = State({"foo": "bar", "baz": "qux"})
    assert state.get_all() == {"foo": "bar", "baz": "qux"}


def test_state_wipe_delete():
    state = State({"foo": "bar", "baz": "qux"})
    wiped = state.wipe(delete=["foo"])
    assert wiped.get_all() == {"baz": "qux"}


def test_state_wipe_keep():
    state = State({"foo": "bar", "baz": "qux"})
    wiped = state.wipe(keep=["foo"])
    assert wiped.get_all() == {"foo": "bar"}


def test_state_append_validate_failure():
    state = State({"foo": "bar"})
    with pytest.raises(ValueError, match="non-appendable"):
        state.append(foo="baz")


def test_state_extend_validate_failure():
    state = State({"foo": "bar"})
    with pytest.raises(ValueError, match="non-extendable"):
        state.extend(foo=["baz", "qux"], bar=["quux"])


def test_state_increment():
    state = State({"foo": 1})
    incremented = state.increment(foo=2, bar=5)
    assert incremented.get_all() == {"foo": 3, "bar": 5}


def test_state_increment_validate_failure():
    state = State({"foo": "bar"})
    with pytest.raises(ValueError, match="non-integer"):
        state.increment(foo="baz", bar="qux")


def test_field_level_serde():
    def my_field_serializer(value: str, **kwargs) -> dict:
        serde_value = f"serialized_{value}"
        return {"value": serde_value}

    def my_field_deserializer(value: dict, **kwargs) -> str:
        serde_value = value["value"]
        return serde_value.replace("serialized_", "")

    register_field_serde("my_field", my_field_serializer, my_field_deserializer)
    state = State({"foo": {"hi": "world"}, "baz": "qux", "my_field": "testing 123"})
    assert state.serialize() == {
        "foo": {"hi": "world"},
        "baz": "qux",
        "my_field": {"value": "serialized_testing 123"},
    }
    state = State.deserialize(
        {"foo": {"hi": "world"}, "baz": "qux", "my_field": {"value": "serialized_testing 123"}}
    )
    assert state.get_all() == {"foo": {"hi": "world"}, "baz": "qux", "my_field": "testing 123"}


def test_field_level_serde_bad_serde_function():
    def my_field_serializer(value: str, **kwargs) -> str:
        # bad function
        serde_value = f"serialized_{value}"
        return serde_value

    def my_field_deserializer(value: dict, **kwargs) -> str:
        serde_value = value["value"]
        return serde_value.replace("serialized_", "")

    register_field_serde("my_field", my_field_serializer, my_field_deserializer)
    state = State({"foo": {"hi": "world"}, "baz": "qux", "my_field": "testing 123"})
    with pytest.raises(ValueError):
        state.serialize()


def test_register_field_serde_check_no_kwargs():
    def my_field_serializer(value: str) -> dict:
        serde_value = f"serialized_{value}"
        return {"value": serde_value}

    def my_field_deserializer(value: dict) -> str:
        serde_value = value["value"]
        return serde_value.replace("serialized_", "")

    with pytest.raises(ValueError):
        # serializer & deserializer missing kwargs
        register_field_serde("my_field", my_field_serializer, my_field_deserializer)

    def my_field_serializer(value: str, **kwargs) -> dict:
        serde_value = f"serialized_{value}"
        return {"value": serde_value}

    with pytest.raises(ValueError):
        # deserializer still bad
        register_field_serde("my_field", my_field_serializer, my_field_deserializer)


class SimpleTypingSystem(TypingSystem[Any]):
    def state_type(self) -> type[Any]:
        raise NotImplementedError

    def state_pre_action_run_type(self, action: Action, graph: Graph) -> type[Any]:
        raise NotImplementedError

    def state_post_action_run_type(self, action: Action, graph: Graph) -> type[Any]:
        raise NotImplementedError

    def construct_data(self, state: State[Any]) -> Any:
        raise NotImplementedError

    def construct_state(self, data: State[Any]) -> State[Any]:
        raise NotImplementedError


def test_state_apply_keeps_typing_system():
    state = State({"foo": "bar"}, typing_system=SimpleTypingSystem())
    assert state.update(foo="baz").typing_system is state.typing_system
    assert state.subset("foo").typing_system is state.typing_system


def test_state_keys_returns_list():
    """Test that State.keys() returns a list (fixes #409)"""
    state = State({"a": 1, "b": 2, "c": 3})
    keys = state.keys()

    # Should return a list with the correct keys
    assert isinstance(keys, list)
    assert keys == ["a", "b", "c"]

    # Test with empty state
    empty_state = State()
    assert empty_state.keys() == []
