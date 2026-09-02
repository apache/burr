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

from burr.core.action import DEFAULT_SCHEMA
from burr.core.state import State
from burr.core.typing import ActionSchema, DictBasedTypingSystem


def test_action_schema_subclass_implements_instance_methods():
    class MySchema(ActionSchema[State, State, dict]):
        def state_input_type(self) -> type[State]:
            return State

        def state_output_type(self) -> type[State]:
            return State

        def intermediate_result_type(self) -> type[dict]:
            return dict

    schema = MySchema()
    assert schema.state_input_type() is State
    assert schema.state_output_type() is State
    assert schema.intermediate_result_type() is dict


def test_action_schema_incomplete_subclass_cannot_instantiate():
    class Incomplete(ActionSchema):
        def state_input_type(self) -> type[State]:
            return State

    with pytest.raises(TypeError):
        Incomplete()


def test_default_schema_satisfies_action_schema():
    assert isinstance(DEFAULT_SCHEMA, ActionSchema)
    assert DEFAULT_SCHEMA.intermediate_result_type() is dict
    with pytest.raises(NotImplementedError):
        DEFAULT_SCHEMA.state_input_type()
    with pytest.raises(NotImplementedError):
        DEFAULT_SCHEMA.state_output_type()


def test_dict_based_typing_system():
    typing_system = DictBasedTypingSystem()
    assert typing_system.state_type() is dict
    assert typing_system.state_pre_action_run_type(None, None) is dict
    assert typing_system.state_post_action_run_type(None, None) is dict
    state = typing_system.construct_state({"a": 1})
    assert isinstance(state, State)
    assert typing_system.construct_data(state) == {"a": 1}
