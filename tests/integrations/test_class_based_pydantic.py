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

from pydantic import BaseModel

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
    _, _, state = await app.arun(
        halt_after=["observe"], inputs={"prompt": "typed state"}
    )

    assert isinstance(state.data, ClassBasedState)
    assert state.data.initial_prompt == "typed state"
    assert state.data.observed_prompt == "typed state"
