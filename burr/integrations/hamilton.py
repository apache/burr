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

import dataclasses
from typing import Any, Dict, Literal, Tuple, Union

from burr.integrations.base import require_plugin

try:
    from hamilton.driver import Driver
except ImportError as e:
    require_plugin(
        e,
        "hamilton",
    )

from burr.core import Action, State


@dataclasses.dataclass
class StateSource:
    state_key: str
    missing: Literal["drop", "error"] = "error"
    # default: Any = None


MissingAction = Literal["drop", "error"]


@dataclasses.dataclass
class LiteralSource:
    value: Any


Input = Union[StateSource, LiteralSource]


def from_state(
    key: str,
    missing: MissingAction = "error",
) -> StateSource:
    """Indicates that an input should come from state.
    Specify "missing" to allow for missing keys to be dropped or raise an error.

    :param key: Key in state to use
    :param missing: What to do if the key is missing
    :return: A StateSource object -- use by Hamilton(inputs=...)
    """
    return StateSource(key, missing)


def from_value(value: Any) -> LiteralSource:
    """Indicates that an input should come from a literal (variable/constant) value.
    Use this if you just want to fix a parameter into the Hamilton DAG.

    :param value: Value to use
    :return: A LiteralSource object -- use by Hamilton(inputs=...)
    """
    return LiteralSource(value)


@dataclasses.dataclass
class Output:
    key: str
    mode: Literal["update", "append"] = "update"


def update_state(key: str) -> Output:
    """At the update step of a Hamilton Action, call state.update to the key field of state.
    Used with outputs= parameter of Hamilton(...)

    :param key: Field in state to udpate
    :return: An Output object
    """
    return Output(key, "update")


def append_state(key: str):
    """At the update state of a Hamilton Action, call state.append to the key field of state.
    Used with outputs= parameter of Hamilton(...)

    :param key: Field in state to append to
    :return: An Output object
    """
    return Output(key, "append")


DEFAULT_DRIVER = None


class Hamilton(Action):
    @staticmethod
    def set_driver(driver: Driver):
        """Default method if all the hamilton nodes are using the same driver.
        Will set globally, so be careful.

        Note that the driver must have the default adapter (so that it returns a dict).

        :param driver: Driver to use
        """
        global DEFAULT_DRIVER
        DEFAULT_DRIVER = driver

    def __init__(
        self,
        inputs: Dict[str, Input],
        outputs: Dict[str, Output],
        driver: Driver = None,
    ):
        """Creates a Hamilton action. Allows youy to specify:
        1. How to wire state fields into hamilton inputs
        2  How to wire hamilton outputs into state fields

        Note that we o not distinguish between overrides and inputs -- we intelligently decide
        which are which based on the driver's available variables.

        :param inputs:
        :param outputs:
        :param driver:
        :param name:
        """
        super(Hamilton, self).__init__()
        if driver is None and DEFAULT_DRIVER is None:
            raise ValueError(
                "Driver must be set before creating a Hamilton function. "
                "You can do so with Hamilton.set_driver(...) to set it globally, "
                "or pass in driver to the Hamilton(...) constructor."
            )
        self._driver = driver if driver is not None else DEFAULT_DRIVER
        self._inputs = inputs
        self._outputs = outputs

    @property
    def driver(self):
        return self._driver

    def _extract_inputs_overrides(self, state: State) -> Tuple[dict, dict]:
        """Extracts the inputs and overrides from the state."""

        def resolve_value(source: Input) -> Any:
            if isinstance(source, StateSource):
                if source.state_key in state:
                    return state[source.state_key]
                else:
                    if source.missing == "error":
                        raise ValueError(f"Missing state key {source.state_key}")
                    else:
                        return None
            else:
                return source.value

        inputs = {}
        overrides = {}
        dr_vars = {node.name: node for node in self._driver.list_available_variables()}
        for key, source in self._inputs.items():
            if key not in dr_vars:
                raise ValueError(
                    f"Input {key} not available in driver -- "
                    f"available variables are: {list(self._driver.list_available_variables())}"
                )
            node = dr_vars[key]
            if node.is_external_input:
                inputs[node.name] = resolve_value(source)
            else:
                overrides[node.name] = resolve_value(source)
        return inputs, overrides

    def run(self, state: State) -> dict:
        """Runs a hamilton action, using the driver to execute the hamilton DAG.

        :param state: The state to use
        :return: The results of the hamilton DAG
        """
        inputs, overrides = self._extract_inputs_overrides(state)
        result = self._driver.raw_execute(
            list(self._outputs.keys()),
            overrides=overrides,
            inputs=inputs,
        )
        return result

    def update(self, result: dict, state: State) -> State:
        """Updates the state with the results of the hamilton action, as specified in the outputs.

        :param result: The results of the hamilton DAG
        :param state: The state to update
        """
        update_values = {
            self._outputs[key].key: value
            for key, value in result.items()
            if self._outputs[key].mode == "update"
        }
        append_values = {
            self._outputs[key].key: value
            for key, value in result.items()
            if self._outputs[key].mode == "append"
        }
        return state.update(**update_values).append(**append_values)

    @property
    def reads(self) -> list[str]:
        """The set of state items this action reads.
        TODO:
        1. Parse the inputs and overrides to determine which state items are read
        2. Return them
        """
        return [
            source.state_key for source in self._inputs.values() if isinstance(source, StateSource)
        ]

    @property
    def writes(self) -> list[str]:
        """The set of state items this action writes.
        TODO:
        0. Determine how we want to represent writing final vars to the state
        1. Parse the final_vars to determine which state items are written to
        3. Return them
        :return: The set of state items this action writes.
        """
        return [source.key for source in self._outputs.values()]

    def visualize_step(self, **kwargs):
        """Visualizes execution for a Hamilton step"""
        dr = self._driver
        inputs = {key: ... for key in self._inputs}
        overrides = inputs
        final_vars = list(self._outputs.keys())
        return dr.visualize_execution(
            final_vars=final_vars,
            inputs=inputs,
            overrides=overrides,
            bypass_validation=True,
            **kwargs,
        )
