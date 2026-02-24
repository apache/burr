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

import asyncio
from typing import AsyncGenerator, Generator, Optional, Tuple, cast

import pytest

from burr.core import State
from burr.core.action import (
    Action,
    AsyncStreamingAction,
    AsyncStreamingResultContainer,
    Condition,
    Function,
    Input,
    Result,
    SingleStepAction,
    SingleStepStreamingAction,
    StreamingAction,
    StreamingResultContainer,
    action,
    create_action,
    default,
    derive_inputs_from_fn,
    streaming_action,
)


def test_is_async_true():
    class AsyncFunction(Function):
        @property
        def inputs(self) -> list[str]:
            return []

        @property
        def reads(self) -> list[str]:
            return []

        async def run(self, state: State, **run_kwargs) -> dict:
            return {}

    func = AsyncFunction()
    assert func.is_async()


def test_is_async_false():
    class SyncFunction(Function):
        def reads(self) -> list[str]:
            return []

        def run(self, state: State, **run_kwargs) -> dict:
            return {}

    func = SyncFunction()
    assert not func.is_async()


class BasicAction(Action):
    @property
    def reads(self) -> list[str]:
        return ["input_variable"]

    def run(self, state: State) -> dict:
        return {"output_variable": state["input_variable"]}

    @property
    def writes(self) -> list[str]:
        return ["output_variable"]

    def update(self, result: dict, state: State) -> State:
        return state.update(**result)

    @property
    def tags(self) -> list[str]:
        return ["tag1", "tag2"]


def test_with_name():
    action = BasicAction()
    assert action.name is None  # Nothing set initially
    with_name = action.with_name("my_action")
    assert with_name.name == "my_action"  # Name set on copy
    assert with_name.reads == action.reads
    assert with_name.writes == action.writes
    assert with_name.tags == action.tags


def test_condition():
    cond = Condition(["foo"], lambda state: state["foo"] == "bar", name="foo")
    assert cond.name == "foo"
    assert cond.reads == ["foo"]
    assert cond.run(State({"foo": "bar"})) == {Condition.KEY: True}
    assert cond.run(State({"foo": "baz"})) == {Condition.KEY: False}


def test_condition_when():
    cond = Condition.when(foo="bar")
    assert cond.name == "foo=bar"
    assert cond.reads == ["foo"]
    assert cond.run(State({"foo": "bar"})) == {Condition.KEY: True}
    assert cond.run(State({"foo": "baz"})) == {Condition.KEY: False}


def test_condition_when_complex():
    cond = Condition.when(foo="bar", baz="qux")
    assert cond.name == "baz=qux, foo=bar"
    assert sorted(cond.reads) == ["baz", "foo"]
    assert cond.run(State({"foo": "bar", "baz": "qux"})) == {Condition.KEY: True}
    assert cond.run(State({"foo": "baz", "baz": "qux"})) == {Condition.KEY: False}
    assert cond.run(State({"foo": "bar", "baz": "corge"})) == {Condition.KEY: False}
    assert cond.run(State({"foo": "baz", "baz": "corge"})) == {Condition.KEY: False}


def test_condition_default():
    cond = default
    assert cond.name == "default"
    assert cond.reads == []
    assert cond.run(State({"foo": "bar"})) == {Condition.KEY: True}


def test_condition_expr():
    cond = Condition.expr("foo == 'bar'")
    assert cond.name == "foo == 'bar'"
    assert cond.reads == ["foo"]
    assert cond.run(State({"foo": "bar"})) == {Condition.KEY: True}
    assert cond.run(State({"foo": "baz"})) == {Condition.KEY: False}


def test_condition_expr_complex():
    cond = Condition.expr("foo == 'bar' and len(baz) == 3")
    assert cond.name == "foo == 'bar' and len(baz) == 3"
    assert sorted(cond.reads) == ["baz", "foo"]
    assert cond.run(State({"foo": "bar", "baz": "qux"})) == {Condition.KEY: True}
    assert cond.run(State({"foo": "baz", "baz": "qux"})) == {Condition.KEY: False}
    assert cond.run(State({"foo": "bar", "baz": "corge"})) == {Condition.KEY: False}
    assert cond.run(State({"foo": "baz", "baz": "corge"})) == {Condition.KEY: False}


def test_condition__validate_success():
    cond = Condition.when(foo="bar")
    cond._validate(State({"foo": "bar"}))


def test_condition__validate_failure():
    cond = Condition.when(foo="bar")
    with pytest.raises(ValueError, match="foo"):
        cond._validate(State({"baz": "baz"}))


def test_condition_invert():
    cond = Condition(
        ["foo"],
        lambda state: state["foo"] == "bar",
        name="foo == 'bar'",
    )
    cond_inverted = ~cond
    assert cond_inverted.name == "~foo == 'bar'"
    assert cond_inverted.reads == ["foo"]
    assert cond_inverted.run(State({"foo": "bar"})) == {Condition.KEY: False}
    assert cond_inverted.run(State({"foo": "baz"})) == {Condition.KEY: True}


def test_condition_and():
    cond1 = Condition.when(foo="bar")
    cond2 = Condition.when(baz="qux")
    cond_and = cond1 & cond2
    assert cond_and.name == "foo=bar & baz=qux"
    assert sorted(cond_and.reads) == ["baz", "foo"]
    assert cond_and.run(State({"foo": "bar", "baz": "qux"})) == {Condition.KEY: True}
    assert cond_and.run(State({"foo": "baz", "baz": "qux"})) == {Condition.KEY: False}
    assert cond_and.run(State({"foo": "bar", "baz": "corge"})) == {Condition.KEY: False}
    assert cond_and.run(State({"foo": "baz", "baz": "corge"})) == {Condition.KEY: False}


def test_condition_or():
    cond1 = Condition.when(foo="bar")
    cond2 = Condition.when(baz="qux")
    cond_or = cond1 | cond2
    assert cond_or.name == "foo=bar | baz=qux"
    assert sorted(cond_or.reads) == ["baz", "foo"]
    assert cond_or.run(State({"foo": "bar", "baz": "qux"})) == {Condition.KEY: True}
    assert cond_or.run(State({"foo": "baz", "baz": "qux"})) == {Condition.KEY: True}
    assert cond_or.run(State({"foo": "bar", "baz": "corge"})) == {Condition.KEY: True}
    assert cond_or.run(State({"foo": "baz", "baz": "corge"})) == {Condition.KEY: False}


def test_condition_lmda():
    cond = Condition.lmda(lambda state: state["foo"] == "bar", ["foo"])
    assert cond.reads == ["foo"]
    assert cond.run(State({"foo": "bar"})) == {Condition.KEY: True}
    assert cond.run(State({"foo": "baz"})) == {Condition.KEY: False}


# TODO -- add this in once we decide what to do with optional keys...
# def test_condition_exists_single():
#     cond = Condition.exists("foo")
#     assert cond.name == "exists_foo"
#     assert cond.reads == ["foo"]
#     assert cond.run(State({"foo": "baz", "bar": "baz"})) == {Condition.KEY: True}
#     assert cond.run(State({})) == {Condition.KEY: False}
#
#
# def test_condition_exists_double():
#     cond = Condition.exists("foo", "bar")
#     assert cond.name == "exists_bar_and_foo"
#     assert cond.reads == ["foo"]
#     assert cond.run(State({"foo": "baz", "bar": "baz"})) == {Condition.KEY: True}
#     assert cond.run(State({"foo" : "bar"})) == {Condition.KEY: False}


def test_result():
    result = Result("foo", "bar")
    assert result.run(State({"foo": "baz", "bar": "qux", "baz": "quux"})) == {
        "foo": "baz",
        "bar": "qux",
    }
    assert result.writes == []  # doesn't write anything
    assert result.reads == ["foo", "bar"]
    # no results
    assert result.update(
        {"foo": "baz", "bar": "qux"}, State({"foo": "baz", "bar": "qux", "baz": "quux"})
    ) == State(
        {"foo": "baz", "bar": "qux", "baz": "quux"}
    )  # no impact


def test_input():
    input_action = Input("foo", "bar")
    assert input_action.reads == []
    assert input_action.writes == ["foo", "bar"]
    assert input_action.inputs == ["foo", "bar"]
    assert (result := input_action.run(State({}), foo="baz", bar="qux")) == {
        "foo": "baz",
        "bar": "qux",
    }
    assert input_action.update(result, State({})).get_all() == {"foo": "baz", "bar": "qux"}


def test_function_based_action():
    @action(reads=["input_variable"], writes=["output_variable"], tags=["tag1", "tag2"])
    def my_action(state: State) -> Tuple[dict, State]:
        return {"output_variable": state["input_variable"]}, state.update(
            output_variable=state["input_variable"]
        )

    fn_based_action = create_action(my_action, name="my_action")
    assert fn_based_action.single_step
    assert fn_based_action.name == "my_action"
    assert fn_based_action.reads == ["input_variable"]
    assert fn_based_action.writes == ["output_variable"]
    assert fn_based_action.tags == ["tag1", "tag2"]
    result, state = fn_based_action.run_and_update(State({"input_variable": "foo"}))
    assert result == {"output_variable": "foo"}
    assert state.get_all() == {"input_variable": "foo", "output_variable": "foo"}


def test_function_based_action_with_inputs():
    @action(reads=["input_variable"], writes=["output_variable"], tags=["tag1", "tag2"])
    def my_action(state: State, bound_input: int, unbound_input: int) -> Tuple[dict, State]:
        res = state["input_variable"] + bound_input + unbound_input
        return {"output_variable": res}, state.update(output_variable=res)

    fn_based_action = cast(
        SingleStepAction, create_action(my_action.bind(bound_input=10), name="my_action")
    )
    assert fn_based_action.inputs == (["unbound_input"], [])
    assert fn_based_action.tags == ["tag1", "tag2"]
    result, state = fn_based_action.run_and_update(State({"input_variable": 1}), unbound_input=100)
    assert state.get_all() == {"input_variable": 1, "output_variable": 111}
    assert result == {"output_variable": 111}


def test_function_based_action_multiple_binds():
    # This ensures that bind doesn't impact the original function
    @action(reads=["input_variable"], writes=["output_variable"])
    def my_action(state: State, bound_input: int, unbound_input: int) -> Tuple[dict, State]:
        res = state["input_variable"] + bound_input + unbound_input
        return {"output_variable": res}, state.update(output_variable=res)

    # The binding has to happen before the actions are created
    # Otherwise it'll get the right value
    # This simulates how the ApplicationBuilder creates them
    bound_1 = my_action.bind(bound_input=10)
    bound_2 = my_action.bind(bound_input=20)

    fn_based_action = cast(SingleStepAction, create_action(bound_1, name="my_action"))
    fn_based_action_2 = cast(SingleStepAction, create_action(bound_2, name="my_action"))
    assert fn_based_action.inputs == (["unbound_input"], [])
    result, state = fn_based_action.run_and_update(State({"input_variable": 1}), unbound_input=100)
    assert state.get_all() == {"input_variable": 1, "output_variable": 111}
    assert result == {"output_variable": 111}

    assert fn_based_action_2.inputs == (["unbound_input"], [])
    result, state = fn_based_action_2.run_and_update(
        State({"input_variable": 1}), unbound_input=100
    )
    assert state.get_all() == {"input_variable": 1, "output_variable": 121}
    assert result == {"output_variable": 121}


def test_function_based_action_with_defaults():
    @action(reads=["input_variable"], writes=["output_variable"])
    def my_action(
        state: State, bound_input: int, unbound_input: int, unbound_default_input: int = 1000
    ) -> Tuple[dict, State]:
        res = state["input_variable"] + bound_input + unbound_input + unbound_default_input
        return {"output_variable": res}, state.update(output_variable=res)

    fn_based_action: SingleStepAction = create_action(
        my_action.bind(bound_input=10), name="my_action"
    )
    assert fn_based_action.inputs == (["unbound_input"], ["unbound_default_input"])
    result, state = fn_based_action.run_and_update(State({"input_variable": 1}), unbound_input=100)
    assert state.get_all() == {"input_variable": 1, "output_variable": 1111}
    assert result == {"output_variable": 1111}


def test_function_based_action_with_defaults_unbound():
    # inputs can have defaults -- this tests that we treat them propertly
    @action(reads=["input_variable"], writes=["output_variable"])
    def my_action(
        state: State, unbound_input_1: int, unbound_input_2: int, unbound_default_input: int = 1000
    ) -> Tuple[dict, State]:
        res = state["input_variable"] + unbound_input_1 + unbound_input_2 + unbound_default_input
        return {"output_variable": res}, state.update(output_variable=res)

    fn_based_action: SingleStepAction = create_action(my_action, name="my_action")
    assert fn_based_action.inputs == (
        ["unbound_input_1", "unbound_input_2"],
        ["unbound_default_input"],
    )
    result, state = fn_based_action.run_and_update(
        State({"input_variable": 1}), unbound_input_1=10, unbound_input_2=100
    )
    assert state.get_all() == {"input_variable": 1, "output_variable": 1111}
    assert result == {"output_variable": 1111}


async def test_function_based_action_async():
    @action(reads=["input_variable"], writes=["output_variable"], tags=["tag1", "tag2"])
    async def my_action(state: State) -> Tuple[dict, State]:
        await asyncio.sleep(0.01)
        return {"output_variable": state["input_variable"]}, state.update(
            output_variable=state["input_variable"]
        )

    fn_based_action = create_action(my_action, name="my_action")
    assert fn_based_action.is_async()
    assert fn_based_action.single_step is True
    assert fn_based_action.name == "my_action"
    assert fn_based_action.reads == ["input_variable"]
    assert fn_based_action.writes == ["output_variable"]
    assert fn_based_action.tags == ["tag1", "tag2"]
    result, state = await fn_based_action.run_and_update(State({"input_variable": "foo"}))
    assert result == {"output_variable": "foo"}
    assert state.get_all() == {"input_variable": "foo", "output_variable": "foo"}


async def test_function_based_action_with_inputs_async():
    @action(reads=["input_variable"], writes=["output_variable"])
    async def my_action(state: State, bound_input: int, unbound_input: int) -> Tuple[dict, State]:
        await asyncio.sleep(0.01)
        res = state["input_variable"] + bound_input + unbound_input
        return {"output_variable": res}, state.update(output_variable=res)

    fn_based_action: SingleStepAction = create_action(
        my_action.bind(bound_input=10), name="my_action"
    )
    assert fn_based_action.is_async()
    assert fn_based_action.inputs == (["unbound_input"], [])
    result, state = await fn_based_action.run_and_update(
        State({"input_variable": 1}), unbound_input=100
    )
    assert state.get_all() == {"input_variable": 1, "output_variable": 111}
    assert result == {"output_variable": 111}


async def test_function_based_action_with_defaults_async():
    @action(reads=["input_variable"], writes=["output_variable"])
    async def my_action(
        state: State, bound_input: int, unbound_input: int, unbound_default_input: int = 1000
    ) -> Tuple[dict, State]:
        await asyncio.sleep(0.01)
        res = state["input_variable"] + bound_input + unbound_input + unbound_default_input
        return {"output_variable": res}, state.update(output_variable=res)

    fn_based_action: SingleStepAction = create_action(
        my_action.bind(bound_input=10), name="my_action"
    )
    assert fn_based_action.inputs == (["unbound_input"], ["unbound_default_input"])
    result, state = await fn_based_action.run_and_update(
        State({"input_variable": 1}), unbound_input=100
    )
    assert state.get_all() == {"input_variable": 1, "output_variable": 1111}
    assert result == {"output_variable": 1111}


def test_create_action_class_api():
    raw_action = BasicAction()
    created_action = create_action(raw_action, name="my_action")
    assert created_action.name == "my_action"
    assert created_action.reads == raw_action.reads
    assert created_action.writes == raw_action.writes
    assert created_action.tags == raw_action.tags


def test_create_action_fn_api():
    @action(reads=["input_variable"], writes=["output_variable"], tags=["tag1", "tag2"])
    def test_action(state: State) -> Tuple[dict, State]:
        result = {"output_variable": state["input_variable"]}
        return result, state.update(output_variable=result["output_variable"])

    created_action = create_action(test_action, name="my_action")
    assert created_action.name == "my_action"
    assert created_action.reads == ["input_variable"]
    assert created_action.writes == ["output_variable"]
    assert created_action.single_step
    assert created_action.tags == ["tag1", "tag2"]
    result, state = created_action.run_and_update(State({"input_variable": "foo"}))
    assert result == {"output_variable": "foo"}
    assert state.get_all() == {"input_variable": "foo", "output_variable": "foo"}


def test_create_action_fn_api_with_bind():
    @action(reads=["input_variable_1"], writes=["output_variable_1", "output_variable_2"])
    def test_action(state: State, input_variable_2: int) -> Tuple[dict, State]:
        result = {
            "output_variable_1": state["input_variable_1"],
            "output_variable_2": input_variable_2,
        }
        return result, state.update(**result)

    bound = test_action.bind(input_variable_2=2)
    created_action = create_action(bound, name="my_action")

    assert created_action.name == "my_action"
    result, state = created_action.run_and_update(State({"input_variable_1": "foo"}))
    assert result == {
        "output_variable_1": "foo",
        "output_variable_2": 2,
    }
    assert state.get_all() == {
        "input_variable_1": "foo",
        "output_variable_1": "foo",
        "output_variable_2": 2,
    }


def test_create_action_streaming_fn_api_with_bind():
    @streaming_action(reads=["input_variable"], writes=["output_variable"], tags=["tag1", "tag2"])
    def test_action(
        state: State, prefix: str
    ) -> Generator[Tuple[dict, Optional[State]], None, None]:
        buffer = []
        for c in prefix + state["input_variable"]:
            buffer.append(c)
            yield {"output_variable": c}, None  # intermediate results
        result = {"output_variable": "".join(buffer)}
        yield result, state.update(output_variable=result["output_variable"])

    created_action = create_action(test_action.bind(prefix="prefix_"), name="my_action")
    assert created_action.streaming
    assert isinstance(created_action, SingleStepStreamingAction)
    assert created_action.name == "my_action"
    assert created_action.reads == ["input_variable"]
    assert created_action.writes == ["output_variable"]
    assert created_action.tags == ["tag1", "tag2"]
    assert created_action.single_step
    gen = created_action.stream_run_and_update(State({"input_variable": "foo"}))
    out = [item for item in gen]
    final_result, state = out[-1]
    intermediate_results = [item[0]["output_variable"] for item in out[:-1]]
    assert final_result == {"output_variable": "prefix_foo"}
    assert state.get_all() == {"input_variable": "foo", "output_variable": "prefix_foo"}
    assert intermediate_results == list("prefix_foo")


async def test_create_action_streaming_fn_api_with_bind_async():
    @streaming_action(reads=["input_variable"], writes=["output_variable"], tags=["tag1", "tag2"])
    async def test_action(
        state: State, prefix: str
    ) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
        buffer = []
        for c in prefix + state["input_variable"]:
            buffer.append(c)
            yield {"output_variable": c}, None  # intermediate results
            await asyncio.sleep(0.01)
        joined = "".join(buffer)
        yield {"output_variable": joined}, state.update(output_variable=joined)

    created_action = create_action(test_action.bind(prefix="prefix_"), name="my_action")
    assert created_action.streaming  # streaming
    assert created_action.is_async()  # async
    assert isinstance(created_action, SingleStepStreamingAction)
    assert created_action.name == "my_action"
    assert created_action.reads == ["input_variable"]
    assert created_action.writes == ["output_variable"]
    assert created_action.single_step
    assert created_action.tags == ["tag1", "tag2"]
    gen = created_action.stream_run_and_update(State({"input_variable": "foo"}))
    out = [item async for item in gen]
    final_result, state = out[-1]
    intermediate_results = [item[0]["output_variable"] for item in out[:-1]]
    assert final_result == {"output_variable": "prefix_foo"}
    assert state.get_all() == {"input_variable": "foo", "output_variable": "prefix_foo"}
    assert intermediate_results == list("prefix_foo")


def test_create_action_undecorated_function():
    def test_action(state: State) -> Tuple[dict, State]:
        result = {"output_variable": state["input_variable"]}
        return result, state.update(output_variable=result["output_variable"])

    with pytest.raises(ValueError, match="not a valid action"):
        create_action(test_action, name="my_action")


def test_streaming_action_stream_run():
    class SimpleStreamingAction(StreamingAction):
        def stream_run(
            self, state: State, **run_kwargs
        ) -> Generator[Tuple[dict, Optional[State]], None, None]:
            buffer = []
            for char in state["echo"]:
                yield {"response": char}, None
                buffer.append(char)
            yield {"response": "".join(buffer)}, state.update(response="".join(buffer))

        @property
        def reads(self) -> list[str]:
            return []

        @property
        def writes(self) -> list[str]:
            return ["response"]

        def update(self, result: dict, state: State) -> State:
            return state.update(**result)

    action = SimpleStreamingAction()
    STR = "test streaming action"
    result, state_update = action.run(State({"echo": STR}))
    assert result["response"] == STR
    assert state_update["response"] == STR


async def test_streaming_action_stream_run_async():
    class SimpleAsyncStreamingAction(AsyncStreamingAction):
        async def stream_run(self, state: State, **run_kwargs) -> AsyncGenerator[dict, None]:
            buffer = []
            for char in state["echo"]:
                yield {"response": char}, None
                await asyncio.sleep(0.01)
                buffer.append(char)
            yield {"response": "".join(buffer)}

        @property
        def reads(self) -> list[str]:
            return []

        @property
        def writes(self) -> list[str]:
            return ["response"]

        def update(self, result: dict, state: State) -> State:
            return state.update(**result)

    action = SimpleAsyncStreamingAction()
    STR = "test streaming action"
    result = await action.run(State({"echo": STR}))
    state_update = action.update(result, State({"echo": STR}))
    assert result["response"] == STR
    assert state_update["response"] == STR


def sample_generator(chars: str) -> Generator[Tuple[dict, Optional[State]], None, None]:
    buffer = []
    for c in chars:
        buffer.append(c)
        yield {"response": c}, None
    joined = "".join(buffer)
    yield {"response": joined}, State({"response": joined})


def test_streaming_result_container_iterate():
    string_value = "test streaming action"
    container = StreamingResultContainer(
        sample_generator(string_value),
        initial_state=State(),
        process_result=lambda r, s: (r, s),
        callback=lambda s, r, e: None,
    )
    assert [item["response"] for item in list(container)] == list(string_value)
    result, state = container.get()
    assert result["response"] == string_value


def test_streaming_result_get_runs_through():
    string_value = "test streaming action"
    container = StreamingResultContainer(
        sample_generator(string_value),
        initial_state=State(),
        process_result=lambda r, s: (r, s),
        callback=lambda s, r, e: None,
    )
    result, state = container.get()
    assert result["response"] == string_value


def test_streaming_result_callback_called():
    called = []
    string_value = "test streaming action"

    container = StreamingResultContainer(
        sample_generator(string_value),
        # initial state is here solely for returning debugging so we can return an
        # state to the user in the case of failure
        initial_state=State({"foo": "bar"}),
        process_result=lambda r, s: (r, s),
        callback=lambda s, r, e: called.append((s, r, e)),
    )
    container.get()
    assert len(called) == 1
    state, result, error = called[0]
    assert result["response"] == string_value
    assert state["response"] == string_value
    assert error is None


def test_streaming_result_callback_error():
    """This tests whether the callback is called when an error occurs in the generator. Note that try/except
    blocks -- this is required so we can end up delegating to the generators closing capability"""

    class SentinelError(Exception):
        pass

    try:
        called = []
        string_value = "test streaming action"
        container = StreamingResultContainer(
            sample_generator(string_value),
            initial_state=State({"foo": "bar"}),
            process_result=lambda r, s: (r, s),
            callback=lambda r, s, e: called.append((r, s, e)),
        )
        try:
            for _ in container:
                raise SentinelError("error")
        finally:
            assert len(called) == 1
            ((result, state, error),) = called
            assert state["foo"] == "bar"
            assert result is None
            # Exception is currently not exactly what we want, so won't assert on that.
            # See note in StreamingResultContainer
    except SentinelError:
        pass


async def sample_async_generator(chars: str) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
    buffer = []
    for c in chars:
        buffer.append(c)
        yield {"response": c}, None
        await asyncio.sleep(0.01)
    joined = "".join(buffer)
    yield {"response": joined}, State({"response": joined})


async def test_streaming_result_container_iterate_async():
    async def callback(r: dict, s: State, e: Exception):
        pass

    string_value = "test streaming action"
    container = AsyncStreamingResultContainer(
        sample_async_generator(string_value),
        initial_state=State(),
        process_result=lambda r, s: (r, s),
        callback=callback,
    )
    assert [item["response"] async for item in container] == list(string_value)
    result, state = await container.get()
    assert result["response"] == string_value


async def test_streaming_result_get_runs_through_async():
    async def callback(r: dict, s: State, e: Exception):
        pass

    string_value = "test streaming action"
    container = AsyncStreamingResultContainer(
        sample_async_generator(string_value),
        initial_state=State(),
        process_result=lambda r, s: (r, s),
        callback=callback,
    )
    result, state = await container.get()
    assert result["response"] == string_value


async def test_streaming_result_callback_called_async():
    called = []
    string_value = "test streaming action"

    async def callback(r: Optional[dict], s: State, e: Exception):
        called.append((s, r, e))

    container = AsyncStreamingResultContainer(
        sample_async_generator(string_value),
        # initial state is here solely for returning debugging so we can return an
        # state to the user in the case of failure
        initial_state=State({"foo": "bar"}),
        process_result=lambda r, s: (r, s),
        callback=callback,
    )
    await container.get()
    assert len(called) == 1
    result, state, error = called[0]
    assert result["response"] == string_value
    assert state["response"] == string_value
    assert error is None


def test_streaming_result_callback_error_async():
    """Oi. This can't use pytest-asyncio because pytest-asyncio doesn't shutdown async gens.
    I sure hope our customer's stuff shuts down async gens.

    See https://github.com/pytest-dev/pytest-asyncio/issues/759 for more details.

    """
    called = []

    class SentinelError(Exception):
        pass

    async def test_fn():
        try:

            async def callback(r: Optional[dict], s: State, e: Exception):
                called.append((r, s, e))

            string_value = "test streaming action"
            container = AsyncStreamingResultContainer(
                sample_async_generator(string_value),
                initial_state=State({"foo": "bar"}),
                process_result=lambda r, s: (r, s),
                callback=callback,
            )
            async for _ in container:
                raise SentinelError("error")
                # Exception is currently not exactly what we want, so won't assert on that.
                # See note in StreamingResultContainer
        except SentinelError:
            pass

    asyncio.run(test_fn())
    assert len(called) == 1
    ((result, state, error),) = called
    assert state["foo"] == "bar"
    assert result is None


def test_derive_inputs_from_fn_state_only():
    def fn(state):
        ...

    bound_params = {}
    required, optional = derive_inputs_from_fn(bound_params, fn)
    assert required == []
    assert optional == []


def test_derive_inputs_from_fn_state_and_required():
    def fn(state, a, b):
        ...

    bound_params = {"state": 1}
    required, optional = derive_inputs_from_fn(bound_params, fn)
    assert required == ["a", "b"]
    assert optional == []


def test_derive_inputs_from_fn_state_required_and_optional():
    def fn(state, a, b=2):
        ...

    bound_params = {"state": 1}
    required, optional = derive_inputs_from_fn(bound_params, fn)
    assert required == ["a"]
    assert optional == ["b"]


def test_derive_inputs_from_fnh_state_and_all_bound_except_state():
    def fn(state, a, b):
        ...

    bound_params = {"a": 1, "b": 2}
    required, optional = derive_inputs_from_fn(bound_params, fn)
    assert required == []
    assert optional == []


def test_non_existent_bound_parameters():
    def fn(state, a):
        ...

    bound_params = {"a": 1, "non_existent": 2}
    required, optional = derive_inputs_from_fn(bound_params, fn)
    assert required == []
    assert optional == []


def test_undeclared_state_read_raises_error():
    with pytest.raises(ValueError):

        @action(reads=["foo"], writes=[])
        def bad_action(state: State):
            _ = state["bar"]
            return {}, state


def test_declared_state_read_passes():
    @action(reads=["foo"], writes=[])
    def good_action(state: State):
        _ = state["foo"]
        return {}, state


def test_multiple_undeclared_reads_interleaved():
    with pytest.raises(ValueError) as exc:

        @action(reads=["foo"], writes=[])
        def bad_action(state: State):
            _ = state["foo"]
            _ = state["bar"]
            _ = state["baz"]
            return {}, state

    message = str(exc.value)
    assert "bar" in message
    assert "baz" in message


def test_pydantic_action_not_impacted():
    try:
        from pydantic import BaseModel
    except ImportError:
        pytest.skip("pydantic not installed")

    class MyState(BaseModel):
        foo: str

    @action.pydantic(
        reads=["foo"],
        writes=["foo"],
        state_input_type=MyState,
        state_output_type=MyState,
    )
    def good_action(state: MyState):
        return {"foo": state.foo}

    # ensure decoration didn't raise and action is creatable
    from burr.core.action import create_action

    create_action(good_action, name="test")
