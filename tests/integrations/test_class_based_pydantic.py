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

from typing import Optional

import pytest
from pydantic import BaseModel, ValidationError

from burr.core.action import Action
from burr.core.application import ApplicationBuilder
from burr.integrations.pydantic import PydanticActionSchema, PydanticTypingSystem


class ClassBasedState(BaseModel):
    initial_prompt: Optional[str] = None
    observed_prompt: Optional[str] = None


class SetInitialPromptAction(Action):
    @property
    def reads(self) -> list[str]:
        return []

    @property
    def writes(self) -> list[str]:
        return ["initial_prompt"]

    @property
    def inputs(self) -> list[str]:
        return ["prompt"]

    @property
    def schema(self) -> PydanticActionSchema:
        return PydanticActionSchema(ClassBasedState, ClassBasedState, dict)

    def run(self, state: ClassBasedState, prompt: str) -> dict:
        assert isinstance(state, ClassBasedState)
        return {"initial_prompt": prompt}

    def update(self, result: dict, state: ClassBasedState) -> ClassBasedState:
        assert isinstance(state, ClassBasedState)
        state.initial_prompt = result["initial_prompt"]
        return state


class ObservePromptAction(Action):
    @property
    def reads(self) -> list[str]:
        return ["initial_prompt"]

    @property
    def writes(self) -> list[str]:
        return ["observed_prompt"]

    @property
    def schema(self) -> PydanticActionSchema:
        return PydanticActionSchema(ClassBasedState, ClassBasedState, dict)

    def run(self, state: ClassBasedState) -> dict:
        assert isinstance(state, ClassBasedState)
        return {"observed_prompt": state.initial_prompt}

    def update(self, result: dict, state: ClassBasedState) -> ClassBasedState:
        assert isinstance(state, ClassBasedState)
        state.observed_prompt = result["observed_prompt"]
        return state


class AsyncObservePromptAction(ObservePromptAction):
    async def run(self, state: ClassBasedState) -> dict:
        assert isinstance(state, ClassBasedState)
        return {"observed_prompt": state.initial_prompt}


def build_class_based_app(observe: Action):
    return (
        ApplicationBuilder()
        .with_actions(set_prompt=SetInitialPromptAction(), observe=observe)
        .with_entrypoint("set_prompt")
        .with_transitions(("set_prompt", "observe"))
        .with_typing(PydanticTypingSystem(ClassBasedState))
        .with_state(ClassBasedState())
        .build()
    )


def test_class_based_actions_receive_pydantic_state():
    app = build_class_based_app(ObservePromptAction())

    _, _, state = app.run(halt_after=["observe"], inputs={"prompt": "typed state"})

    assert isinstance(state.data, ClassBasedState)
    assert state.data.initial_prompt == "typed state"
    assert state.data.observed_prompt == "typed state"


async def test_async_class_based_action_receives_pydantic_state():
    app = build_class_based_app(AsyncObservePromptAction())
    _, _, state = await app.arun(halt_after=["observe"], inputs={"prompt": "typed state"})

    assert isinstance(state.data, ClassBasedState)
    assert state.data.initial_prompt == "typed state"
    assert state.data.observed_prompt == "typed state"


class PartialState(BaseModel):
    value: int = 0
    counter: int = 0


class RequiredState(BaseModel):
    value: int
    name: str


class WriteValue(Action):
    def __init__(self, model=PartialState, reads=None):
        super().__init__()
        self.model = model
        self._reads = reads or []

    @property
    def reads(self):
        return self._reads

    @property
    def writes(self):
        return ["value"]

    @property
    def schema(self):
        return PydanticActionSchema(self.model, self.model, dict)

    def run(self, state):
        assert isinstance(state, self.model)
        return {"value": 7}

    def update(self, result, state):
        assert isinstance(state, self.model)
        state.value = result["value"]
        if hasattr(state, "counter"):
            state.counter = 999
        return state


class AsyncWriteValue(WriteValue):
    async def run(self, state):
        return super().run(state)


def _write_app(action, initial):
    return (
        ApplicationBuilder()
        .with_actions(write=action)
        .with_entrypoint("write")
        .with_state(**initial)
        .build()
    )


@pytest.mark.parametrize("initial", [{}, {"counter": 3, "unrelated": "keep"}])
def test_class_based_only_merges_declared_writes(initial):
    _, _, state = _write_app(WriteValue(), initial).run(halt_after=["write"])
    assert {k: v for k, v in state.get_all().items() if not k.startswith("__")} == {
        **initial,
        "value": 7,
    }


@pytest.mark.parametrize("initial", [{}, {"counter": 3, "unrelated": "keep"}])
async def test_async_class_based_only_merges_declared_writes(initial):
    _, _, state = await _write_app(AsyncWriteValue(), initial).arun(halt_after=["write"])
    assert {k: v for k, v in state.get_all().items() if not k.startswith("__")} == {
        **initial,
        "value": 7,
    }


def test_required_fields_outside_reads_can_be_absent():
    _, _, state = _write_app(WriteValue(RequiredState), {}).run(halt_after=["write"])
    assert state["value"] == 7
    assert "name" not in state


async def test_async_required_fields_outside_reads_can_be_absent():
    _, _, state = await _write_app(AsyncWriteValue(RequiredState), {}).arun(halt_after=["write"])
    assert state["value"] == 7
    assert "name" not in state


def test_declared_read_still_validates_type():
    with pytest.raises(ValidationError):
        _write_app(WriteValue(RequiredState, reads=["value"]), {"value": "invalid"}).run(
            halt_after=["write"]
        )


@pytest.mark.parametrize("value", [None, "invalid"])
def test_declared_write_still_validates_type(value):
    class WriteInvalidValue(WriteValue):
        def update(self, result, state):
            state.value = value
            return state

    with pytest.raises(ValidationError):
        _write_app(WriteInvalidValue(RequiredState), {}).run(halt_after=["write"])
