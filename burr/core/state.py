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

import abc
import copy
import dataclasses
import importlib
import inspect
import logging
from functools import cached_property
from typing import Any, Callable, Dict, Generic, Iterator, Mapping, Optional, TypeVar, Union

from burr.core import serde
from burr.core.typing import DictBasedTypingSystem, TypingSystem

logger = logging.getLogger(__name__)

FIELD_SERIALIZATION = {}


def register_field_serde(field_name: str, serializer: Callable, deserializer: Callable):
    """Registers a custom serializer + deserializer for a field globally.

    This is useful for really controlling how a field is serialized and deserialized for
    tracking / persistence.

    .. code-block:: python

        def my_field_serializer(value: MyType, **kwargs) -> dict:
            serde_value = _do_something_to_serialize(value)
            return {"value": serde_value}

        def my_field_deserializer(value: dict, **kwargs) -> MyType:
            serde_value = value["value"]
            return _do_something_to_deserialize(serde_value)

        register_field_serde("my_field", my_field_serializer, my_field_deserializer)

    :param field_name: The name of the field to register the serializer for.
    :param serializer: A function that takes the field value and returns a JSON serializable object.
    :param deserializer: A function that takes the JSON serializable object and returns the field value.
    """
    # assert that the serializer has **kwargs argument; it also needs to return a dict but we can't check that.
    # def name(value: Any, **kwargs) -> dict
    serializer_sig = inspect.signature(serializer)
    if not any(param.kind == param.VAR_KEYWORD for param in serializer_sig.parameters.values()):
        raise ValueError(f"Serializer for [{field_name}] must have **kwargs argument.")

    # assert that the deserializer has **kwargs argument; it also needs to return a dict but we can't check that.
    deserializer_sig = inspect.signature(deserializer)
    if not any(param.kind == param.VAR_KEYWORD for param in deserializer_sig.parameters.values()):
        raise ValueError(f"Deserializer for [{field_name}] must have **kwargs argument.")

    FIELD_SERIALIZATION[field_name] = (serializer, deserializer)


class StateDelta(abc.ABC):
    """Represents a delta operation for state. This represents a transaction.
    Note it has the ability to mutate state in-place, but will be layered behind an immutable
    state object."""

    @classmethod
    @abc.abstractmethod
    def name(cls) -> str:
        """Unique name of this operation for ser/deser"""
        pass

    def serialize(self) -> dict:
        """Converts the state delta to a JSON object"""
        if not dataclasses.is_dataclass(self):
            raise TypeError("serialize method is only supported for dataclass instances")
        return dataclasses.asdict(self)

    def base_serialize(self) -> dict:
        """Converts the state delta to a JSON object"""
        return {"name": self.name(), "operation": self.serialize()}

    def validate(self, input_state: Dict[str, Any]):
        """Validates the input state given the state delta. This is a no-op by default, as most operations are valid"""
        pass

    @classmethod
    def deserialize(cls, json_dict: dict) -> "StateDelta":
        """Converts a JSON object to a state delta"""
        if not dataclasses.is_dataclass(cls):
            raise TypeError("deserialize method is only supported for dataclass types")
        return cls(**json_dict)  # Assumes all fields in the dataclass match keys in json_dict

    def base_deserialize(self, json_dict: dict) -> "StateDelta":
        """Converts a JSON object to a state delta"""
        return self.deserialize(json_dict)

    @abc.abstractmethod
    def reads(self) -> list[str]:
        """Returns the keys that this state delta reads"""
        pass

    @abc.abstractmethod
    def writes(self) -> list[str]:
        """Returns the keys that this state delta writes"""
        pass

    @abc.abstractmethod
    def apply_mutate(self, inputs: dict):
        """Applies the state delta to the inputs"""
        pass


@dataclasses.dataclass
class SetFields(StateDelta):
    """State delta that sets fields in the state"""

    values: Mapping[str, Any]

    @classmethod
    def name(cls) -> str:
        return "set"

    def reads(self) -> list[str]:
        return list(self.values.keys())

    def writes(self) -> list[str]:
        return list(self.values.keys())

    def apply_mutate(self, inputs: dict):
        inputs.update(self.values)


@dataclasses.dataclass
class AppendFields(StateDelta):
    """State delta that appends to fields in the state"""

    values: Mapping[str, Any]

    @classmethod
    def name(cls) -> str:
        return "append"

    def reads(self) -> list[str]:
        return list(self.values.keys())

    def writes(self) -> list[str]:
        return list(self.values.keys())

    def apply_mutate(self, inputs: dict):
        for key, value in self.values.items():
            if key not in inputs:
                inputs[key] = []
            if not isinstance(inputs[key], list):
                raise ValueError(f"Cannot append to non-list value {key}={inputs[key]}")
            inputs[key].append(value)

    def validate(self, input_state: Dict[str, Any]):
        incorrect_types = {}
        for write_key in self.writes():
            if write_key in input_state and not hasattr(input_state[write_key], "append"):
                incorrect_types[write_key] = type(input_state[write_key])
        if incorrect_types:
            raise ValueError(
                f"Cannot append to non-appendable values: {incorrect_types}. "
                f"Please ensure that all fields are list-like."
            )


@dataclasses.dataclass
class ExtendFields(StateDelta):
    """State delta that extends fields in the state"""

    values: Mapping[str, list[Any]]

    @classmethod
    def name(cls) -> str:
        return "extend"

    def reads(self) -> list[str]:
        return list(self.values.keys())

    def writes(self) -> list[str]:
        return list(self.values.keys())

    def apply_mutate(self, inputs: dict):
        for key, value in self.values.items():
            if key not in inputs:
                inputs[key] = []
            if not isinstance(inputs[key], list):
                raise ValueError(f"Cannot extend non-list value {key}={inputs[key]}")
            inputs[key].extend(value)

    def validate(self, input_state: Dict[str, Any]):
        incorrect_types = {}
        for write_key in self.writes():
            if write_key in input_state and not hasattr(input_state[write_key], "extend"):
                incorrect_types[write_key] = type(input_state[write_key])
        if incorrect_types:
            raise ValueError(
                f"Cannot extend non-extendable values: {incorrect_types}. "
                f"Please ensure that all fields are list-like."
            )


@dataclasses.dataclass
class IncrementFields(StateDelta):
    values: Mapping[str, int]

    @classmethod
    def name(cls) -> str:
        return "increment"

    def reads(self) -> list[str]:
        return list(self.values.keys())

    def writes(self) -> list[str]:
        return list(self.values.keys())

    def validate(self, input_state: Dict[str, Any]):
        incorrect_types = {}
        for write_key in self.writes():
            if write_key in input_state and not isinstance(input_state[write_key], int):
                incorrect_types[write_key] = type(input_state[write_key])
        if incorrect_types:
            raise ValueError(
                f"Cannot increment non-integer values: {incorrect_types}. "
                f"Please ensure that all fields are integers."
            )

    def apply_mutate(self, inputs: dict):
        for key, value in self.values.items():
            if key not in inputs:
                inputs[key] = value
            else:
                inputs[key] += value


@dataclasses.dataclass
class DeleteField(StateDelta):
    """State delta that deletes fields from the state"""

    keys: list[str]

    @classmethod
    def name(cls) -> str:
        return "delete"

    def reads(self) -> list[str]:
        return list(self.keys)

    def writes(self) -> list[str]:
        return []

    def apply_mutate(self, inputs: dict):
        for key in self.keys:
            inputs.pop(key, None)


StateType = TypeVar("StateType", bound=Union[Dict[str, Any], Any])
AssignedStateType = TypeVar("AssignedStateType")


class State(Mapping, Generic[StateType]):
    """An immutable state object. This is the only way to interact with state in Burr."""

    def __init__(
        self,
        initial_values: Optional[Dict[str, Any]] = None,
        typing_system: Optional[TypingSystem[StateType]] = None,
    ):
        if initial_values is None:
            initial_values = dict()
        self._typing_system = (
            typing_system if typing_system is not None else DictBasedTypingSystem()  # type: ignore
        )
        self._state = initial_values

    @property
    def typing_system(self) -> TypingSystem[StateType]:
        return self._typing_system

    def with_typing_system(
        self, typing_system: TypingSystem[AssignedStateType]
    ) -> "State[AssignedStateType]":
        """Copies state with a specific typing system"""
        return State(self._state, typing_system=typing_system)

    @cached_property
    def data(self) -> StateType:
        return self._typing_system.construct_data(self)  # type: ignore

    def apply_operation(self, operation: StateDelta) -> "State[StateType]":
        """Applies a given operation to the state, returning a new state"""

        new_state = copy.copy(self._state)  # TODO -- restrict to just the read keys
        for field in operation.reads():
            # This ensures we only copy the fields that are read by value
            # and copy the others by value
            # TODO -- make this more efficient when we have immutable transactions
            # with event-based history: https://github.com/DAGWorks-Inc/burr/issues/33
            if field in new_state:
                # currently the reads() includes optional fields
                # We should clean that up, but this is an internal API so not worried now
                new_state[field] = copy.deepcopy(new_state[field])
        operation.validate(new_state)
        operation.apply_mutate(
            new_state
        )  # todo -- validate that the write keys are the only different ones
        return State(new_state, typing_system=self._typing_system)

    def get_all(self) -> Dict[str, Any]:
        """Returns the entire state, realize as a dictionary. This is a copy."""
        return dict(self)

    def serialize(self, **kwargs) -> dict:
        """Converts the state to a JSON serializable object"""
        _dict = self.get_all()

        def _serialize(k, v, **extrakwargs) -> Union[dict, str]:
            """chooses the correct serde function for the given key and calls it"""
            if k in FIELD_SERIALIZATION:
                result = FIELD_SERIALIZATION[k][0](v, **extrakwargs)
                if not isinstance(result, dict):
                    raise ValueError(
                        f"Field serde for {k} must return a dict,"
                        f" but {FIELD_SERIALIZATION[k][0].__name__} returned {type(result)} ({str(result)[0:10]})."
                    )
                return result
            return serde.serialize(v, **extrakwargs)

        return {k: _serialize(k, v, **kwargs) for k, v in _dict.items()}

    @classmethod
    def deserialize(cls, json_dict: dict, **kwargs) -> "State[StateType]":
        """Converts a dictionary representing a JSON object back into a state"""

        def _deserialize(k, v: Union[str, dict], **extrakwargs) -> Callable:
            """chooses the correct serde function for the given key and calls it"""
            if k in FIELD_SERIALIZATION:
                return FIELD_SERIALIZATION[k][1](v, **extrakwargs)
            return serde.deserialize(v, **extrakwargs)

        return State({k: _deserialize(k, v, **kwargs) for k, v in json_dict.items()})

    def update(self, **updates: Any) -> "State[StateType]":
        """Updates the state with a set of key-value pairs
        Does an upsert operation (if the keys exist their value will be overwritten,
        otherwise they will be created)

        .. code-block:: python

            state = State({"a": 1})
            state.update(a=2, b=3)  # State({"a": 2, "b": 3})

        :param updates: Updates to apply
        :return: A new state with the updates applied
        """
        return self.apply_operation(SetFields(updates))

    def append(self, **updates: Any) -> "State[StateType]":
        """Appends to the state with a set of key-value pairs. Each one
        must correspond to a list-like object, or an error will be raised.

        This is an upsert operation, meaning that if the key does not
        exist, a new list will be created with the value in it.

        .. code-block:: python

            state = State({"a": [1]})
            state.append(a=2)  # State({"a": [1, 2]})

        :param updates: updates to apply
        :return: new state object
        """

        return self.apply_operation(AppendFields(updates))

    def extend(self, **updates: list[Any]) -> "State[StateType]":
        """Extends the state with a set of key-value pairs. Each one
        must correspond to a list-like object, or an error will be raised.

        This is an upsert operation, meaning that if the key does not
        exist, a new list will be created and extended with the values.

        .. code-block:: python

            state = State({"a": [1]})
            state.extend(a=[2, 3])  # State({"a": [1, 2, 3]})

        :param updates: updates to apply
        :return: new state object
        """

        return self.apply_operation(ExtendFields(updates))

    def increment(self, **updates: int) -> "State[StateType]":
        """Increments the state with a set of key-value pairs. Each one
        must correspond to an integer, or an error will be raised.

        :param updates: updates to apply
        :return: new state object
        """ ""
        return self.apply_operation(IncrementFields(updates))

    def wipe(self, delete: Optional[list[str]] = None, keep: Optional[list[str]] = None):
        """Wipes the state, either by deleting the keys in delete and keeping everything else
         or keeping the keys in keep. and deleting everything else. If you pass nothing in
         it will delete the whole thing.

        :param delete: Keys to delete
        :param keep: Keys to keep
        :return: A new state object
        """
        if delete is not None and keep is not None:
            raise ValueError(
                f"You cannot specify both delete and keep -- not both! "
                f"You have specified: delete={delete}, keep={keep}"
            )
        if delete is not None:
            fields_to_delete = delete
        else:
            fields_to_delete = [key for key in self._state if key not in keep]
        return self.apply_operation(DeleteField(fields_to_delete))

    def merge(self, other: "State") -> "State[StateType]":
        """Merges two states together, overwriting the values in self
        with those in other."""
        return State({**self.get_all(), **other.get_all()}, self.typing_system)

    def subset(self, *keys: str, ignore_missing: bool = True) -> "State[StateType]":
        """Returns a subset of the state, with only the given keys"""
        return State(
            {key: self[key] for key in keys if key in self or not ignore_missing},
            self.typing_system,
        )

    def __getitem__(self, __k: str) -> Any:
        if __k not in self._state:
            raise KeyError(
                f"Key \"{__k}\" not found in state. Keys state knows about are: {[key for key in self._state.keys() if not key.startswith('__')]}. "
                "If you hit this within the context of an application, you want to "
                "(a) ensure that an upstream action has produced this state/it is set as an initial state value and "
                "(b) ensure that your action declares this as a read key."
            )
        return self._state[__k]

    def __len__(self) -> int:
        return len(self._state)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._state)

    def keys(self):
        """Returns a list of the state keys only (without values for cleaner display).

        Returns:
            list: A list of state keys
        """
        return list(self._state)

    def __repr__(self):
        return self.get_all().__repr__()  # quick hack


# We register the serde plugins here that we'll automatically try to load.
# In the future if we need to reorder/replace, we'll just have some
# check here that can skip loading plugins/override which ones to load.
# Note for pickle, we require people to manually register the type for that.
for serde_plugin in ["langchain", "pydantic", "pandas"]:
    try:
        importlib.import_module(f"burr.integrations.serde.{serde_plugin}")
    except ImportError:
        logger.debug(f"Skipped registering {serde_plugin} serde plugin.")
