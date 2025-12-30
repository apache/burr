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
from typing import AsyncGenerator, Generator, List, Optional, Tuple

import pydantic
import pytest
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.fields import FieldInfo

from burr.core import expr
from burr.core.action import (
    AsyncStreamingResultContainer,
    FunctionBasedAction,
    StreamingResultContainer,
    action,
    streaming_action,
)
from burr.core.application import ApplicationBuilder
from burr.core.state import State
from burr.integrations.pydantic import (
    PydanticTypingSystem,
    _validate_and_extract_signature_types,
    _validate_keys,
    merge_to_state,
    model_from_state,
    model_to_dict,
    pydantic_action,
    pydantic_streaming_action,
    subset_model,
)


# Define a nested Pydantic model
class NestedModel(BaseModel):
    nested_field1: int
    nested_field2: Optional[str] = "default_string"


# Expanded OriginalModel
class OriginalModel(BaseModel):
    foo: int
    bar: str
    baz: Optional[int] = None
    qux: Optional[EmailStr] = Field(None, pattern=r"^[a-z0-9]+@[a-z]+\.[a-z]{2,3}$")
    nested: NestedModel
    list_field: List[int] = [1, 2, 3]


def _assert_fields_match(field_original: FieldInfo, field_new: FieldInfo, made_optional: bool):
    if not made_optional:
        assert field_original.annotation == field_new.annotation
        assert field_new.is_required() == field_original.is_required()
    else:
        assert field_original.annotation == Optional[field_new.annotation]
        assert not field_new.is_required()
    assert field_original.default == field_new.default


@pytest.mark.parametrize(
    "fields,force_optional_fields,model_name_suffix,expected_fields,expected_optionals,expected_name",
    [
        # Test case 1: Subset with optional fields maintained
        (["foo", "qux"], [], "Subset", ["foo", "qux"], [], "OriginalModelSubset"),
        # Test case 2: Subset with forced optional fields
        (["foo", "baz"], ["baz"], "Test", ["foo", "baz"], ["baz"], "OriginalModelTest"),
        # Test case 3: Handling nested models and default values
        (
            ["nested", "list_field"],
            [],
            "NestedSubset",
            ["nested", "list_field"],
            [],
            "OriginalModelNestedSubset",
        ),
        # Test case 4: forcing optional with something that wasn't optional
        (["foo"], ["bar"], "Test", ["foo"], ["bar"], "OriginalModelTest"),
    ],
)
def test_subset_model_success(
    fields: List[str],
    force_optional_fields: List[str],
    model_name_suffix: str,
    expected_fields: List[str],
    expected_optionals: List[str],
    expected_name: str,
):
    """Test the successful creation of subset models with proper fields and optionality."""
    SubsetModel = subset_model(OriginalModel, fields, force_optional_fields, model_name_suffix)
    assert SubsetModel.__name__ == expected_name  # Ensure the model name is correct
    for field in expected_fields:
        assert field in SubsetModel.model_fields  # Ensure the field is in the subset
        if field in expected_optionals:
            _assert_fields_match(
                OriginalModel.model_fields[field],
                SubsetModel.model_fields[field],
                made_optional=False,
            )
        elif field in force_optional_fields:
            _assert_fields_match(
                OriginalModel.model_fields[field],
                SubsetModel.model_fields[field],
                made_optional=True,
            )


def test_subset_model_copy_config():
    class Arbitrary:
        pass

    class MyModelWithConfig(pydantic.BaseModel):
        foo: int
        arbitrary: Arbitrary

        model_config = ConfigDict(arbitrary_types_allowed=True)

    SubsetModel = subset_model(MyModelWithConfig, ["foo", "bar"], [], "Subset")
    assert SubsetModel.__name__ == "MyModelWithConfigSubset"
    assert SubsetModel.model_config == {"arbitrary_types_allowed": True}


def test_merge_to_state():
    model = OriginalModel(
        foo=1,
        bar="bar",
        baz=2,
        qux="email@email.io",
        nested=NestedModel(nested_field1=1),
        list_field=[1, 2],
    )
    write_keys = ["foo", "baz", "nested"]
    state = State(dict(foo=2, list_field=[3, 4], not_written="prior_value"))
    new_state = merge_to_state(model, write_keys, state)
    assert new_state.get_all() == {
        **model_to_dict(model, include=write_keys),
        "not_written": "prior_value",
        "list_field": [3, 4],
    }


def test_model_from_state():
    model_data = dict(
        foo=1,
        bar="bar",
        baz=2,
        qux="email@email.io",
        nested=NestedModel(nested_field1=1),
        list_field=[1, 2],
    )
    state = State(
        model_data,
    )
    model = model_from_state(OriginalModel, state)
    assert model_to_dict(model) == state.get_all()


def _fn_without_state_arg(foo: OriginalModel) -> OriginalModel:
    ...


def _fn_with_incorrect_state_arg(state: int) -> OriginalModel:
    ...


def _fn_with_incorrect_return_type(state: OriginalModel) -> int:
    ...


def _fn_with_no_return_type(state: OriginalModel):
    ...


def _fn_with_untyped_state_arg(state) -> OriginalModel:
    ...


def _fn_correct_same_itype_otype(state: OriginalModel, input_1: int) -> OriginalModel:
    ...


def _fn_correct_diff_itype_otype(state: OriginalModel, input_1: int) -> NestedModel:
    ...


@pytest.mark.parametrize(
    "fn,expected_exception",
    [
        (_fn_without_state_arg, ValueError),
        (_fn_with_incorrect_state_arg, ValueError),
        (_fn_with_incorrect_return_type, ValueError),
        (_fn_with_no_return_type, ValueError),
        (_fn_with_untyped_state_arg, ValueError),
    ],
)
def test__validate_and_extract_signature_types_error(fn, expected_exception):
    with pytest.raises(expected_exception=expected_exception):
        _validate_and_extract_signature_types(fn)


def test__validate_and_extract_signature_types_untyped_state_error_message():
    """Test that the error message is informative when state is not type-annotated."""
    with pytest.raises(ValueError) as excinfo:
        _validate_and_extract_signature_types(_fn_with_untyped_state_arg)
    assert "'state' parameter must be annotated" in str(excinfo.value)


@pytest.mark.parametrize(
    "fn,expected",
    [
        (_fn_correct_same_itype_otype, (OriginalModel, OriginalModel)),
        (_fn_correct_diff_itype_otype, (OriginalModel, NestedModel)),
    ],
)
def test__validate_and_extract_signature_types_success(fn, expected):
    itype, otype = _validate_and_extract_signature_types(fn)
    assert itype == expected[0]
    assert otype == expected[1]


def test__validate_keys():
    _validate_keys(OriginalModel, ["foo", "baz", "nested"], _fn_correct_same_itype_otype)


class StateModelIn(BaseModel):
    foo: int
    bar: str


class StateModelOut(BaseModel):
    baz: Optional[int] = None
    qux: Optional[EmailStr] = Field(default=None)


class StateModel(StateModelIn, StateModelOut):
    pass


class ModelWithDefaults(BaseModel):
    a: int
    b: str = "b"
    c: list[int] = pydantic.Field(default_factory=list)
    d: Optional[str] = None


def test_subset_model_with_defaults():
    SubsetModel = subset_model(ModelWithDefaults, [], ["a", "b", "c", "d"], "Subset")
    assert SubsetModel.__name__ == "ModelWithDefaultsSubset"
    mod = SubsetModel(a=1)
    assert mod.a == 1
    assert mod.b == "b"
    assert mod.c == []
    assert mod.d is None


def test_pydantic_action_returns_correct_results_same_io_modified():
    @pydantic_action(reads=["foo", "bar"], writes=["baz", "qux"])
    def act(state: StateModel, tld: str) -> StateModel:
        state.baz = state.foo + 1
        state.qux = f"{state.bar}@{state.bar}.{tld}"
        return state

    assert hasattr(act, "bind")  # has to have bind
    assert (action_function := getattr(act, FunctionBasedAction.ACTION_FUNCTION, None)) is not None
    assert action_function.inputs == (["tld"], [])
    assert action_function.reads == ["foo", "bar"]
    assert action_function.writes == ["baz", "qux"]
    result = action_function.fn(
        State(dict(foo=1, bar="bar")),
        tld="com",
    )
    # TODO - figure out if we want the old state objects lying around
    # For now we don't care, this will be handled by the state merge operations
    assert result["baz"] == 2
    assert result["qux"] == "bar@bar.com"


async def test_pydantic_action_returns_correct_results_same_io_modified_async():
    @pydantic_action(reads=["foo", "bar"], writes=["baz", "qux"])
    async def act(state: StateModel, tld: str) -> StateModel:
        await asyncio.sleep(0.0001)
        state.baz = state.foo + 1
        state.qux = f"{state.bar}@{state.bar}.{tld}"
        return state

    assert hasattr(act, "bind")  # has to have bind
    assert (action_function := getattr(act, FunctionBasedAction.ACTION_FUNCTION, None)) is not None
    assert action_function.reads == ["foo", "bar"]
    assert action_function.writes == ["baz", "qux"]
    result = await action_function.fn(
        State(dict(foo=1, bar="bar")),
        tld="com",
    )
    # TODO - figure out if we want the old state objects lying around
    # For now we don't care, this will be handled by the state merge operations
    assert result["baz"] == 2
    assert result["qux"] == "bar@bar.com"


def test_pydantic_action_returns_correct_results_different_io_modified():
    @pydantic_action(reads=["foo", "bar"], writes=["baz", "qux"])
    def act(state: StateModelIn, tld: str) -> StateModelOut:
        return StateModelOut(baz=state.foo + 1, qux=f"{state.bar}@{state.bar}.{tld}")

    assert hasattr(act, "bind")  # has to have bind
    assert (action_function := getattr(act, FunctionBasedAction.ACTION_FUNCTION, None)) is not None
    assert action_function.reads == ["foo", "bar"]
    assert action_function.writes == ["baz", "qux"]
    result = action_function.fn(
        State(dict(foo=1, bar="bar")),
        tld="com",
    )
    # TODO - figure out if we want the old state objects lying around
    # For now we don't care, this will be handled by the state merge operations
    assert result["baz"] == 2
    assert result["qux"] == "bar@bar.com"


def test_pydantic_action_returns_correct_results_different_io_modified_specified_type_in_decorator():
    @pydantic_action(
        reads=["foo", "bar"],
        writes=["baz", "qux"],
        state_input_type=StateModelIn,
        state_output_type=StateModelOut,
    )
    def act(state, tld):
        return StateModelOut(baz=state.foo + 1, qux=f"{state.bar}@{state.bar}.{tld}")

    assert hasattr(act, "bind")  # has to have bind
    assert (action_function := getattr(act, FunctionBasedAction.ACTION_FUNCTION, None)) is not None
    assert action_function.reads == ["foo", "bar"]
    assert action_function.writes == ["baz", "qux"]
    result = action_function.fn(
        State(dict(foo=1, bar="bar")),
        tld="com",
    )
    # TODO - figure out if we want the old state objects lying around
    # For now we don't care, this will be handled by the state merge operations
    assert result["baz"] == 2
    assert result["qux"] == "bar@bar.com"


async def test_pydantic_action_returns_correct_results_different_io_modified_async():
    @pydantic_action(reads=["foo", "bar"], writes=["baz", "qux"])
    async def act(state: StateModelIn, tld: str) -> StateModelOut:
        await asyncio.sleep(0.0001)
        return StateModelOut(baz=state.foo + 1, qux=f"{state.bar}@{state.bar}.{tld}")

    assert hasattr(act, "bind")  # has to have bind
    assert (action_function := getattr(act, FunctionBasedAction.ACTION_FUNCTION, None)) is not None
    assert action_function.inputs == (["tld"], [])
    assert action_function.reads == ["foo", "bar"]
    assert action_function.writes == ["baz", "qux"]
    result = await action_function.fn(
        State(dict(foo=1, bar="bar")),
        tld="com",
    )
    # TODO - figure out if we want the old state objects lying around
    # For now we don't care, this will be handled by the state merge operations
    assert result["baz"] == 2
    assert result["qux"] == "bar@bar.com"


def test_pydantic_action_incorrect_reads():
    def act(state: StateModel, tld: str) -> StateModel:
        ...

    with pytest.raises(ValueError, match="are not present in the model"):
        pydantic_action(reads=["foo", "bar", "not_present"], writes=["baz", "qux"])(act)


def test_pydantic_action_incorrect_writes():
    def act(state: StateModel, tld: str) -> StateModel:
        ...

    with pytest.raises(ValueError, match="are not present in the model"):
        pydantic_action(reads=["foo", "bar"], writes=["baz", "qux", "not_prsent"])(act)


# Simple model to test streaming pydantic model
class AppStateModel(BaseModel):
    count: int
    times_called: int
    other: bool = Field(default=False)
    yet_another: float = Field(default=0.0)


class IntermediateModel(BaseModel):
    result: int


def test_streaming_pydantic_action_same_io():
    @pydantic_streaming_action(
        reads=["count", "times_called"],
        writes=["count", "times_called"],
        stream_type=IntermediateModel,
        state_input_type=AppStateModel,
        state_output_type=AppStateModel,
    )
    def act(
        state: AppStateModel, total_count: int
    ) -> Generator[Tuple[IntermediateModel, Optional[AppStateModel]], None, None]:
        initial_value = state.count
        for i in range(initial_value, initial_value + total_count):
            yield IntermediateModel(result=i), None
            state.count = i
        state.times_called += 1
        yield IntermediateModel(result=state.count), state

    assert hasattr(act, "bind")  # has to have bind
    assert (action_function := getattr(act, FunctionBasedAction.ACTION_FUNCTION, None)) is not None
    assert action_function.inputs == (["total_count"], [])
    gen = action_function.fn(
        State(dict(count=1, times_called=0), typing_system=PydanticTypingSystem(AppStateModel)),
        total_count=5,
    )
    result = list(gen)
    assert len(result) == 6
    assert [item[0].result for item in result] == [1, 2, 3, 4, 5, 5]
    assert all([isinstance(item[0], IntermediateModel) for item in result])
    assert all([item[1] is None for item in result[:-1]])
    assert isinstance(final_state := result[-1][1], State)
    assert final_state["count"] == 5
    assert final_state["times_called"] == 1
    assert final_state.data.count == 5
    assert final_state.data.times_called == 1


async def test_streaming_pydantic_action_same_io_async():
    @pydantic_streaming_action(
        reads=["count", "times_called"],
        writes=["count", "times_called"],
        stream_type=IntermediateModel,
        state_input_type=AppStateModel,
        state_output_type=AppStateModel,
    )
    async def act(
        state: AppStateModel, total_count: int
    ) -> AsyncGenerator[Tuple[IntermediateModel, Optional[AppStateModel]], None]:
        initial_value = state.count
        for i in range(initial_value, initial_value + total_count):
            await asyncio.sleep(0.0001)
            yield IntermediateModel(result=i), None
            state.count = i
        state.times_called += 1
        await asyncio.sleep(0.0001)
        yield IntermediateModel(result=state.count), state

    assert hasattr(act, "bind")  # has to have bind
    assert (action_function := getattr(act, FunctionBasedAction.ACTION_FUNCTION, None)) is not None
    assert action_function.inputs == (["total_count"], [])
    gen = action_function.fn(
        State(dict(count=1, times_called=0), typing_system=PydanticTypingSystem(AppStateModel)),
        total_count=5,
    )
    result = [item async for item in gen]
    assert len(result) == 6
    assert [item[0].result for item in result] == [1, 2, 3, 4, 5, 5]
    assert all([isinstance(item[0], IntermediateModel) for item in result])
    assert all([item[1] is None for item in result[:-1]])
    assert isinstance(final_state := result[-1][1], State)
    assert final_state["count"] == 5
    assert final_state["times_called"] == 1
    assert final_state.data.count == 5
    assert final_state.data.times_called == 1


class OutputModel(BaseModel):
    completed: bool = Field(default=False)
    sum_of_values: int = Field(default=0)


class InputModel(BaseModel):
    count: int
    increment_by: int
    other_value: Optional[str] = None
    yet_another_value: Optional[float] = None


class StateModelStreaming(InputModel, OutputModel):
    pass


def test_streaming_pydantic_action_different_io():
    @pydantic_streaming_action(
        reads=["count", "increment_by"],
        writes=["completed", "sum_of_values"],
        stream_type=IntermediateModel,
        state_input_type=InputModel,
        state_output_type=OutputModel,
    )
    def act(
        state: InputModel, total_count: int
    ) -> Generator[Tuple[IntermediateModel, Optional[OutputModel]], None, None]:
        sum_of_values = 0
        for i in range(total_count):
            yield IntermediateModel(result=i), None
            sum_of_values += state.increment_by
        yield IntermediateModel(result=total_count), OutputModel(
            completed=True, sum_of_values=sum_of_values
        )

    assert hasattr(act, "bind")  # has to have bind
    assert (action_function := getattr(act, FunctionBasedAction.ACTION_FUNCTION, None)) is not None
    assert action_function.inputs == (["total_count"], [])
    gen = action_function.fn(
        State(
            dict(count=1, increment_by=2), typing_system=PydanticTypingSystem(StateModelStreaming)
        ),
        total_count=5,
    )
    assert action_function.inputs == (["total_count"], [])
    result = list(gen)
    assert len(result) == 6
    assert [item[0].result for item in result] == [0, 1, 2, 3, 4, 5]
    assert all([isinstance(item[0], IntermediateModel) for item in result])
    assert all([item[1] is None for item in result[:-1]])
    assert isinstance(final_state := result[-1][1], State)
    assert final_state["completed"] is True
    assert final_state["sum_of_values"] == 10
    assert final_state.data.completed is True
    assert final_state.data.sum_of_values == 10


async def test_streaming_pydantic_action_different_io_async():
    @pydantic_streaming_action(
        reads=["count", "increment_by"],
        writes=["completed", "sum_of_values"],
        stream_type=IntermediateModel,
        state_input_type=InputModel,
        state_output_type=OutputModel,
    )
    async def act(
        state: InputModel, total_count: int
    ) -> AsyncGenerator[Tuple[IntermediateModel, Optional[OutputModel]], None]:
        sum_of_values = 0
        for i in range(total_count):
            await asyncio.sleep(0.0001)
            yield IntermediateModel(result=i), None
            sum_of_values += state.increment_by
        await asyncio.sleep(0.0001)
        yield IntermediateModel(result=total_count), OutputModel(
            completed=True, sum_of_values=sum_of_values
        )

    assert hasattr(act, "bind")  # has to have bind
    assert (action_function := getattr(act, FunctionBasedAction.ACTION_FUNCTION, None)) is not None
    assert action_function.inputs == (["total_count"], [])
    gen = action_function.fn(
        State(
            dict(count=1, increment_by=2), typing_system=PydanticTypingSystem(StateModelStreaming)
        ),
        total_count=5,
    )
    result = [item async for item in gen]
    assert len(result) == 6
    assert [item[0].result for item in result] == [0, 1, 2, 3, 4, 5]
    assert all([isinstance(item[0], IntermediateModel) for item in result])
    assert all([item[1] is None for item in result[:-1]])
    assert isinstance(final_state := result[-1][1], State)
    assert final_state["completed"] is True
    assert final_state["sum_of_values"] == 10
    assert final_state.data.completed is True
    assert final_state.data.sum_of_values == 10


class CounterExampleAppState(pydantic.BaseModel):
    count: int = 0
    counter_called_times: int = 0
    num_counter_calls: int = 10
    final_result: int = 0


def test_end_to_end_pydantic(tmpdir):
    @action.pydantic(
        reads=["count", "counter_called_times"],
        writes=["count", "counter_called_times"],
    )
    def counter(state: CounterExampleAppState, increment_by: int) -> CounterExampleAppState:
        state.count += increment_by
        state.counter_called_times += 1
        return state

    @action.pydantic(
        reads=["count"],
        writes=["final_result"],
    )
    def final_result(state: CounterExampleAppState) -> CounterExampleAppState:
        state.final_result = state.count
        return state

    app = (
        ApplicationBuilder()
        .with_actions(counter=counter, final_result=final_result)
        .with_entrypoint("counter")
        .with_tracker(tracker="local", params={"storage_dir": tmpdir})
        .with_typing(PydanticTypingSystem(CounterExampleAppState))
        .with_state(CounterExampleAppState())
        .with_transitions(
            ("counter", "final_result", expr("counter_called_times == num_counter_calls")),
            ("counter", "counter"),
        )
        .build()
    )
    act, result, state = app.run(halt_after=["final_result"], inputs={"increment_by": 2})
    assert isinstance(state.data, CounterExampleAppState)

    assert state.data.final_result == 20
    assert state.data.counter_called_times == 10
    assert state.data.count == 20


async def test_end_to_end_pydantic_async(tmpdir):
    @action.pydantic(
        reads=["count", "counter_called_times"],
        writes=["count", "counter_called_times"],
    )
    async def counter(state: CounterExampleAppState, increment_by: int) -> CounterExampleAppState:
        await asyncio.sleep(0.0001)
        state.count += increment_by
        state.counter_called_times += 1
        return state

    @action.pydantic(
        reads=["count"],
        writes=["final_result"],
    )
    async def final_result(state: CounterExampleAppState) -> CounterExampleAppState:
        await asyncio.sleep(0.0001)
        state.final_result = state.count
        return state

    app = (
        ApplicationBuilder()
        .with_actions(counter=counter, final_result=final_result)
        .with_entrypoint("counter")
        .with_tracker(tracker="local", params={"storage_dir": tmpdir})
        .with_typing(PydanticTypingSystem(CounterExampleAppState))
        .with_state(CounterExampleAppState())
        .with_transitions(
            ("counter", "final_result", expr("counter_called_times == num_counter_calls")),
            ("counter", "counter"),
        )
        .build()
    )
    *_, state = await app.arun(halt_after=["final_result"], inputs={"increment_by": 2})
    assert isinstance(state.data, CounterExampleAppState)

    assert state.data.final_result == 20
    assert state.data.counter_called_times == 10
    assert state.data.count == 20


class IntermediateStreamModel(BaseModel):
    result: int


def test_end_to_end_pydantic_streaming(tmpdir):
    @action.pydantic(
        reads=["count", "counter_called_times"],
        writes=["count", "counter_called_times"],
    )
    def counter(state: CounterExampleAppState, increment_by: int) -> CounterExampleAppState:
        state.count += increment_by
        state.counter_called_times += 1
        return state

    @streaming_action.pydantic(
        reads=["count"],
        writes=["final_result"],
        state_output_type=CounterExampleAppState,
        state_input_type=CounterExampleAppState,
        stream_type=IntermediateModel,
    )
    def final_result_streamed(
        state: CounterExampleAppState,
    ) -> Generator[Tuple[IntermediateModel, Optional[CounterExampleAppState]], None, None]:
        for i in range(state.count):
            yield IntermediateModel(result=i), None
        state.final_result = state.count
        yield IntermediateModel(result=state.count), state

    app = (
        ApplicationBuilder()
        .with_actions(counter=counter, final_result=final_result_streamed)
        .with_entrypoint("counter")
        .with_tracker(tracker="local", params={"storage_dir": tmpdir})
        .with_typing(PydanticTypingSystem(CounterExampleAppState))
        .with_state(CounterExampleAppState())
        .with_transitions(
            ("counter", "final_result", expr("counter_called_times == num_counter_calls")),
            ("counter", "counter"),
        )
        .build()
    )
    _, container = app.stream_result(halt_after=["final_result"], inputs={"increment_by": 2})  # type: ignore
    container: StreamingResultContainer[CounterExampleAppState, IntermediateModel]
    results = list(container)
    assert all(isinstance(item, IntermediateModel) for item in results)
    result, state = container.get()

    assert state.data.final_result == 20
    assert state.data.counter_called_times == 10
    assert state.data.count == 20
    assert isinstance(result, IntermediateModel)
    assert result.result == 20


async def test_end_to_end_pydantic_streaming_async(tmpdir):
    @action.pydantic(
        reads=["count", "counter_called_times"],
        writes=["count", "counter_called_times"],
    )
    async def counter(state: CounterExampleAppState, increment_by: int) -> CounterExampleAppState:
        await asyncio.sleep(0.0001)
        state.count += increment_by
        state.counter_called_times += 1
        return state

    @streaming_action.pydantic(
        reads=["count"],
        writes=["final_result"],
        state_output_type=CounterExampleAppState,
        state_input_type=CounterExampleAppState,
        stream_type=IntermediateModel,
    )
    async def final_result_streamed(
        state: CounterExampleAppState,
    ) -> AsyncGenerator[Tuple[IntermediateModel, Optional[CounterExampleAppState]], None]:
        for i in range(state.count):
            yield IntermediateModel(result=i), None
        state.final_result = state.count
        yield IntermediateModel(result=state.count), state

    app = (
        ApplicationBuilder()
        .with_actions(counter=counter, final_result=final_result_streamed)
        .with_entrypoint("counter")
        .with_tracker(tracker="local", params={"storage_dir": tmpdir})
        .with_typing(PydanticTypingSystem(CounterExampleAppState))
        .with_state(CounterExampleAppState())
        .with_transitions(
            ("counter", "final_result", expr("counter_called_times == num_counter_calls")),
            ("counter", "counter"),
        )
        .build()
    )
    _, container = await app.astream_result(halt_after=["final_result"], inputs={"increment_by": 2})  # type: ignore
    container: AsyncStreamingResultContainer[CounterExampleAppState, IntermediateModel]
    results = [item async for item in container]
    assert all(isinstance(item, IntermediateModel) for item in results)
    result, state = await container.get()

    assert state.data.final_result == 20
    assert state.data.counter_called_times == 10
    assert state.data.count == 20
    assert isinstance(result, IntermediateModel)
    assert result.result == 20
