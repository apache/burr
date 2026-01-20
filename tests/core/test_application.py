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
import collections
import datetime
import logging
import typing
import uuid
from typing import Any, Awaitable, Callable, Dict, Generator, Literal, Optional, Tuple, Union

from burr.core.application import ApplicationBuilder
from burr.core.state import State
from burr.core.persistence import (
    BaseStatePersister,
    BaseStateLoader,
    PersistedStateData,
)

import pytest

from burr.core import State
from burr.core.action import (
    DEFAULT_SCHEMA,
    Action,
    AsyncGenerator,
    AsyncStreamingAction,
    Condition,
    Reducer,
    Result,
    SingleStepAction,
    SingleStepStreamingAction,
    StreamingAction,
    action,
    default,
    expr,
)
from burr.core.application import (
    PRIOR_STEP,
    Application,
    ApplicationBuilder,
    ApplicationContext,
    _adjust_single_step_output,
    _arun_function,
    _arun_multi_step_streaming_action,
    _arun_single_step_action,
    _arun_single_step_streaming_action,
    _remap_dunder_parameters,
    _run_function,
    _run_multi_step_streaming_action,
    _run_reducer,
    _run_single_step_action,
    _run_single_step_streaming_action,
    _validate_reducer_writes,
    _validate_start,
)
from burr.core.graph import Graph, GraphBuilder, Transition
from burr.core.persistence import (
    AsyncDevNullPersister,
    BaseStatePersister,
    DevNullPersister,
    PersistedStateData,
    SQLLitePersister,
)
from burr.core.typing import TypingSystem
from burr.lifecycle import (
    PostRunStepHook,
    PostRunStepHookAsync,
    PreRunStepHook,
    PreRunStepHookAsync,
    internal,
)
from burr.lifecycle.base import (
    ExecuteMethod,
    PostApplicationCreateHook,
    PostApplicationExecuteCallHook,
    PostApplicationExecuteCallHookAsync,
    PostEndStreamHook,
    PostStreamItemHook,
    PostStreamItemHookAsync,
    PreApplicationExecuteCallHook,
    PreApplicationExecuteCallHookAsync,
    PreStartStreamHook,
    PreStartStreamHookAsync,
)
from burr.lifecycle.internal import LifecycleAdapterSet
from burr.tracking.base import SyncTrackingClient


class PassedInAction(Action):
    def __init__(
        self,
        reads: list[str],
        writes: list[str],
        fn: Callable[..., dict],
        update_fn: Callable[[dict, State], State],
        inputs: list[str],
    ):
        super(PassedInAction, self).__init__()
        self._reads = reads
        self._writes = writes
        self._fn = fn
        self._update_fn = update_fn
        self._inputs = inputs

    def run(self, state: State, **run_kwargs) -> dict:
        return self._fn(state, **run_kwargs)

    @property
    def inputs(self) -> list[str]:
        return self._inputs

    def update(self, result: dict, state: State) -> State:
        return self._update_fn(result, state)

    @property
    def reads(self) -> list[str]:
        return self._reads

    @property
    def writes(self) -> list[str]:
        return self._writes


class PassedInActionAsync(PassedInAction):
    def __init__(
        self,
        reads: list[str],
        writes: list[str],
        fn: Callable[..., Awaitable[dict]],
        update_fn: Callable[[dict, State], State],
        inputs: list[str],
    ):
        super().__init__(reads=reads, writes=writes, fn=fn, update_fn=update_fn, inputs=inputs)  # type: ignore

    async def run(self, state: State, **run_kwargs) -> dict:
        return await self._fn(state, **run_kwargs)


base_counter_action = PassedInAction(
    reads=["count"],
    writes=["count"],
    fn=lambda state: {"count": state.get("count", 0) + 1},
    update_fn=lambda result, state: state.update(**result),
    inputs=[],
)

base_counter_action_with_inputs = PassedInAction(
    reads=["count"],
    writes=["count"],
    fn=lambda state, additional_increment: {
        "count": state.get("count", 0) + 1 + additional_increment
    },
    update_fn=lambda result, state: state.update(**result),
    inputs=["additional_increment"],
)


class StreamEventCaptureTracker(PreStartStreamHook, PostStreamItemHook, PostEndStreamHook):
    def post_end_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        self.post_end_stream_calls.append((action, locals()))

    def __init__(self):
        self.pre_start_stream_calls = []
        self.post_stream_item_calls = []
        self.post_end_stream_calls = []

    def pre_start_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        self.pre_start_stream_calls.append((action, locals()))

    def post_stream_item(
        self,
        *,
        item: Any,
        item_index: int,
        stream_initialize_time: datetime.datetime,
        first_stream_item_start_time: datetime.datetime,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        self.post_stream_item_calls.append((action, locals()))


class StreamEventCaptureTrackerAsync(
    PreStartStreamHookAsync, PostStreamItemHookAsync, PostEndStreamHook
):
    def __init__(self):
        self.pre_start_stream_calls = []
        self.post_stream_item_calls = []
        self.post_end_stream_calls = []

    async def pre_start_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        self.pre_start_stream_calls.append((action, locals()))

    async def post_stream_item(
        self,
        *,
        item: Any,
        item_index: int,
        stream_initialize_time: datetime.datetime,
        first_stream_item_start_time: datetime.datetime,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        self.post_stream_item_calls.append((action, locals()))

    def post_end_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        self.post_end_stream_calls.append((action, locals()))


class CallCaptureTracker(
    PreRunStepHook,
    PostRunStepHook,
    PreApplicationExecuteCallHook,
    PostApplicationExecuteCallHook,
):
    def __init__(self):
        self.pre_called = []
        self.post_called = []
        self.pre_run_execute_calls = []
        self.post_run_execute_calls = []

    def pre_run_step(
        self,
        *,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        state: "State",
        action: "Action",
        inputs: Dict[str, Any],
        **future_kwargs: Any,
    ):
        self.pre_called.append((action.name, locals()))

    def post_run_step(
        self,
        *,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        state: "State",
        action: "Action",
        result: Optional[Dict[str, Any]],
        exception: Exception,
        **future_kwargs: Any,
    ):
        self.post_called.append((action.name, locals()))

    def pre_run_execute_call(
        self,
        *,
        app_id: str,
        partition_key: str,
        state: "State",
        method: ExecuteMethod,
        **future_kwargs: Any,
    ):
        self.pre_run_execute_calls.append(("pre", locals()))

    def post_run_execute_call(
        self,
        *,
        app_id: str,
        partition_key: str,
        state: "State",
        method: ExecuteMethod,
        exception: Optional[Exception],
        **future_kwargs,
    ):
        self.post_run_execute_calls.append(("post", locals()))


class ExecuteMethodTrackerAsync(
    PreApplicationExecuteCallHookAsync, PostApplicationExecuteCallHookAsync
):
    def __init__(self):
        self.pre_run_execute_calls = []
        self.post_run_execute_calls = []

    async def pre_run_execute_call(
        self,
        *,
        app_id: str,
        partition_key: str,
        state: "State",
        method: ExecuteMethod,
        **future_kwargs: Any,
    ):
        self.pre_run_execute_calls.append(("pre", locals()))

    async def post_run_execute_call(
        self,
        *,
        app_id: str,
        partition_key: str,
        state: "State",
        method: ExecuteMethod,
        exception: Optional[Exception],
        **future_kwargs,
    ):
        self.post_run_execute_calls.append(("post", locals()))


class ActionTrackerAsync(PreRunStepHookAsync, PostRunStepHookAsync):
    def __init__(self):
        self.pre_called = []
        self.post_called = []

    async def pre_run_step(self, *, action: Action, **future_kwargs):
        await asyncio.sleep(0.0001)
        self.pre_called.append((action.name, future_kwargs))

    async def post_run_step(self, *, action: Action, **future_kwargs):
        await asyncio.sleep(0.0001)
        self.post_called.append((action.name, future_kwargs))


async def _counter_update_async(state: State, additional_increment: int = 0) -> dict:
    await asyncio.sleep(0.0001)  # just so we can make this *truly* async
    # does not matter, but more accurately simulates an async function
    return {"count": state.get("count", 0) + 1 + additional_increment}


base_counter_action_async = PassedInActionAsync(
    reads=["count"],
    writes=["count"],
    fn=_counter_update_async,
    update_fn=lambda result, state: state.update(**result),
    inputs=[],
)

base_counter_action_with_inputs_async = PassedInActionAsync(
    reads=["count"],
    writes=["count"],
    fn=lambda state, additional_increment: _counter_update_async(
        state, additional_increment=additional_increment
    ),
    update_fn=lambda result, state: state.update(**result),
    inputs=["additional_increment"],
)


class BrokenStepException(Exception):
    pass


base_broken_action = PassedInAction(
    reads=[],
    writes=[],
    fn=lambda x: exec("raise(BrokenStepException(x))"),
    update_fn=lambda result, state: state,
    inputs=[],
)

base_broken_action_async = PassedInActionAsync(
    reads=[],
    writes=[],
    fn=lambda x: exec("raise(BrokenStepException(x))"),
    update_fn=lambda result, state: state,
    inputs=[],
)


async def incorrect(x):
    return "not a dict"


base_action_incorrect_result_type = PassedInAction(
    reads=[],
    writes=[],
    fn=lambda x: "not a dict",
    update_fn=lambda result, state: state,
    inputs=[],
)

base_action_incorrect_result_type_async = PassedInActionAsync(
    reads=[],
    writes=[],
    fn=incorrect,
    update_fn=lambda result, state: state,
    inputs=[],
)


def test__run_function():
    """Tests that we can run a function"""
    action = base_counter_action
    state = State({})
    result = _run_function(action, state, inputs={}, name=action.name)
    assert result == {"count": 1}


def test__run_function_with_inputs():
    """Tests that we can run a function"""
    action = base_counter_action_with_inputs
    state = State({})
    result = _run_function(action, state, inputs={"additional_increment": 1}, name=action.name)
    assert result == {"count": 2}


def test__run_function_cant_run_async():
    """Tests that we can't run an async function"""
    action = base_counter_action_async
    state = State({})
    with pytest.raises(ValueError, match="async"):
        _run_function(action, state, inputs={}, name=action.name)


def test__run_function_incorrect_result_type():
    """Tests that we can run an async function"""
    action = base_action_incorrect_result_type
    state = State({})
    with pytest.raises(ValueError, match="returned a non-dict"):
        _run_function(action, state, inputs={}, name=action.name)


def test__run_reducer_modifies_state():
    """Tests that we can run a reducer and it behaves as expected"""
    reducer = PassedInAction(
        reads=["count"],
        writes=["count"],
        fn=...,
        update_fn=lambda result, state: state.update(**result),
        inputs=[],
    )
    state = State({"count": 0})
    state = _run_reducer(reducer, state, {"count": 1}, "reducer")
    assert state["count"] == 1


def test__run_reducer_deletes_state():
    """Tests that we can run a reducer that deletes an item from state"""
    reducer = PassedInAction(
        reads=["count"],
        writes=[],  # TODO -- figure out how we can better know that it deletes items...ß
        fn=...,
        update_fn=lambda result, state: state.wipe(delete=["count"]),
        inputs=[],
    )
    state = State({"count": 0})
    state = _run_reducer(reducer, state, {}, "deletion_reducer")
    assert "count" not in state


def test__validate_reducer_writes_with_state_keys_returning_list():
    """Tests that _validate_reducer_writes works when state.keys() returns a list.

    This is a regression test for a bug where state.keys() could return a list
    instead of a set, causing a TypeError when trying to do set subtraction.
    """
    # Create a reducer with some expected writes
    reducer = PassedInAction(
        reads=["input"],
        writes=["output", "result"],
        fn=...,
        update_fn=lambda result, state: state.update(**result),
        inputs=[],
    )

    # Create a state that has all the required writes
    state = State({"input": 1, "output": 2, "result": 3})

    # This should not raise a TypeError even if state.keys() returns a list
    # (which was the original bug)
    _validate_reducer_writes(reducer, state, "test_action")


def test__validate_reducer_writes_raises_on_missing_keys():
    """Tests that _validate_reducer_writes raises ValueError when required keys are missing."""
    # Create a reducer with some expected writes
    reducer = PassedInAction(
        reads=["input"],
        writes=["output", "result", "missing_key"],
        fn=...,
        update_fn=lambda result, state: state.update(**result),
        inputs=[],
    )

    # Create a state that is missing some required writes
    state = State({"input": 1, "output": 2, "result": 3})

    # This should raise a ValueError for missing "missing_key"
    with pytest.raises(ValueError, match="missing_key"):
        _validate_reducer_writes(reducer, state, "test_action")


async def test__arun_function():
    """Tests that we can run an async function"""
    action = base_counter_action_async
    state = State({})
    result = await _arun_function(action, state, inputs={}, name=action.name)
    assert result == {"count": 1}


async def test__arun_function_incorrect_result_type():
    """Tests that we can run an async function"""
    action = base_action_incorrect_result_type_async
    state = State({})
    with pytest.raises(ValueError, match="returned a non-dict"):
        await _arun_function(action, state, inputs={}, name=action.name)


async def test__arun_function_with_inputs():
    """Tests that we can run an async function"""
    action = base_counter_action_with_inputs_async
    state = State({})
    result = await _arun_function(
        action, state, inputs={"additional_increment": 1}, name=action.name
    )
    assert result == {"count": 2}


def test_run_reducer_errors_missing_writes():
    class BrokenReducer(Reducer):
        def update(self, result: dict, state: State) -> State:
            return state.update(present_value=1)

        @property
        def writes(self) -> list[str]:
            return ["missing_value", "present_value"]

    reducer = BrokenReducer()
    state = State()
    with pytest.raises(ValueError, match="missing_value"):
        _run_reducer(reducer, state, {}, "broken_reducer")


def test_run_single_step_action_errors_missing_writes():
    class BrokenAction(SingleStepAction):
        @property
        def reads(self) -> list[str]:
            return []

        def run_and_update(self, state: State, **run_kwargs) -> Tuple[dict, State]:
            return {"present_value": 1}, state.update(present_value=1)

        @property
        def writes(self) -> list[str]:
            return ["missing_value", "present_value"]

    action = BrokenAction()
    state = State()
    with pytest.raises(ValueError, match="missing_value"):
        _run_single_step_action(action, state, inputs={})


async def test_arun_single_step_action_errors_missing_writes():
    class BrokenAction(SingleStepAction):
        @property
        def reads(self) -> list[str]:
            return []

        async def run_and_update(self, state: State, **run_kwargs) -> Tuple[dict, State]:
            await asyncio.sleep(0.0001)  # just so we can make this *truly* async
            return {"present_value": 1}, state.update(present_value=1)

        @property
        def writes(self) -> list[str]:
            return ["missing_value", "present_value"]

    action = BrokenAction()
    state = State()
    with pytest.raises(ValueError, match="missing_value"):
        await _arun_single_step_action(action, state, inputs={})


def test_run_single_step_streaming_action_errors_missing_write():
    class BrokenAction(SingleStepStreamingAction):
        def stream_run_and_update(
            self, state: State, **run_kwargs
        ) -> Generator[Tuple[dict, Optional[State]], None, None]:
            yield {}, None
            yield {"present_value": 1}, state.update(present_value=1)

        @property
        def reads(self) -> list[str]:
            return []

        @property
        def writes(self) -> list[str]:
            return ["missing_value", "present_value"]

    action = BrokenAction()
    state = State()
    with pytest.raises(ValueError, match="missing_value"):
        gen = _run_single_step_streaming_action(
            action, state, inputs={}, sequence_id=0, partition_key="partition_key", app_id="app_id"
        )
        collections.deque(gen, maxlen=0)  # exhaust the generator


async def test_run_single_step_streaming_action_errors_missing_write_async():
    class BrokenAction(SingleStepStreamingAction):
        async def stream_run_and_update(
            self, state: State, **run_kwargs
        ) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
            yield {}, None
            yield {"present_value": 1}, state.update(present_value=1)

        @property
        def reads(self) -> list[str]:
            return []

        @property
        def writes(self) -> list[str]:
            return ["missing_value", "present_value"]

    action = BrokenAction()
    state = State()
    with pytest.raises(ValueError, match="missing_value"):
        gen = _arun_single_step_streaming_action(
            action,
            state,
            inputs={},
            sequence_id=0,
            app_id="app_id",
            partition_key="partition_key",
            lifecycle_adapters=LifecycleAdapterSet(),
        )
        [result async for result in gen]  # exhaust the generator


def test_run_multi_step_streaming_action_errors_missing_write():
    class BrokenAction(StreamingAction):
        def stream_run(self, state: State, **run_kwargs) -> Generator[dict, None, None]:
            yield {}
            yield {"present_value": 1}

        def update(self, result: dict, state: State) -> State:
            return state.update(present_value=1)

        @property
        def reads(self) -> list[str]:
            return []

        @property
        def writes(self) -> list[str]:
            return ["missing_value", "present_value"]

    action = BrokenAction()
    state = State()
    with pytest.raises(ValueError, match="missing_value"):
        gen = _run_multi_step_streaming_action(
            action, state, inputs={}, sequence_id=0, partition_key="partition_key", app_id="app_id"
        )
        collections.deque(gen, maxlen=0)  # exhaust the generator


class SingleStepCounter(SingleStepAction):
    def run_and_update(self, state: State, **run_kwargs) -> Tuple[dict, State]:
        result = {"count": state["count"] + 1 + sum([0] + list(run_kwargs.values()))}
        return result, state.update(**result).append(tracker=result["count"])

    @property
    def reads(self) -> list[str]:
        return ["count"]

    @property
    def writes(self) -> list[str]:
        return ["count", "tracker"]


class SingleStepCounterWithInputs(SingleStepCounter):
    @property
    def inputs(self) -> list[str]:
        return ["additional_increment"]


class SingleStepActionIncorrectResultType(SingleStepAction):
    def run_and_update(self, state: State, **run_kwargs) -> Tuple[dict, State]:
        return "not a dict", state

    @property
    def reads(self) -> list[str]:
        return []

    @property
    def writes(self) -> list[str]:
        return []


class SingleStepActionIncorrectResultTypeAsync(SingleStepActionIncorrectResultType):
    async def run_and_update(self, state: State, **run_kwargs) -> Tuple[dict, State]:
        return "not a dict", state


class SingleStepCounterAsync(SingleStepCounter):
    async def run_and_update(self, state: State, **run_kwargs) -> Tuple[dict, State]:
        await asyncio.sleep(0.0001)  # just so we can make this *truly* async
        return super(SingleStepCounterAsync, self).run_and_update(state, **run_kwargs)

    @property
    def reads(self) -> list[str]:
        return ["count"]

    @property
    def writes(self) -> list[str]:
        return ["count", "tracker"]


class SingleStepCounterWithInputsAsync(SingleStepCounterAsync):
    @property
    def inputs(self) -> list[str]:
        return ["additional_increment"]


class StreamingCounter(StreamingAction):
    def stream_run(self, state: State, **run_kwargs) -> Generator[dict, None, None]:
        if "steps_per_count" in run_kwargs:
            steps_per_count = run_kwargs["granularity"]
        else:
            steps_per_count = 10
        count = state["count"]
        for i in range(steps_per_count):
            yield {"count": count + ((i + 1) / 10)}
        yield {"count": count + 1}

    @property
    def reads(self) -> list[str]:
        return ["count"]

    @property
    def writes(self) -> list[str]:
        return ["count", "tracker"]

    def update(self, result: dict, state: State) -> State:
        return state.update(**result).append(tracker=result["count"])


class AsyncStreamingCounter(AsyncStreamingAction):
    async def stream_run(self, state: State, **run_kwargs) -> AsyncGenerator[dict, None]:
        if "steps_per_count" in run_kwargs:
            steps_per_count = run_kwargs["granularity"]
        else:
            steps_per_count = 10
        count = state["count"]
        for i in range(steps_per_count):
            await asyncio.sleep(0.01)
            yield {"count": count + (i + 1) / 10}
        await asyncio.sleep(0.01)
        yield {"count": count + 1}

    @property
    def reads(self) -> list[str]:
        return ["count"]

    @property
    def writes(self) -> list[str]:
        return ["count", "tracker"]

    def update(self, result: dict, state: State) -> State:
        return state.update(**result).append(tracker=result["count"])


class SingleStepStreamingCounter(SingleStepStreamingAction):
    def stream_run_and_update(
        self, state: State, **run_kwargs
    ) -> Generator[Tuple[dict, Optional[State]], None, None]:
        steps_per_count = run_kwargs.get("granularity", 10)
        count = state["count"]
        for i in range(steps_per_count):
            yield {"count": count + ((i + 1) / 10)}, None
        yield {"count": count + 1}, state.update(count=count + 1).append(tracker=count + 1)

    @property
    def reads(self) -> list[str]:
        return ["count"]

    @property
    def writes(self) -> list[str]:
        return ["count", "tracker"]


class SingleStepStreamingCounterAsync(SingleStepStreamingAction):
    async def stream_run_and_update(
        self, state: State, **run_kwargs
    ) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
        steps_per_count = run_kwargs.get("granularity", 10)
        count = state["count"]
        for i in range(steps_per_count):
            await asyncio.sleep(0.01)
            yield {"count": count + ((i + 1) / 10)}, None
        await asyncio.sleep(0.01)
        yield {"count": count + 1}, state.update(count=count + 1).append(tracker=count + 1)

    @property
    def reads(self) -> list[str]:
        return ["count"]

    @property
    def writes(self) -> list[str]:
        return ["count", "tracker"]


class StreamingActionIncorrectResultType(StreamingAction):
    def stream_run(self, state: State, **run_kwargs) -> Generator[dict, None, dict]:
        yield {}
        yield "not a dict"

    @property
    def reads(self) -> list[str]:
        return []

    @property
    def writes(self) -> list[str]:
        return []

    def update(self, result: dict, state: State) -> State:
        return state


class StreamingActionIncorrectResultTypeAsync(AsyncStreamingAction):
    async def stream_run(self, state: State, **run_kwargs) -> AsyncGenerator[dict, None]:
        yield {}
        yield "not a dict"

    @property
    def reads(self) -> list[str]:
        return []

    @property
    def writes(self) -> list[str]:
        return []

    def update(self, result: dict, state: State) -> State:
        return state


class StreamingSingleStepActionIncorrectResultType(SingleStepStreamingAction):
    def stream_run_and_update(
        self, state: State, **run_kwargs
    ) -> Generator[Tuple[dict, Optional[State]], None, None]:
        yield {}, State
        yield "not a dict", state

    @property
    def reads(self) -> list[str]:
        return []

    @property
    def writes(self) -> list[str]:
        return []


class StreamingSingleStepActionIncorrectResultTypeAsync(SingleStepStreamingAction):
    async def stream_run_and_update(
        self, state: State, **run_kwargs
    ) -> typing.AsyncGenerator[Tuple[dict, Optional[State]], None]:
        yield {}, None
        yield "not a dict", state

    @property
    def reads(self) -> list[str]:
        return []

    @property
    def writes(self) -> list[str]:
        return []


base_single_step_counter = SingleStepCounter()
base_single_step_counter_async = SingleStepCounterAsync()
base_single_step_counter_with_inputs = SingleStepCounterWithInputs()
base_single_step_counter_with_inputs_async = SingleStepCounterWithInputsAsync()

base_streaming_counter = StreamingCounter()
base_streaming_single_step_counter = SingleStepStreamingCounter()

base_streaming_counter_async = AsyncStreamingCounter()
base_streaming_single_step_counter_async = SingleStepStreamingCounterAsync()

base_single_step_action_incorrect_result_type = SingleStepActionIncorrectResultType()
base_single_step_action_incorrect_result_type_async = SingleStepActionIncorrectResultTypeAsync()


def test__run_single_step_action():
    action = base_single_step_counter.with_name("counter")
    state = State({"count": 0, "tracker": []})
    result, state = _run_single_step_action(action, state, inputs={})
    assert result == {"count": 1}
    assert state.subset("count", "tracker").get_all() == {"count": 1, "tracker": [1]}
    result, state = _run_single_step_action(action, state, inputs={})
    assert result == {"count": 2}
    assert state.subset("count", "tracker").get_all() == {"count": 2, "tracker": [1, 2]}


def test__run_single_step_action_incorrect_result_type():
    action = base_single_step_action_incorrect_result_type.with_name("counter")
    state = State({"count": 0, "tracker": []})
    with pytest.raises(ValueError, match="returned a non-dict"):
        _run_single_step_action(action, state, inputs={})


async def test__arun_single_step_action_incorrect_result_type():
    action = base_single_step_action_incorrect_result_type_async.with_name("counter")
    state = State({"count": 0, "tracker": []})
    with pytest.raises(ValueError, match="returned a non-dict"):
        await _arun_single_step_action(action, state, inputs={})


def test__run_single_step_action_with_inputs():
    action = base_single_step_counter_with_inputs.with_name("counter")
    state = State({"count": 0, "tracker": []})
    result, state = _run_single_step_action(action, state, inputs={"additional_increment": 1})
    assert result == {"count": 2}
    assert state.subset("count", "tracker").get_all() == {"count": 2, "tracker": [2]}
    result, state = _run_single_step_action(action, state, inputs={"additional_increment": 1})
    assert result == {"count": 4}
    assert state.subset("count", "tracker").get_all() == {"count": 4, "tracker": [2, 4]}


async def test__arun_single_step_action():
    action = base_single_step_counter_async.with_name("counter")
    state = State({"count": 0, "tracker": []})
    result, state = await _arun_single_step_action(action, state, inputs={})
    assert result == {"count": 1}
    assert state.subset("count", "tracker").get_all() == {"count": 1, "tracker": [1]}
    result, state = await _arun_single_step_action(action, state, inputs={})
    assert result == {"count": 2}
    assert state.subset("count", "tracker").get_all() == {"count": 2, "tracker": [1, 2]}


async def test__arun_single_step_action_with_inputs():
    action = base_single_step_counter_with_inputs_async.with_name("counter")
    state = State({"count": 0, "tracker": []})
    result, state = await _arun_single_step_action(
        action, state, inputs={"additional_increment": 1}
    )
    assert result == {"count": 2}
    assert state.subset("count", "tracker").get_all() == {"count": 2, "tracker": [2]}
    result, state = await _arun_single_step_action(
        action, state, inputs={"additional_increment": 1}
    )
    assert result == {"count": 4}
    assert state.subset("count", "tracker").get_all() == {"count": 4, "tracker": [2, 4]}


class SingleStepActionWithDeletion(SingleStepAction):
    def run_and_update(self, state: State, **run_kwargs) -> Tuple[dict, State]:
        return {}, state.wipe(delete=["to_delete"])

    @property
    def reads(self) -> list[str]:
        return []

    @property
    def writes(self) -> list[str]:
        return []


def test__run_single_step_action_deletes_state():
    action = SingleStepActionWithDeletion()
    state = State({"to_delete": 0})
    result, state = _run_single_step_action(action, state, inputs={})
    assert "to_delete" not in state


def test__run_multistep_streaming_action():
    action = base_streaming_counter.with_name("counter")
    state = State({"count": 0, "tracker": []})
    generator = _run_multi_step_streaming_action(
        action, state, inputs={}, sequence_id=0, partition_key="partition_key", app_id="app_id"
    )
    last_result = -1
    result = None
    for result, state in generator:
        if last_result < 1:
            # Otherwise you hit floating poit comparison problems
            assert result["count"] > last_result
        last_result = result["count"]
    assert result == {"count": 1}
    assert state.subset("count", "tracker").get_all() == {"count": 1, "tracker": [1]}


def test__run_multistep_streaming_action_callbacks():
    class TrackingCallback(PostStreamItemHook):
        def __init__(self):
            self.items = []

        def post_stream_item(self, item: Any, **future_kwargs: Any):
            self.items.append(item)

    hook = TrackingCallback()

    action = base_streaming_counter.with_name("counter")
    state = State({"count": 0, "tracker": []})
    generator = _run_multi_step_streaming_action(
        action,
        state,
        inputs={},
        sequence_id=0,
        partition_key="partition_key",
        app_id="app_id",
        lifecycle_adapters=LifecycleAdapterSet(hook),
    )
    last_result = -1
    result = None
    for result, state in generator:
        if last_result < 1:
            # Otherwise you hit floating poit comparison problems
            assert result["count"] > last_result
        last_result = result["count"]
    assert result == {"count": 1}
    assert state.subset("count", "tracker").get_all() == {"count": 1, "tracker": [1]}
    assert len(hook.items) == 10  # one for each streaming callback


async def test__run_multistep_streaming_action_async():
    action = base_streaming_counter_async.with_name("counter")
    state = State({"count": 0, "tracker": []})
    generator = _arun_multi_step_streaming_action(
        action=action,
        state=state,
        inputs={},
        sequence_id=0,
        app_id="app_id",
        partition_key="partition_key",
        lifecycle_adapters=LifecycleAdapterSet(),
    )
    last_result = -1
    result = None
    async for result, state in generator:
        if last_result < 1:
            # Otherwise you hit floating poit comparison problems
            assert result["count"] > last_result
        last_result = result["count"]
    assert result == {"count": 1}
    assert state.subset("count", "tracker").get_all() == {"count": 1, "tracker": [1]}


async def test__run_multistep_streaming_action_async_callbacks():
    class TrackingCallback(PostStreamItemHookAsync):
        def __init__(self):
            self.items = []

        async def post_stream_item(self, item: Any, **future_kwargs: Any):
            self.items.append(item)

    hook = TrackingCallback()
    action = base_streaming_counter_async.with_name("counter")
    state = State({"count": 0, "tracker": []})
    generator = _arun_multi_step_streaming_action(
        action=action,
        state=state,
        inputs={},
        sequence_id=0,
        app_id="app_id",
        partition_key="partition_key",
        lifecycle_adapters=LifecycleAdapterSet(hook),
    )
    last_result = -1
    result = None
    async for result, state in generator:
        if last_result < 1:
            # Otherwise you hit floating poit comparison problems
            assert result["count"] > last_result
        last_result = result["count"]
    assert result == {"count": 1}
    assert state.subset("count", "tracker").get_all() == {"count": 1, "tracker": [1]}
    assert len(hook.items) == 10  # one for each streaming callback


def test__run_streaming_action_incorrect_result_type():
    action = StreamingActionIncorrectResultType()
    state = State()
    with pytest.raises(ValueError, match="returned a non-dict"):
        gen = _run_multi_step_streaming_action(
            action, state, inputs={}, sequence_id=0, partition_key="partition_key", app_id="app_id"
        )
        collections.deque(gen, maxlen=0)  # exhaust the generator


async def test__run_streaming_action_incorrect_result_type_async():
    action = StreamingActionIncorrectResultTypeAsync()
    state = State()
    with pytest.raises(ValueError, match="returned a non-dict"):
        gen = _arun_multi_step_streaming_action(
            action=action,
            state=state,
            inputs={},
            sequence_id=0,
            app_id="app_id",
            partition_key="partition_key",
            lifecycle_adapters=LifecycleAdapterSet(),
        )
        async for _ in gen:
            pass


def test__run_single_step_streaming_action_incorrect_result_type():
    action = StreamingSingleStepActionIncorrectResultType()
    state = State()
    with pytest.raises(ValueError, match="returned a non-dict"):
        gen = _run_single_step_streaming_action(
            action=action,
            state=state,
            inputs={},
            sequence_id=0,
            partition_key="partition_key",
            app_id="app_id",
        )
        collections.deque(gen, maxlen=0)  # exhaust the generator


async def test__run_single_step_streaming_action_incorrect_result_type_async():
    action = StreamingSingleStepActionIncorrectResultTypeAsync()
    state = State()
    with pytest.raises(ValueError, match="returned a non-dict"):
        gen = _arun_single_step_streaming_action(
            action,
            state,
            inputs={},
            sequence_id=0,
            partition_key="partition_key",
            app_id="app_id",
            lifecycle_adapters=LifecycleAdapterSet(),
        )
        _ = [item async for item in gen]


def test__run_single_step_streaming_action():
    action = base_streaming_single_step_counter.with_name("counter")
    state = State({"count": 0, "tracker": []})
    generator = _run_single_step_streaming_action(
        action, state, inputs={}, sequence_id=0, partition_key="partition_key", app_id="app_id"
    )
    last_result = -1
    result, state = None, None
    for result, state in generator:
        if last_result < 1:
            # Otherwise you hit comparison issues
            # This is because we get to the last one, which is the final result
            assert result["count"] > last_result
        last_result = result["count"]
    assert result == {"count": 1}
    assert state.subset("count", "tracker").get_all() == {"count": 1, "tracker": [1]}


def test__run_single_step_streaming_action_calls_callbacks():
    action = base_streaming_single_step_counter.with_name("counter")

    class TrackingCallback(PostStreamItemHook):
        def __init__(self):
            self.items = []

        def post_stream_item(self, item: Any, **future_kwargs: Any):
            self.items.append(item)

    hook = TrackingCallback()

    state = State({"count": 0, "tracker": []})
    generator = _run_single_step_streaming_action(
        action,
        state,
        inputs={},
        sequence_id=0,
        partition_key="partition_key",
        app_id="app_id",
        lifecycle_adapters=LifecycleAdapterSet(hook),
    )
    last_result = -1
    result, state = None, None
    for result, state in generator:
        if last_result < 1:
            # Otherwise you hit comparison issues
            # This is because we get to the last one, which is the final result
            assert result["count"] > last_result
        last_result = result["count"]
    assert result == {"count": 1}
    assert state.subset("count", "tracker").get_all() == {"count": 1, "tracker": [1]}
    assert len(hook.items) == 10  # one for each streaming callback


async def test__run_single_step_streaming_action_async():
    async_action = base_streaming_single_step_counter_async.with_name("counter")
    state = State({"count": 0, "tracker": []})
    generator = _arun_single_step_streaming_action(
        action=async_action,
        state=state,
        inputs={},
        sequence_id=0,
        app_id="app_id",
        partition_key="partition_key",
        lifecycle_adapters=LifecycleAdapterSet(),
    )
    last_result = -1
    result, state = None, None
    async for result, state in generator:
        if last_result < 1:
            # Otherwise you hit comparison issues
            # This is because we get to the last one, which is the final result
            assert result["count"] > last_result
        last_result = result["count"]
    assert result == {"count": 1}
    assert state.subset("count", "tracker").get_all() == {"count": 1, "tracker": [1]}


async def test__run_single_step_streaming_action_async_callbacks():
    class TrackingCallback(PostStreamItemHookAsync):
        def __init__(self):
            self.items = []

        async def post_stream_item(self, item: Any, **future_kwargs: Any):
            self.items.append(item)

    hook = TrackingCallback()

    async_action = base_streaming_single_step_counter_async.with_name("counter")
    state = State({"count": 0, "tracker": []})
    generator = _arun_single_step_streaming_action(
        action=async_action,
        state=state,
        inputs={},
        sequence_id=0,
        app_id="app_id",
        partition_key="partition_key",
        lifecycle_adapters=LifecycleAdapterSet(hook),
    )
    last_result = -1
    result, state = None, None
    async for result, state in generator:
        if last_result < 1:
            # Otherwise you hit comparison issues
            # This is because we get to the last one, which is the final result
            assert result["count"] > last_result
        last_result = result["count"]
    assert result == {"count": 1}
    assert state.subset("count", "tracker").get_all() == {"count": 1, "tracker": [1]}
    assert len(hook.items) == 10  # one for each streaming callback


class SingleStepActionWithDeletionAsync(SingleStepActionWithDeletion):
    async def run_and_update(self, state: State, **run_kwargs) -> Tuple[dict, State]:
        return {}, state.wipe(delete=["to_delete"])


async def test__arun_single_step_action_deletes_state():
    action = SingleStepActionWithDeletionAsync()
    state = State({"to_delete": 0})
    result, state = await _arun_single_step_action(action, state, inputs={})
    assert "to_delete" not in state


def test_app_step():
    """Tests that we can run a step in an app"""
    counter_action = base_counter_action.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[Transition(counter_action, counter_action, default)],
        ),
    )
    action, result, state = app.step()
    assert app.sequence_id == 1
    assert action.name == "counter"
    assert result == {"count": 1}
    assert state[PRIOR_STEP] == "counter"  # internal contract, not part of the public API


def test_app_step_with_inputs():
    """Tests that we can run a step in an app"""
    counter_action = base_single_step_counter_with_inputs.with_name("counter")
    app = Application(
        state=State({"count": 0, "tracker": []}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[Transition(counter_action, counter_action, default)],
        ),
    )
    action, result, state = app.step(inputs={"additional_increment": 1})
    assert action.name == "counter"
    assert result == {"count": 2}
    assert state.subset("count", "tracker").get_all() == {"count": 2, "tracker": [2]}


def test_app_step_with_inputs_missing():
    """Tests that we can run a step in an app"""
    counter_action = base_single_step_counter_with_inputs.with_name("counter")
    app = Application(
        state=State({"count": 0, "tracker": []}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[Transition(counter_action, counter_action, default)],
        ),
    )
    with pytest.raises(ValueError, match="missing required inputs"):
        app.step(inputs={})


def test_app_step_broken(caplog):
    """Tests that we can run a step in an app"""
    broken_action = base_broken_action.with_name("broken_action_unique_name")
    app = Application(
        state=State({}),
        entrypoint="broken_action_unique_name",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[broken_action],
            transitions=[Transition(broken_action, broken_action, default)],
        ),
    )
    with caplog.at_level(logging.ERROR):  # it should say the name, that's the only contract for now
        with pytest.raises(BrokenStepException):
            app.step()
    assert "broken_action_unique_name" in caplog.text


def test_app_step_done():
    """Tests that when we cannot run a step, we return None"""
    counter_action = base_counter_action.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[],
        ),
    )
    app.step()
    assert app.step() is None


async def test_app_astep():
    """Tests that we can run an async step in an app"""
    counter_action = base_counter_action_async.with_name("counter_async")
    app = Application(
        state=State({}),
        entrypoint="counter_async",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[Transition(counter_action, counter_action, default)],
        ),
    )
    action, result, state = await app.astep()
    assert app.sequence_id == 1
    assert action.name == "counter_async"
    assert result == {"count": 1}
    assert state[PRIOR_STEP] == "counter_async"  # internal contract, not part of the public API


def test_app_step_context():
    APP_ID = str(uuid.uuid4())
    PARTITION_KEY = str(uuid.uuid4())

    @action(reads=[], writes=[])
    def test_action(state: State, __context: ApplicationContext) -> State:
        assert __context.sequence_id == 0
        assert __context.partition_key == PARTITION_KEY
        assert __context.app_id == APP_ID
        assert __context.action_name == "test_action"
        return state

    app = (
        ApplicationBuilder()
        .with_actions(test_action)
        .with_entrypoint("test_action")
        .with_transitions()
        .with_identifiers(
            app_id=APP_ID,
            partition_key=PARTITION_KEY,
        )
        .build()
    )
    app.step()


async def test_app_astep_context():
    """Tests that app.astep correctly passes context."""
    APP_ID = str(uuid.uuid4())
    PARTITION_KEY = str(uuid.uuid4())

    @action(reads=[], writes=[])
    def test_action(state: State, __context: ApplicationContext) -> State:
        assert __context.sequence_id == 0
        assert __context.partition_key == PARTITION_KEY
        assert __context.app_id == APP_ID
        assert __context.action_name == "test_action"
        return state

    app = (
        ApplicationBuilder()
        .with_actions(test_action)
        .with_entrypoint("test_action")
        .with_transitions()
        .with_identifiers(
            app_id=APP_ID,
            partition_key=PARTITION_KEY,
        )
        .build()
    )
    await app.astep()


async def test_app_astep_with_inputs():
    """Tests that we can run an async step in an app"""
    counter_action = base_single_step_counter_with_inputs_async.with_name("counter_async")
    app = Application(
        state=State({"count": 0, "tracker": []}),
        entrypoint="counter_async",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[Transition(counter_action, counter_action, default)],
        ),
    )
    action, result, state = await app.astep(inputs={"additional_increment": 1})
    assert action.name == "counter_async"
    assert result == {"count": 2}
    assert state.subset("count", "tracker").get_all() == {"count": 2, "tracker": [2]}


async def test_app_astep_with_inputs_missing():
    """Tests that we can run an async step in an app"""
    counter_action = base_single_step_counter_with_inputs_async.with_name("counter_async")
    app = Application(
        state=State({"count": 0, "tracker": []}),
        entrypoint="counter_async",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[Transition(counter_action, counter_action, default)],
        ),
    )
    with pytest.raises(ValueError, match="missing required inputs"):
        await app.astep(inputs={})


async def test_app_astep_broken(caplog):
    """Tests that we can run a step in an app"""
    broken_action = base_broken_action_async.with_name("broken_action_unique_name")
    app = Application(
        state=State({}),
        entrypoint="broken_action_unique_name",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[broken_action],
            transitions=[Transition(broken_action, broken_action, default)],
        ),
    )
    with caplog.at_level(logging.ERROR):  # it should say the name, that's the only contract for now
        with pytest.raises(BrokenStepException):
            await app.astep()
    assert "broken_action_unique_name" in caplog.text


async def test_app_astep_done():
    """Tests that when we cannot run a step, we return None"""
    counter_action = base_counter_action_async.with_name("counter_async")
    app = Application(
        state=State({}),
        entrypoint="counter_async",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[],
        ),
    )
    await app.astep()
    assert await app.astep() is None


# internal API
def test_app_many_steps():
    counter_action = base_counter_action.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[Transition(counter_action, counter_action, default)],
        ),
    )
    action, result = None, None
    for i in range(100):
        action, result, state = app.step()
    assert action.name == "counter"
    assert result == {"count": 100}


async def test_app_many_a_steps():
    counter_action = base_counter_action_async.with_name("counter_async")
    app = Application(
        state=State({}),
        entrypoint="counter_async",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[Transition(counter_action, counter_action, default)],
        ),
    )
    action, result = None, None
    for i in range(100):
        action, result, state = await app.astep()
    assert action.name == "counter_async"
    assert result == {"count": 100}


def test_iterate():
    result_action = Result("count").with_name("result")
    counter_action = base_counter_action.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, counter_action, Condition.expr("count < 10")),
                Transition(counter_action, result_action, default),
            ],
        ),
    )
    res = []
    gen = app.iterate(halt_after=["result"])
    counter = 0
    try:
        while True:
            action, result, state = next(gen)
            if action.name == "counter":
                assert state["count"] == counter + 1
                assert result["count"] == state["count"]
                counter = result["count"]
            else:
                res.append(result)
                assert state["count"] == 10
                assert result["count"] == 10
    except StopIteration as e:
        stop_iteration_error = e
    generator_result = stop_iteration_error.value
    action, result, state = generator_result
    assert state["count"] == 10
    assert result["count"] == 10
    assert app.sequence_id == 11


def test_iterate_with_inputs():
    result_action = Result("count").with_name("result")
    counter_action = base_counter_action_with_inputs.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, counter_action, Condition.expr("count < 2")),
                Transition(counter_action, result_action, default),
            ],
        ),
    )
    gen = app.iterate(
        halt_after=["result"], inputs={"additional_increment": 10}
    )  # make it go quicly to the end
    while True:
        try:
            action, result, state = next(gen)
        except StopIteration as e:
            a, r, s = e.value
            assert r["count"] == 11  # 1 + 10, for the first one
            break


async def test_aiterate():
    result_action = Result("count").with_name("result")
    counter_action = base_counter_action_async.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, counter_action, Condition.expr("count < 10")),
                Transition(counter_action, result_action, default),
            ],
        ),
    )
    gen = app.aiterate(halt_after=["result"])
    assert app.sequence_id == 0
    counter = 0
    # Note that we use an async-for loop cause the API is different, this doesn't
    # return anything (async generators are not allowed to).
    async for action_, result, state in gen:
        print("si", app.sequence_id, action_.name, state)
        if action_.name == "counter":
            assert state["count"] == result["count"] == counter + 1
            counter = result["count"]
        else:
            assert state["count"] == result["count"] == 10
    assert app.sequence_id == 11


async def test_aiterate_halt_before():
    result_action = Result("count").with_name("result")
    counter_action = base_counter_action_async.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, counter_action, Condition.expr("count < 10")),
                Transition(counter_action, result_action, default),
            ],
        ),
    )
    gen = app.aiterate(halt_before=["result"])
    counter = 0
    # Note that we use an async-for loop cause the API is different, this doesn't
    # return anything (async generators are not allowed to).
    async for action_, result, state in gen:
        if action_.name == "counter":
            assert state["count"] == counter + 1
            counter = result["count"]
        else:
            assert result is None
            assert state["count"] == 10


async def test_app_aiterate_with_inputs():
    result_action = Result("count").with_name("result")
    counter_action = base_counter_action_with_inputs_async.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, counter_action, Condition.expr("count < 10")),
                Transition(counter_action, result_action, default),
            ],
        ),
    )
    gen = app.aiterate(halt_after=["result"], inputs={"additional_increment": 10})
    async for action_, result, state in gen:
        if action_.name == "counter":
            assert result["count"] == state["count"] == 11
        else:
            assert state["count"] == result["count"] == 11


def test_run():
    result_action = Result("count").with_name("result")
    counter_action = base_counter_action.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, counter_action, Condition.expr("count < 10")),
                Transition(counter_action, result_action, default),
            ],
        ),
    )
    action, result, state = app.run(halt_after=["result"])
    assert state["count"] == 10
    assert result["count"] == 10


def test_run_halt_before():
    result_action = Result("count").with_name("result")
    counter_action = base_counter_action.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, counter_action, Condition.expr("count < 10")),
                Transition(counter_action, result_action, default),
            ],
        ),
    )
    action, result, state = app.run(halt_before=["result"])
    assert state["count"] == 10
    assert result is None
    assert action.name == "result"


def test_run_with_inputs():
    result_action = Result("count").with_name("result")
    counter_action = base_counter_action_with_inputs.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, counter_action, Condition.expr("count < 10")),
                Transition(counter_action, result_action, default),
            ],
        ),
    )
    action_, result, state = app.run(halt_after=["result"], inputs={"additional_increment": 10})
    assert action_.name == "result"
    assert state["count"] == result["count"] == 11


def test_run_with_inputs_multiple_actions():
    """Tests that inputs aren't popped off and are passed through to multiple actions."""
    result_action = Result("count").with_name("result")
    counter_action1 = base_counter_action_with_inputs.with_name("counter1")
    counter_action2 = base_counter_action_with_inputs.with_name("counter2")
    app = Application(
        state=State({}),
        entrypoint="counter1",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action1, counter_action2, result_action],
            transitions=[
                Transition(counter_action1, counter_action1, Condition.expr("count < 10")),
                Transition(counter_action1, counter_action2, Condition.expr("count >= 10")),
                Transition(counter_action2, counter_action2, Condition.expr("count < 20")),
                Transition(counter_action2, result_action, default),
            ],
        ),
    )
    action_, result, state = app.run(halt_after=["result"], inputs={"additional_increment": 8})
    assert action_.name == "result"
    assert state["count"] == result["count"] == 27
    assert state["__SEQUENCE_ID"] == 4


async def test_arun():
    result_action = Result("count").with_name("result")
    counter_action = base_counter_action_async.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, counter_action, Condition.expr("count < 10")),
                Transition(counter_action, result_action, default),
            ],
        ),
    )
    action_, result, state = await app.arun(halt_after=["result"])
    assert state["count"] == result["count"] == 10
    assert action_.name == "result"


async def test_arun_halt_before():
    result_action = Result("count").with_name("result")
    counter_action = base_counter_action_async.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, counter_action, Condition.expr("count < 10")),
                Transition(counter_action, result_action, default),
            ],
        ),
    )
    action_, result, state = await app.arun(halt_before=["result"])
    assert state["count"] == 10
    assert result is None
    assert action_.name == "result"


async def test_arun_with_inputs():
    result_action = Result("count").with_name("result")
    counter_action = base_counter_action_with_inputs_async.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, counter_action, Condition.expr("count < 10")),
                Transition(counter_action, result_action, default),
            ],
        ),
    )
    action_, result, state = await app.arun(
        halt_after=["result"], inputs={"additional_increment": 10}
    )
    assert state["count"] == result["count"] == 11
    assert action_.name == "result"


async def test_arun_with_inputs_multiple_actions():
    result_action = Result("count").with_name("result")
    counter_action1 = base_counter_action_with_inputs_async.with_name("counter1")
    counter_action2 = base_counter_action_with_inputs_async.with_name("counter2")
    app = Application(
        state=State({}),
        entrypoint="counter1",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action1, counter_action2, result_action],
            transitions=[
                Transition(counter_action1, counter_action1, Condition.expr("count < 10")),
                Transition(counter_action1, counter_action2, Condition.expr("count >= 10")),
                Transition(counter_action2, counter_action2, Condition.expr("count < 20")),
                Transition(counter_action2, result_action, default),
            ],
        ),
    )
    action_, result, state = await app.arun(
        halt_after=["result"], inputs={"additional_increment": 8}
    )
    assert state["count"] == result["count"] == 27
    assert action_.name == "result"
    assert state["__SEQUENCE_ID"] == 4


async def test_app_a_run_async_and_sync():
    result_action = Result("count").with_name("result")
    counter_action_sync = base_counter_action_async.with_name("counter_sync")
    counter_action_async = base_counter_action_async.with_name("counter_async")
    app = Application(
        state=State({}),
        entrypoint="counter_sync",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action_sync, counter_action_async, result_action],
            transitions=[
                Transition(counter_action_sync, counter_action_async, Condition.expr("count < 20")),
                Transition(counter_action_async, counter_action_sync, default),
                Transition(counter_action_sync, result_action, default),
            ],
        ),
    )
    action_, result, state = await app.arun(halt_after=["result"])
    assert state["count"] > 20
    assert result["count"] > 20


def test_stream_result_halt_after_unique_ordered_sequence_id():
    action_tracker = CallCaptureTracker()
    stream_event_tracker = StreamEventCaptureTracker()
    counter_action = base_streaming_counter.with_name("counter")
    counter_action_2 = base_streaming_counter.with_name("counter_2")
    app = Application(
        state=State({"count": 0}),
        entrypoint="counter",
        adapter_set=LifecycleAdapterSet(action_tracker, stream_event_tracker),
        partition_key="test",
        uid="test-123",
        graph=Graph(
            actions=[counter_action, counter_action_2],
            transitions=[
                Transition(counter_action, counter_action_2, default),
            ],
        ),
    )
    action_, streaming_container = app.stream_result(halt_after=["counter_2"])
    results = list(streaming_container)
    assert len(results) == 10
    result, state = streaming_container.get()
    assert result["count"] == state["count"] == 2
    assert state["tracker"] == [1, 2]
    assert len(action_tracker.pre_called) == 2
    assert len(action_tracker.post_called) == 2
    assert set(dict(action_tracker.pre_called).keys()) == {"counter", "counter_2"}
    assert set(dict(action_tracker.post_called).keys()) == {"counter", "counter_2"}
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected
    # One post call/one pre-call, as we call stream_result once
    assert len(action_tracker.post_run_execute_calls) == 1
    assert len(action_tracker.pre_run_execute_calls) == 1
    # One call for streaming
    assert len(stream_event_tracker.pre_start_stream_calls) == 1
    # 10 streaming items
    assert len(stream_event_tracker.post_stream_item_calls) == 10
    # One call for streaming
    assert len(stream_event_tracker.post_end_stream_calls) == 1


async def test_astream_result_halt_after_unique_ordered_sequence_id():
    action_tracker = CallCaptureTracker()
    stream_event_tracker = StreamEventCaptureTrackerAsync()
    stream_event_tracker_sync = StreamEventCaptureTracker()
    counter_action = base_streaming_counter_async.with_name("counter")
    counter_action_2 = base_streaming_counter_async.with_name("counter_2")
    app = Application(
        state=State({"count": 0}),
        entrypoint="counter",
        adapter_set=LifecycleAdapterSet(
            action_tracker, stream_event_tracker, stream_event_tracker_sync
        ),
        partition_key="test",
        uid="test-123",
        graph=Graph(
            actions=[counter_action, counter_action_2],
            transitions=[
                Transition(counter_action, counter_action_2, default),
            ],
        ),
    )
    action_, streaming_async_container = await app.astream_result(halt_after=["counter_2"])
    results = [
        item async for item in streaming_async_container
    ]  # this should just have the intermediate results
    # results = list(streaming_container)
    assert len(results) == 10
    result, state = await streaming_async_container.get()
    assert result["count"] == state["count"] == 2
    assert state["tracker"] == [1, 2]
    assert len(action_tracker.pre_called) == 2
    assert len(action_tracker.post_called) == 2
    assert set(dict(action_tracker.pre_called).keys()) == {"counter", "counter_2"}
    assert set(dict(action_tracker.post_called).keys()) == {"counter", "counter_2"}
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected
    assert len(action_tracker.post_run_execute_calls) == 1
    assert len(action_tracker.pre_run_execute_calls) == 1

    # One call for streaming
    assert (
        len(stream_event_tracker.pre_start_stream_calls)
        == len(stream_event_tracker_sync.pre_start_stream_calls)
        == 1
    )
    # 10 streaming items
    assert (
        len(stream_event_tracker.post_stream_item_calls)
        == len(stream_event_tracker_sync.post_stream_item_calls)
        == 10
    )
    # One call for streaming
    assert (
        len(stream_event_tracker.post_end_stream_calls)
        == len(stream_event_tracker_sync.post_end_stream_calls)
        == 1
    )


def test_stream_result_halt_after_run_through_streaming():
    """Tests that we can pass through streaming results,
    fully realize them, then get to the streaming results at the end and return the stream"""
    action_tracker = CallCaptureTracker()
    stream_event_tracker = StreamEventCaptureTracker()
    counter_action = base_streaming_single_step_counter.with_name("counter")
    counter_action_2 = base_streaming_single_step_counter.with_name("counter_2")
    app = Application(
        state=State({"count": 0}),
        entrypoint="counter",
        adapter_set=LifecycleAdapterSet(action_tracker, stream_event_tracker),
        partition_key="test",
        uid="test-123",
        graph=Graph(
            actions=[counter_action, counter_action_2],
            transitions=[
                Transition(counter_action, counter_action_2, default),
            ],
        ),
    )
    action_, streaming_container = app.stream_result(halt_after=["counter_2"])
    results = list(streaming_container)
    assert len(results) == 10
    result, state = streaming_container.get()
    assert result["count"] == state["count"] == 2
    assert state["tracker"] == [1, 2]
    assert len(action_tracker.pre_called) == 2
    assert len(action_tracker.post_called) == 2
    assert set(dict(action_tracker.pre_called).keys()) == {"counter", "counter_2"}
    assert set(dict(action_tracker.post_called).keys()) == {"counter", "counter_2"}
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected
    assert len(action_tracker.post_run_execute_calls) == 1
    assert len(action_tracker.pre_run_execute_calls) == 1
    # One call for streaming
    assert len(stream_event_tracker.pre_start_stream_calls) == 1
    # 10 streaming items
    assert len(stream_event_tracker.post_stream_item_calls) == 10
    # One call for streaming
    assert len(stream_event_tracker.post_end_stream_calls) == 1


@pytest.mark.parametrize("exhaust_intermediate_generators", [True, False])
def test_stream_iterate(exhaust_intermediate_generators: bool):
    """Tests that we can pass through streaming results in streaming iterate. Note that this tests two cases:
    1. We exhaust the intermediate generators, and then call get() to get the final result
    2. We don't exhaust the intermediate generators, and then call get() to get the final result
    This ensures that the application effectively does it for us.
    """
    action_tracker = CallCaptureTracker()
    stream_event_tracker = StreamEventCaptureTracker()
    counter_action = base_streaming_single_step_counter.with_name("counter")
    counter_action_2 = base_streaming_single_step_counter.with_name("counter_2")
    app = Application(
        state=State({"count": 0}),
        entrypoint="counter",
        adapter_set=LifecycleAdapterSet(action_tracker, stream_event_tracker),
        partition_key="test",
        uid="test-123",
        graph=Graph(
            actions=[counter_action, counter_action_2],
            transitions=[
                Transition(counter_action, counter_action_2, default),
            ],
        ),
    )
    for _, streaming_container in app.stream_iterate(halt_after=["counter_2"]):
        if exhaust_intermediate_generators:
            results = list(streaming_container)
            assert len(results) == 10
    result, state = streaming_container.get()
    assert result["count"] == state["count"] == 2
    assert state["tracker"] == [1, 2]
    assert len(action_tracker.pre_called) == 2
    assert len(action_tracker.post_called) == 2
    assert set(dict(action_tracker.pre_called).keys()) == {"counter", "counter_2"}
    assert set(dict(action_tracker.post_called).keys()) == {"counter", "counter_2"}
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected

    assert len(stream_event_tracker.pre_start_stream_calls) == 2
    assert len(stream_event_tracker.post_end_stream_calls) == 2
    assert len(stream_event_tracker.post_stream_item_calls) == 20
    assert len(stream_event_tracker.post_stream_item_calls) == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("exhaust_intermediate_generators", [True, False])
async def test_astream_iterate(exhaust_intermediate_generators: bool):
    """Tests that we can pass through streaming results in astream_iterate. Note that this tests two cases:
    1. We exhaust the intermediate generators, and then call get() to get the final result
    2. We don't exhaust the intermediate generators, and then call get() to get the final result
    This ensures that the application effectively does it for us.
    """
    action_tracker = CallCaptureTracker()
    stream_event_tracker = StreamEventCaptureTracker()
    counter_action = base_streaming_single_step_counter_async.with_name(
        "counter"
    )  # Use async action
    counter_action_2 = base_streaming_single_step_counter_async.with_name(
        "counter_2"
    )  # Use async action
    app = Application(
        state=State({"count": 0}),
        entrypoint="counter",
        adapter_set=LifecycleAdapterSet(action_tracker, stream_event_tracker),
        partition_key="test",
        uid="test-123",
        graph=Graph(
            actions=[counter_action, counter_action_2],
            transitions=[
                Transition(counter_action, counter_action_2, default),
            ],
        ),
    )
    streaming_container = None  # Define outside the loop to access later
    async for _, streaming_container in app.astream_iterate(halt_after=["counter_2"]):
        if exhaust_intermediate_generators:
            results = []
            async for item in streaming_container:  # Use async for
                results.append(item)
            assert len(results) == 10
    assert streaming_container is not None  # Ensure the loop ran
    result, state = await streaming_container.get()  # Use await
    assert result["count"] == state["count"] == 2
    assert state["tracker"] == [1, 2]
    assert len(action_tracker.pre_called) == 2
    assert len(action_tracker.post_called) == 2
    assert set(dict(action_tracker.pre_called).keys()) == {"counter", "counter_2"}
    assert set(dict(action_tracker.post_called).keys()) == {"counter", "counter_2"}
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected

    assert len(stream_event_tracker.pre_start_stream_calls) == 2
    assert len(stream_event_tracker.post_end_stream_calls) == 2
    assert len(stream_event_tracker.post_stream_item_calls) == 20


async def test_astream_result_halt_after_run_through_streaming():
    action_tracker = CallCaptureTracker()
    stream_event_tracker = StreamEventCaptureTrackerAsync()
    sync_stream_event_tracker = StreamEventCaptureTracker()

    counter_action = base_streaming_single_step_counter_async.with_name("counter")
    counter_action_2 = base_streaming_single_step_counter_async.with_name("counter_2")
    assert counter_action.is_async()
    assert counter_action_2.is_async()
    app = Application(
        state=State({"count": 0}),
        entrypoint="counter",
        adapter_set=LifecycleAdapterSet(
            action_tracker, stream_event_tracker, sync_stream_event_tracker
        ),
        partition_key="test",
        uid="test-123",
        graph=Graph(
            actions=[counter_action, counter_action_2],
            transitions=[
                Transition(counter_action, counter_action_2, default),
            ],
        ),
    )
    action_, streaming_container = await app.astream_result(halt_after=["counter_2"])
    results = [
        item async for item in streaming_container
    ]  # this should just have the intermediate results
    assert len(results) == 10
    result, state = await streaming_container.get()
    assert result["count"] == state["count"] == 2
    assert state["tracker"] == [1, 2]
    assert len(action_tracker.pre_called) == 2
    assert len(action_tracker.post_called) == 2
    assert set(dict(action_tracker.pre_called).keys()) == {"counter", "counter_2"}
    assert set(dict(action_tracker.post_called).keys()) == {"counter", "counter_2"}
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == [
        0,
        1,
    ]  # ensure sequence ID is respected
    assert len(action_tracker.post_run_execute_calls) == 1
    assert len(action_tracker.pre_run_execute_calls) == 1

    # One call for streaming
    assert (
        len(stream_event_tracker.pre_start_stream_calls)
        == len(sync_stream_event_tracker.pre_start_stream_calls)
        == 1
    )
    # 10 streaming items
    assert (
        len(stream_event_tracker.post_stream_item_calls)
        == len(sync_stream_event_tracker.post_stream_item_calls)
        == 10
    )
    # One call for streaming
    assert (
        len(stream_event_tracker.post_end_stream_calls)
        == len(sync_stream_event_tracker.post_end_stream_calls)
        == 1
    )


def test_stream_result_halt_after_run_through_non_streaming():
    """Tests what happens when we have an app that runs through non-streaming
    results before hitting a final streaming result specified by halt_after"""
    action_tracker = CallCaptureTracker()
    stream_event_tracker = StreamEventCaptureTracker()
    counter_non_streaming = base_counter_action.with_name("counter_non_streaming")
    counter_streaming = base_streaming_single_step_counter.with_name("counter_streaming")

    app = Application(
        state=State({"count": 0}),
        entrypoint="counter_non_streaming",
        adapter_set=LifecycleAdapterSet(action_tracker, stream_event_tracker),
        partition_key="test",
        uid="test-123",
        graph=Graph(
            actions=[counter_non_streaming, counter_streaming],
            transitions=[
                Transition(counter_non_streaming, counter_non_streaming, expr("count < 10")),
                Transition(counter_non_streaming, counter_streaming, default),
            ],
        ),
    )
    action_, streaming_container = app.stream_result(halt_after=["counter_streaming"])
    results = list(streaming_container)
    assert len(results) == 10
    result, state = streaming_container.get()
    assert result["count"] == state["count"] == 11
    assert len(action_tracker.pre_called) == 11
    assert len(action_tracker.post_called) == 11
    assert set(dict(action_tracker.pre_called).keys()) == {
        "counter_streaming",
        "counter_non_streaming",
    }
    assert set(dict(action_tracker.post_called).keys()) == {
        "counter_streaming",
        "counter_non_streaming",
    }
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == list(
        range(0, 11)
    )  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == list(
        range(0, 11)
    )  # ensure sequence ID is respected
    assert len(action_tracker.post_run_execute_calls) == 1
    assert len(action_tracker.pre_run_execute_calls) == 1

    # One call for streaming
    assert len(stream_event_tracker.pre_start_stream_calls) == 1
    # 10 streaming items
    assert len(stream_event_tracker.post_stream_item_calls) == 10
    # One call for streaming
    assert len(stream_event_tracker.post_end_stream_calls) == 1


async def test_astream_result_halt_after_run_through_non_streaming():
    action_tracker = CallCaptureTracker()
    stream_event_tracker = StreamEventCaptureTrackerAsync()
    stream_event_tracker_sync = StreamEventCaptureTracker()
    counter_non_streaming = base_counter_action_async.with_name("counter_non_streaming")
    counter_streaming = base_streaming_single_step_counter_async.with_name("counter_streaming")

    app = Application(
        state=State({"count": 0}),
        entrypoint="counter_non_streaming",
        adapter_set=LifecycleAdapterSet(
            action_tracker, stream_event_tracker, stream_event_tracker_sync
        ),
        partition_key="test",
        uid="test-123",
        graph=Graph(
            actions=[counter_non_streaming, counter_streaming],
            transitions=[
                Transition(counter_non_streaming, counter_non_streaming, expr("count < 10")),
                Transition(counter_non_streaming, counter_streaming, default),
            ],
        ),
    )
    action_, async_streaming_container = await app.astream_result(halt_after=["counter_streaming"])
    results = [
        item async for item in async_streaming_container
    ]  # this should just have the intermediate results
    assert len(results) == 10
    result, state = await async_streaming_container.get()
    assert result["count"] == state["count"] == 11
    assert len(action_tracker.pre_called) == 11
    assert len(action_tracker.post_called) == 11
    assert set(dict(action_tracker.pre_called).keys()) == {
        "counter_streaming",
        "counter_non_streaming",
    }
    assert set(dict(action_tracker.post_called).keys()) == {
        "counter_streaming",
        "counter_non_streaming",
    }
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == list(
        range(0, 11)
    )  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == list(
        range(0, 11)
    )  # ensure sequence ID is respected
    assert len(action_tracker.post_run_execute_calls) == 1
    assert len(action_tracker.pre_run_execute_calls) == 1

    # One call for streaming
    assert (
        len(stream_event_tracker.pre_start_stream_calls)
        == len(stream_event_tracker_sync.pre_start_stream_calls)
        == 1
    )
    # 10 streaming items
    assert (
        len(stream_event_tracker.post_stream_item_calls)
        == len(stream_event_tracker_sync.post_stream_item_calls)
        == 10
    )
    # One call for streaming
    assert (
        len(stream_event_tracker.post_end_stream_calls)
        == len(stream_event_tracker_sync.post_end_stream_calls)
        == 1
    )


def test_stream_result_halt_after_run_through_final_non_streaming():
    """Tests that we can pass through non-streaming results when streaming is called"""
    action_tracker = CallCaptureTracker()
    counter_non_streaming = base_counter_action.with_name("counter_non_streaming")
    counter_final_non_streaming = base_counter_action.with_name("counter_final_non_streaming")

    app = Application(
        state=State({"count": 0}),
        entrypoint="counter_non_streaming",
        adapter_set=LifecycleAdapterSet(action_tracker),
        partition_key="test",
        uid="test-123",
        graph=Graph(
            actions=[counter_non_streaming, counter_final_non_streaming],
            transitions=[
                Transition(counter_non_streaming, counter_non_streaming, expr("count < 10")),
                Transition(counter_non_streaming, counter_final_non_streaming, default),
            ],
        ),
    )
    action, streaming_container = app.stream_result(halt_after=["counter_final_non_streaming"])
    results = list(streaming_container)
    assert len(results) == 0  # nothing to steram
    result, state = streaming_container.get()
    assert result["count"] == state["count"] == 11
    assert len(action_tracker.pre_called) == 11
    assert len(action_tracker.post_called) == 11
    assert set(dict(action_tracker.pre_called).keys()) == {
        "counter_non_streaming",
        "counter_final_non_streaming",
    }
    assert set(dict(action_tracker.post_called).keys()) == {
        "counter_non_streaming",
        "counter_final_non_streaming",
    }
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == list(
        range(0, 11)
    )  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == list(
        range(0, 11)
    )  # ensure sequence ID is respected
    assert len(action_tracker.pre_run_execute_calls) == 1
    assert len(action_tracker.post_run_execute_calls) == 1


async def test_astream_result_halt_after_run_through_final_streaming():
    """Tests that we can pass through non-streaming results when streaming is called"""
    action_tracker = CallCaptureTracker()

    counter_non_streaming = base_counter_action_async.with_name("counter_non_streaming")
    counter_final_non_streaming = base_counter_action_async.with_name("counter_final_non_streaming")

    app = Application(
        state=State({"count": 0}),
        entrypoint="counter_non_streaming",
        adapter_set=LifecycleAdapterSet(action_tracker),
        partition_key="test",
        uid="test-123",
        graph=Graph(
            actions=[counter_non_streaming, counter_final_non_streaming],
            transitions=[
                Transition(counter_non_streaming, counter_non_streaming, expr("count < 10")),
                Transition(counter_non_streaming, counter_final_non_streaming, default),
            ],
        ),
    )
    action, streaming_container = await app.astream_result(
        halt_after=["counter_final_non_streaming"]
    )
    results = [
        item async for item in streaming_container
    ]  # this should just have the intermediate results
    assert len(results) == 0  # nothing to stream
    result, state = await streaming_container.get()
    assert result["count"] == state["count"] == 11
    assert len(action_tracker.pre_called) == 11
    assert len(action_tracker.post_called) == 11
    assert set(dict(action_tracker.pre_called).keys()) == {
        "counter_non_streaming",
        "counter_final_non_streaming",
    }
    assert set(dict(action_tracker.post_called).keys()) == {
        "counter_non_streaming",
        "counter_final_non_streaming",
    }
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == list(
        range(0, 11)
    )  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == list(
        range(0, 11)
    )  # ensure sequence ID is respected
    assert len(action_tracker.post_run_execute_calls) == 1
    assert len(action_tracker.pre_run_execute_calls) == 1


def test_stream_result_halt_before():
    action_tracker = CallCaptureTracker()
    counter_non_streaming = base_counter_action.with_name("counter_non_streaming")
    counter_streaming = base_streaming_single_step_counter.with_name("counter_final")

    app = Application(
        state=State({"count": 0}),
        entrypoint="counter_non_streaming",
        partition_key="test",
        uid="test-123",
        adapter_set=LifecycleAdapterSet(action_tracker),
        graph=Graph(
            actions=[counter_non_streaming, counter_streaming],
            transitions=[
                Transition(counter_non_streaming, counter_non_streaming, expr("count < 10")),
                Transition(counter_non_streaming, counter_streaming, default),
            ],
        ),
    )
    action, streaming_container = app.stream_result(halt_after=[], halt_before=["counter_final"])
    results = list(streaming_container)
    assert len(results) == 0  # nothing to steram
    result, state = streaming_container.get()
    assert action.name == "counter_final"  # halt before this one
    assert result is None
    assert state["count"] == 10
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == list(
        range(0, 10)
    )  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == list(
        range(0, 10)
    )  # ensure sequence ID is respected
    assert len(action_tracker.post_run_execute_calls) == 1
    assert len(action_tracker.pre_run_execute_calls) == 1


async def test_astream_result_halt_before():
    action_tracker = CallCaptureTracker()
    counter_non_streaming = base_counter_action_async.with_name("counter_non_streaming")
    counter_streaming = base_streaming_single_step_counter_async.with_name("counter_final")

    app = Application(
        state=State({"count": 0}),
        entrypoint="counter_non_streaming",
        partition_key="test",
        uid="test-123",
        adapter_set=LifecycleAdapterSet(action_tracker),
        graph=Graph(
            actions=[counter_non_streaming, counter_streaming],
            transitions=[
                Transition(counter_non_streaming, counter_non_streaming, expr("count < 10")),
                Transition(counter_non_streaming, counter_streaming, default),
            ],
        ),
    )
    action, streaming_container = await app.astream_result(
        halt_after=[], halt_before=["counter_final"]
    )
    results = [
        item async for item in streaming_container
    ]  # this should just have the intermediate results
    assert len(results) == 0  # nothing to stream
    result, state = await streaming_container.get()
    assert action.name == "counter_final"  # halt before this one
    assert result is None
    assert state["count"] == 10
    assert [item["sequence_id"] for _, item in action_tracker.pre_called] == list(
        range(0, 10)
    )  # ensure sequence ID is respected
    assert [item["sequence_id"] for _, item in action_tracker.post_called] == list(
        range(0, 10)
    )  # ensure sequence ID is respected
    assert len(action_tracker.post_run_execute_calls) == 1
    assert len(action_tracker.pre_run_execute_calls) == 1


def test_app_set_state():
    counter_action = base_counter_action.with_name("counter")
    app = Application(
        state=State(),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[Transition(counter_action, counter_action, default)],
        ),
    )
    assert "counter" not in app.state  # initial value
    app.step()
    assert app.state["count"] == 1  # updated value
    state = app.state
    app.update_state(state.update(count=2))
    assert app.state["count"] == 2  # updated value


def test_app_get_next_step():
    counter_action_1 = base_counter_action.with_name("counter_1")
    counter_action_2 = base_counter_action.with_name("counter_2")
    counter_action_3 = base_counter_action.with_name("counter_3")
    app = Application(
        state=State(),
        entrypoint="counter_1",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action_1, counter_action_2, counter_action_3],
            transitions=[
                Transition(counter_action_1, counter_action_2, default),
                Transition(counter_action_2, counter_action_3, default),
                Transition(counter_action_3, counter_action_1, default),
            ],
        ),
    )
    # uninitialized -- counter_1
    assert app.get_next_action().name == "counter_1"
    app.step()
    # ran counter_1 -- counter_2
    assert app.get_next_action().name == "counter_2"
    app.step()
    # ran counter_2 -- counter_3
    assert app.get_next_action().name == "counter_3"
    app.step()
    # ran counter_3 -- back to counter_1
    assert app.get_next_action().name == "counter_1"


def test_application_builder_complete():
    app = (
        ApplicationBuilder()
        .with_state(count=0)
        .with_actions(counter=base_counter_action, result=Result("count"))
        .with_transitions(
            ("counter", "counter", Condition.expr("count < 10")), ("counter", "result")
        )
        .with_entrypoint("counter")
        .build()
    )
    graph = app.graph
    assert len(graph.actions) == 2
    assert len(graph.transitions) == 2
    assert app.get_next_action().name == "counter"


def test__validate_start_valid():
    _validate_start("counter", {"counter", "result"})


def test__validate_start_not_found():
    with pytest.raises(ValueError, match="not found"):
        _validate_start("counter", {"result"})


def test__adjust_single_step_output_result_and_state():
    state = State({"count": 1})
    result = {"count": 1}
    assert _adjust_single_step_output((result, state), "test_action", DEFAULT_SCHEMA) == (
        result,
        state,
    )


def test__adjust_single_step_output_just_state():
    state = State({"count": 1})
    assert _adjust_single_step_output(state, "test_action", DEFAULT_SCHEMA) == ({}, state)


def test__adjust_single_step_output_errors_incorrect_type():
    state = "foo"
    with pytest.raises(ValueError, match="must return either"):
        _adjust_single_step_output(state, "test_action", DEFAULT_SCHEMA)


def test__adjust_single_step_output_errors_incorrect_result_type():
    state = State()
    result = "bar"
    with pytest.raises(ValueError, match="non-dict"):
        _adjust_single_step_output((state, result), "test_action", DEFAULT_SCHEMA)


def test_application_builder_unset():
    with pytest.raises(ValueError):
        ApplicationBuilder().build()


def test_application_run_step_hooks_sync():
    action_tracker = CallCaptureTracker()
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count").with_name("result")
    app = Application(
        state=State({}),
        entrypoint="counter",
        adapter_set=internal.LifecycleAdapterSet(action_tracker),
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, result_action, Condition.expr("count >= 10")),
                Transition(counter_action, counter_action, default),
            ],
        ),
    )
    app.run(halt_after=["result"])
    assert set(dict(action_tracker.pre_called).keys()) == {"counter", "result"}
    assert set(dict(action_tracker.post_called).keys()) == {"counter", "result"}
    # assert sequence id is incremented
    assert action_tracker.pre_called[0][1]["sequence_id"] == 1
    assert action_tracker.post_called[0][1]["sequence_id"] == 1
    assert {
        "action",
        "sequence_id",
        "state",
        "inputs",
        "app_id",
        "partition_key",
    }.issubset(set(action_tracker.pre_called[0][1].keys()))
    assert {
        "sequence_id",
        "result",
        "state",
        "exception",
        "app_id",
        "partition_key",
    }.issubset(set(action_tracker.post_called[0][1].keys()))
    assert len(action_tracker.pre_called) == 11
    assert len(action_tracker.post_called) == 11
    # quick inclusion to ensure that the action is not called when we're done running
    assert len(action_tracker.post_run_execute_calls) == 1
    assert len(action_tracker.pre_run_execute_calls) == 1
    assert app.step() is None  # should be None
    assert len(action_tracker.post_run_execute_calls) == 2
    assert len(action_tracker.pre_run_execute_calls) == 2


async def test_application_run_step_hooks_async():
    tracker = ActionTrackerAsync()
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count").with_name("result")
    app = Application(
        state=State({}),
        entrypoint="counter",
        adapter_set=internal.LifecycleAdapterSet(tracker),
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, result_action, Condition.expr("count >= 10")),
                Transition(counter_action, counter_action, default),
            ],
        ),
    )
    await app.arun(halt_after=["result"])
    assert set(dict(tracker.pre_called).keys()) == {"counter", "result"}
    assert set(dict(tracker.post_called).keys()) == {"counter", "result"}
    # assert sequence id is incremented
    assert tracker.pre_called[0][1]["sequence_id"] == 1
    assert tracker.post_called[0][1]["sequence_id"] == 1
    assert {
        "sequence_id",
        "state",
        "inputs",
        "app_id",
        "partition_key",
    }.issubset(set(tracker.pre_called[0][1].keys()))
    assert {
        "sequence_id",
        "result",
        "state",
        "exception",
        "app_id",
        "partition_key",
    }.issubset(set(tracker.post_called[0][1].keys()))
    assert len(tracker.pre_called) == 11
    assert len(tracker.post_called) == 11


async def test_application_run_step_runs_hooks():
    hooks = [CallCaptureTracker(), ActionTrackerAsync()]

    counter_action = base_counter_action.with_name("counter")
    app = Application(
        state=State({}),
        entrypoint="counter",
        adapter_set=internal.LifecycleAdapterSet(*hooks),
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action],
            transitions=[
                Transition(counter_action, counter_action, default),
            ],
        ),
    )
    await app.astep()
    assert len(hooks[0].pre_called) == 1
    assert len(hooks[0].post_called) == 1
    # assert sequence id is incremented
    assert hooks[0].pre_called[0][1]["sequence_id"] == 1
    assert hooks[0].post_called[0][1]["sequence_id"] == 1
    assert {
        "sequence_id",
        "state",
        "inputs",
        "app_id",
        "partition_key",
        "action",
    }.issubset(set(hooks[0].pre_called[0][1].keys()))
    assert {
        "sequence_id",
        "state",
        "inputs",
        "app_id",
        "partition_key",
    }.issubset(set(hooks[1].pre_called[0][1].keys()))
    assert {
        "sequence_id",
        "result",
        "state",
        "exception",
        "app_id",
        "partition_key",
    }.issubset(set(hooks[0].post_called[0][1].keys()))
    assert {
        "sequence_id",
        "result",
        "state",
        "exception",
        "app_id",
        "partition_key",
    }.issubset(set(hooks[1].post_called[0][1].keys()))
    assert len(hooks[1].pre_called) == 1
    assert len(hooks[1].post_called) == 1
    assert len(hooks[0].post_run_execute_calls) == 1
    assert len(hooks[0].pre_run_execute_calls) == 1


def test_application_post_application_create_hook():
    class PostApplicationCreateTracker(PostApplicationCreateHook):
        def __init__(self):
            self.called_args = None
            self.call_count = 0

        def post_application_create(self, **kwargs):
            self.called_args = kwargs
            self.call_count += 1

    tracker = PostApplicationCreateTracker()
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count").with_name("result")
    Application(
        state=State({}),
        entrypoint="counter",
        adapter_set=internal.LifecycleAdapterSet(tracker),
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, result_action, Condition.expr("count >= 10")),
                Transition(counter_action, counter_action, default),
            ],
        ),
    )
    assert "state" in tracker.called_args
    assert "application_graph" in tracker.called_args
    assert tracker.call_count == 1


async def test_application_gives_graph():
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count").with_name("result")
    app = Application(
        state=State({}),
        entrypoint="counter",
        partition_key="test",
        uid="test-123",
        sequence_id=0,
        graph=Graph(
            actions=[counter_action, result_action],
            transitions=[
                Transition(counter_action, result_action, Condition.expr("count >= 10")),
                Transition(counter_action, counter_action, default),
            ],
        ),
    )
    graph = app.graph
    assert len(graph.actions) == 2
    assert len(graph.transitions) == 2
    assert graph.entrypoint.name == "counter"


def test_application_builder_initialize_does_not_allow_state_setting():
    with pytest.raises(ValueError, match="Cannot call initialize_from"):
        ApplicationBuilder().with_entrypoint("foo").with_state(**{"foo": "bar"}).initialize_from(
            DevNullPersister(),
            resume_at_next_action=True,
            default_state={},
            default_entrypoint="foo",
        )


class BrokenPersister(BaseStatePersister):
    """Broken persistor."""

    def load(
        self, partition_key: str, app_id: Optional[str], sequence_id: Optional[int] = None, **kwargs
    ) -> Optional[PersistedStateData]:
        return dict(
            partition_key="key",
            app_id="id",
            sequence_id=0,
            position="foo",
            state=None,
            created_at="",
            status="completed",
        )

    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        return []

    def save(
        self,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int,
        position: str,
        state: State,
        status: Literal["completed", "failed"],
        **kwargs,
    ):
        return


def test_application_builder_initialize_raises_on_broken_persistor():
    """Persisters should return None when there is no state to be loaded and the default used."""
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count").with_name("result")
    with pytest.raises(ValueError, match="but value for state was None"):
        (
            ApplicationBuilder()
            .with_actions(counter_action, result_action)
            .with_transitions(("counter", "result", default))
            .initialize_from(
                BrokenPersister(),
                resume_at_next_action=True,
                default_state={},
                default_entrypoint="foo",
            )
            .build()
        )


def test_load_from_sync_cannot_have_async_persistor_error():
    builder = ApplicationBuilder()
    builder.initialize_from(
        AsyncDevNullPersister(),
        resume_at_next_action=True,
        default_state={},
        default_entrypoint="foo",
    )
    with pytest.raises(
        ValueError, match="are building the sync application, but have used an async initializer."
    ):
        # we have not initialized
        builder._load_from_sync_persister()


async def test_load_from_async_cannot_have_sync_persistor_error():
    await asyncio.sleep(0.00001)
    builder = ApplicationBuilder()
    builder.initialize_from(
        DevNullPersister(),
        resume_at_next_action=True,
        default_state={},
        default_entrypoint="foo",
    )
    with pytest.raises(
        ValueError, match="are building the async application, but have used an sync initializer."
    ):
        # we have not initialized
        await builder._load_from_async_persister()


def test_application_builder_assigns_correct_actions_with_dual_api():
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count")

    @action(reads=[], writes=[])
    def test_action(state: State) -> State:
        return state

    app = (
        ApplicationBuilder()
        .with_state(count=0)
        .with_actions(counter_action, test_action, result=result_action)
        .with_transitions()
        .with_entrypoint("counter")
        .build()
    )
    graph = app.graph
    assert {a.name for a in graph.actions} == {"counter", "result", "test_action"}


def test__validate_halt_conditions():
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count")

    @action(reads=[], writes=[])
    def test_action(state: State) -> State:
        return state

    app = (
        ApplicationBuilder()
        .with_state(count=0)
        .with_actions(counter_action, test_action, result=result_action)
        .with_transitions()
        .with_entrypoint("counter")
        .build()
    )
    with pytest.raises(ValueError, match="(?=.*no_exist_1)(?=.*no_exist_2)"):
        app._validate_halt_conditions(halt_after=["no_exist_1"], halt_before=["no_exist_2"])


def test_application_builder_initialize_raises_on_fork_app_id_not_provided():
    """Can't pass in fork_from* without an app_id."""
    with pytest.raises(ValueError, match="If you set fork_from_partition_key"):
        counter_action = base_counter_action.with_name("counter")
        result_action = Result("count").with_name("result")
        (
            ApplicationBuilder()
            .with_actions(counter_action, result_action)
            .with_transitions(("counter", "result", default))
            .initialize_from(
                BrokenPersister(),
                resume_at_next_action=True,
                default_state={},
                default_entrypoint="foo",
                fork_from_sequence_id=1,
                fork_from_partition_key="foo-bar",
            )
            .build()
        )


class DummyPersister(BaseStatePersister):
    """Dummy persistor."""

    def load(
        self, partition_key: str, app_id: Optional[str], sequence_id: Optional[int] = None, **kwargs
    ) -> Optional[PersistedStateData]:
        return PersistedStateData(
            partition_key="user123",
            app_id="123",
            sequence_id=5,
            position="counter",
            state=State({"count": 5}),
            created_at="",
            status="completed",
        )

    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        return ["123"]

    def save(
        self,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int,
        position: str,
        state: State,
        status: Literal["completed", "failed"],
        **kwargs,
    ):
        return


def test_application_builder_initialize_fork_errors_on_same_app_id():
    """Tests that we can't have an app_id and fork_from_app_id that's the same"""
    with pytest.raises(ValueError, match="Cannot fork and save"):
        counter_action = base_counter_action.with_name("counter")
        result_action = Result("count").with_name("result")
        (
            ApplicationBuilder()
            .with_actions(counter_action, result_action)
            .with_transitions(("counter", "result", default))
            .initialize_from(
                DummyPersister(),
                resume_at_next_action=True,
                default_state={},
                default_entrypoint="foo",
                fork_from_app_id="123",
                fork_from_partition_key="user123",
            )
            .with_identifiers(app_id="123")
            .build()
        )


def test_application_builder_initialize_fork_app_id_happy_pth():
    """Tests that forking properly works"""
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count").with_name("result")
    old_app_id = "123"
    app = (
        ApplicationBuilder()
        .with_actions(counter_action, result_action)
        .with_transitions(("counter", "result", default))
        .initialize_from(
            DummyPersister(),
            resume_at_next_action=True,
            default_state={},
            default_entrypoint="counter",
            fork_from_app_id=old_app_id,
            fork_from_partition_key="user123",
        )
        .with_identifiers(app_id="test123")
        .build()
    )
    assert app.uid != old_app_id
    assert app.state == State({"count": 5, "__PRIOR_STEP": "counter", "__SEQUENCE_ID": 5})
    assert app.parent_pointer.app_id == old_app_id


class NoOpTracker(SyncTrackingClient):
    def copy(self):
        pass

    def pre_start_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass

    def post_stream_item(
        self,
        *,
        item: Any,
        item_index: int,
        stream_initialize_time: datetime.datetime,
        first_stream_item_start_time: datetime.datetime,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass

    def post_end_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass

    def do_log_attributes(self, **future_kwargs: Any):
        pass

    def __init__(self, unique_id: str):
        self.unique_id = unique_id

    def post_application_create(self, **future_kwargs: Any):
        pass

    def pre_run_step(self, **future_kwargs: Any):
        pass

    def post_run_step(self, **future_kwargs: Any):
        pass

    def pre_start_span(self, **future_kwargs: Any):
        pass

    def post_end_span(self, **future_kwargs: Any):
        pass


def test_application_exposes_app_context():
    """Tests that we can get the context from the application correctly"""
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count").with_name("result")
    app = (
        ApplicationBuilder()
        .with_actions(counter_action, result_action)
        .with_transitions(("counter", "result", default))
        .with_tracker(NoOpTracker("unique_tracker_name"))
        .with_identifiers(app_id="test123", partition_key="user123", sequence_id=5)
        .with_entrypoint("counter")
        .with_state(count=0)
        .build()
    )
    context = app.context
    assert context.app_id == "test123"
    assert context.partition_key == "user123"
    assert context.sequence_id == 5
    assert context.tracker.unique_id == "unique_tracker_name"


def test_application_exposes_app_context_through_context_manager_sync():
    """Tests that we can get the context from the application correctly"""

    @action(reads=["count"], writes=["count"])
    def counter(state: State) -> State:
        app_context = ApplicationContext.get()
        assert app_context is not None
        assert app_context.tracker is not None  # NoOpTracker is used
        assert isinstance(app_context.sequence_id, int)
        assert app_context.app_id == "test123"
        return state.update(count=state["count"] + 1)

    result_action = Result("count").with_name("result")
    app = (
        ApplicationBuilder()
        .with_actions(result_action, counter=counter)
        .with_transitions(("counter", "result", default))
        .with_tracker(NoOpTracker("unique_tracker_name"))
        .with_identifiers(app_id="test123", partition_key="user123", sequence_id=5)
        .with_entrypoint("counter")
        .with_state(count=0)
        .build()
    )
    app.run(halt_after=["result"])


async def test_application_exposes_app_context_through_context_manager_async():
    """Tests that we can get the context from the application correctly"""

    @action(reads=["count"], writes=["count"])
    async def counter(state: State) -> State:
        app_context = ApplicationContext.get()
        assert app_context is not None
        assert app_context.tracker is not None  # NoOpTracker is used
        assert isinstance(app_context.sequence_id, int)
        assert app_context.app_id == "test123"
        return state.update(count=state["count"] + 1)

    result_action = Result("count").with_name("result")
    app = (
        ApplicationBuilder()
        .with_actions(result_action, counter=counter)
        .with_transitions(("counter", "result", default))
        .with_tracker(NoOpTracker("unique_tracker_name"))
        .with_identifiers(app_id="test123", partition_key="user123", sequence_id=5)
        .with_entrypoint("counter")
        .with_state(count=0)
        .build()
    )
    await app.arun(halt_after=["result"])


def test_application_passes_context_when_declared():
    """Tests that the context is passed to the function correctly"""
    context_list = []

    @action(reads=["count"], writes=["count"])
    def context_counter(state: State, __context: ApplicationContext) -> State:
        context_list.append(__context)
        return state.update(count=state["count"] + 1)

    result_action = Result("count")
    app = (
        ApplicationBuilder()
        .with_actions(counter=context_counter, result=result_action)
        .with_transitions(("counter", "counter", expr("count < 10")), ("counter", "result"))
        .with_tracker(NoOpTracker("unique_tracker_name"))
        .with_identifiers(app_id="test123", partition_key="user123", sequence_id=5)
        .with_entrypoint("counter")
        .with_state(count=0)
        .build()
    )
    app.run(halt_after=["result"])
    sequence_ids = [context.sequence_id for context in context_list]
    assert sequence_ids == list(range(6, 16))
    app_ids = set(context.app_id for context in context_list)
    assert app_ids == {"test123"}
    trackers = set(context.tracker.unique_id for context in context_list)
    assert trackers == {"unique_tracker_name"}


def test_optional_context_in_dependency_factories():
    """Tests that the context is passed to the function correctly when nulled out.
    TODO -- get this to test without instantiating an application through the builder --
    this is slightly overkill for a bit of code"""
    context_list = []

    @action(reads=["count"], writes=["count"])
    def context_counter(state: State, __context: ApplicationContext = None) -> State:
        context_list.append(__context)
        return state.update(count=state["count"] + 1)

    result_action = Result("count")
    app = (
        ApplicationBuilder()
        .with_actions(counter=context_counter, result=result_action)
        .with_transitions(("counter", "counter", expr("count < 10")), ("counter", "result"))
        .with_tracker(NoOpTracker("unique_tracker_name"))
        .with_identifiers(app_id="test123", partition_key="user123", sequence_id=5)
        .with_entrypoint("counter")
        .with_state(count=0)
        .build()
    )
    inputs = app._process_inputs({}, app.get_next_action())
    assert "__context" in inputs  # it should be there
    assert inputs["__context"] is not None  # it should not be None
    assert inputs["__context"].app_id == "test123"  # it should be the correct context
    assert (
        inputs["__context"].tracker.unique_id == "unique_tracker_name"
    )  # it should be the correct context


def test_application_with_no_spawning_parent():
    """Test that the application does not have a spawning parent when it is not specified"""
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count").with_name("result")
    app = (
        ApplicationBuilder()
        .with_actions(counter_action, result_action)
        .with_transitions(("counter", "result", default))
        .with_identifiers(app_id="test123", partition_key="user123", sequence_id=5)
        .with_entrypoint("counter")
        .with_state(count=0)
        .build()
    )
    spawned_by = app.spawning_parent_pointer
    assert spawned_by is None


def test_application_with_spawning_parent():
    """Tests that the application builder can specify a spawning
    parent and it gets wired through to the app."""
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count").with_name("result")
    app = (
        ApplicationBuilder()
        .with_actions(counter_action, result_action)
        .with_transitions(("counter", "result", default))
        .with_identifiers(app_id="test123", partition_key="user123")
        .with_spawning_parent(app_id="test123", partition_key="user123", sequence_id=5)
        .with_entrypoint("counter")
        .with_state(count=0)
        .build()
    )
    spawned_by = app.spawning_parent_pointer
    assert spawned_by is not None
    assert spawned_by.app_id == "test123"
    assert spawned_by.partition_key == "user123"
    assert spawned_by.sequence_id == 5


def test_application_does_not_allow_dunderscore_inputs():
    """Tests that the context is passed to the function correctly when nulled out.
    TODO -- get this to test without instantiating an application through the builder --
    this is slightly overkill for a bit of code"""
    result_action = Result("count").with_name("result")
    app = (
        ApplicationBuilder()
        .with_actions(result_action)
        .with_entrypoint("result")
        .with_transitions()
        .with_state(count=0)
        .build()
    )
    with pytest.raises(ValueError, match="double underscore"):
        app._process_inputs({"__not_allowed": ...}, app.get_next_action())


def test_application_recursive_action_lifecycle_hooks():
    """Tests that calling burr within burr works as expected"""

    class TestingHook(PreApplicationExecuteCallHook, PostApplicationExecuteCallHook):
        def __init__(self):
            self.pre_called = []
            self.post_called = []

        def pre_run_execute_call(
            self,
            *,
            app_id: str,
            partition_key: str,
            state: "State",
            method: ExecuteMethod,
            **future_kwargs: Any,
        ):
            self.pre_called.append((app_id, partition_key, state, method))

        def post_run_execute_call(
            self,
            *,
            app_id: str,
            partition_key: str,
            state: "State",
            method: ExecuteMethod,
            exception: Optional[Exception],
            **future_kwargs,
        ):
            self.post_called.append((app_id, partition_key, state, method, exception))

    hook = TestingHook()
    foo = []

    @action(reads=["recursion_count", "total_count"], writes=["recursion_count", "total_count"])
    def recursive_action(state: State) -> State:
        foo.append(1)
        recursion_count = state["recursion_count"]
        if recursion_count == 5:
            return state
        # Fork bomb!
        total_counts = []
        for i in range(2):
            app = (
                ApplicationBuilder()
                .with_graph(graph)
                .with_hooks(hook)
                .with_entrypoint("recursive_action")
                .with_state(recursion_count=recursion_count + 1, total_count=1)
                .build()
            )
            action, result, state = app.run(halt_after=["recursive_action"])
            total_counts.append(state["total_count"])
        return state.update(
            recursion_count=state["recursion_count"], total_count=sum(total_counts) + 1
        )

    graph = GraphBuilder().with_actions(recursive_action).with_transitions().build()

    # initial to kick it off
    result = recursive_action(State({"recursion_count": 0, "total_count": 0}))
    # Basic sanity checks to demonstrate
    assert result["recursion_count"] == 5
    assert result["total_count"] == 63  # One for each of the calls (sum(2**n for n in range(6)))
    assert (
        len(hook.pre_called) == 62
    )  # 63 - the initial one from the call to recursive_action outside the application
    assert len(hook.post_called) == 62  # ditto


class CounterState(State):
    count: int


class SimpleTypingSystem(TypingSystem[CounterState]):
    def state_type(self) -> type[CounterState]:
        return CounterState

    def state_pre_action_run_type(self, action: Action, graph: Graph) -> type[Any]:
        raise NotImplementedError

    def state_post_action_run_type(self, action: Action, graph: Graph) -> type[Any]:
        raise NotImplementedError

    def construct_data(self, state: State[Any]) -> CounterState:
        return CounterState({"count": state["count"]})

    def construct_state(self, data: Any) -> State[Any]:
        raise NotImplementedError


def test_builder_captures_typing_system():
    """Tests that the typing system is captured correctly"""
    counter_action = base_counter_action.with_name("counter")
    result_action = Result("count").with_name("result")
    app = (
        ApplicationBuilder()
        .with_actions(counter_action, result_action)
        .with_transitions(("counter", "counter", expr("count < 10")))
        .with_transitions(("counter", "result", default))
        .with_entrypoint("counter")
        .with_state(count=0)
        .with_typing(SimpleTypingSystem())
        .build()
    )
    assert isinstance(app.state.data, CounterState)
    _, _, state = app.run(halt_after=["result"])
    assert isinstance(state.data, CounterState)
    assert state.data["count"] == 10


def test_set_sync_state_persister_cannot_have_async_error():
    builder = ApplicationBuilder()
    persister = AsyncDevNullPersister()
    builder.with_state_persister(persister)
    with pytest.raises(
        ValueError, match="are building the sync application, but have used an async persister."
    ):
        # we have not initialized
        builder._set_sync_state_persister()


def test_set_sync_state_persister_is_not_initialized_error(tmp_path):
    builder = ApplicationBuilder()
    persister = SQLLitePersister(db_path=":memory:", table_name="test_table")
    builder.with_state_persister(persister)
    with pytest.raises(RuntimeError):
        # we have not initialized
        builder._set_sync_state_persister()


async def test_set_async_state_persister_cannot_have_sync_error():
    await asyncio.sleep(0.00001)
    builder = ApplicationBuilder()
    persister = DevNullPersister()
    builder.with_state_persister(persister)
    with pytest.raises(
        ValueError, match="are building the async application, but have used an sync persister."
    ):
        # we have not initialized
        await builder._set_async_state_persister()


async def test_set_async_state_persister_is_not_initialized_error(tmp_path):
    await asyncio.sleep(0.00001)
    builder = ApplicationBuilder()

    class FakePersister(AsyncDevNullPersister):
        async def is_initialized(self):
            return False

    persister = FakePersister()
    builder.with_state_persister(persister)
    with pytest.raises(RuntimeError):
        # we have not initialized
        await builder._set_async_state_persister()


def test_with_state_persister_is_initialized_not_implemented():
    builder = ApplicationBuilder()

    class FakePersister(BaseStatePersister):
        # does not implement is_initialized
        def list_app_ids(self):
            return []

        def save(
            self,
            partition_key: Optional[str],
            app_id: str,
            sequence_id: int,
            position: str,
            state: State,
            status: Literal["completed", "failed"],
            **kwargs,
        ):
            pass

        def load(
            self,
            partition_key: str,
            app_id: Optional[str],
            sequence_id: Optional[int] = None,
            **kwargs,
        ):
            return None

    persister = FakePersister()
    # Add the persister to the builder, expecting no exceptions
    builder.with_state_persister(persister)


class ActionWithoutContext(Action):
    def run(self, other_param, foo):
        pass

    @property
    def reads(self) -> list[str]:
        pass

    @property
    def writes(self) -> list[str]:
        pass

    def update(self, result: dict, state: State) -> State:
        pass

    def inputs(self) -> Union[list[str], tuple[list[str], list[str]]]:
        return ["other_param", "foo"]


class ActionWithContext(ActionWithoutContext):
    def run(self, __context, other_param, foo):
        pass

    def inputs(self) -> Union[list[str], tuple[list[str], list[str]]]:
        return ["other_param", "foo", "__context"]


class ActionWithKwargs(ActionWithoutContext):
    def run(self, other_param, foo, **kwargs):
        pass

    def inputs(self) -> Union[list[str], tuple[list[str], list[str]]]:
        return ["other_param", "foo", "__context"]


class ActionWithContextTracer(ActionWithoutContext):
    def run(self, __context, other_param, foo, __tracer):
        pass

    def inputs(self) -> Union[list[str], tuple[list[str], list[str]]]:
        return ["other_param", "foo", "__context", "__tracer"]


def test_remap_context_variable_with_mangled_context_kwargs():
    _action = ActionWithKwargs()

    inputs = {"__context": "context_value", "other_key": "other_value", "foo": "foo_value"}
    expected = {"__context": "context_value", "other_key": "other_value", "foo": "foo_value"}
    assert _remap_dunder_parameters(_action.run, inputs, ["__context", "__tracer"]) == expected


def test_remap_context_variable_with_mangled_context():
    _action = ActionWithContext()

    inputs = {"__context": "context_value", "other_key": "other_value", "foo": "foo_value"}
    expected = {
        f"_{ActionWithContext.__name__}__context": "context_value",
        "other_key": "other_value",
        "foo": "foo_value",
    }
    assert _remap_dunder_parameters(_action.run, inputs, ["__context", "__tracer"]) == expected


def test_remap_context_variable_with_mangled_contexttracer():
    _action = ActionWithContextTracer()

    inputs = {
        "__context": "context_value",
        "__tracer": "tracer_value",
        "other_key": "other_value",
        "foo": "foo_value",
    }
    expected = {
        f"_{ActionWithContextTracer.__name__}__context": "context_value",
        "other_key": "other_value",
        "foo": "foo_value",
        f"_{ActionWithContextTracer.__name__}__tracer": "tracer_value",
    }
    assert _remap_dunder_parameters(_action.run, inputs, ["__context", "__tracer"]) == expected


def test_remap_context_variable_without_mangled_context():
    _action = ActionWithoutContext()
    inputs = {"__context": "context_value", "other_key": "other_value", "foo": "foo_value"}
    expected = {"__context": "context_value", "other_key": "other_value", "foo": "foo_value"}
    assert _remap_dunder_parameters(_action.run, inputs, ["__context", "__tracer"]) == expected


async def test_async_application_builder_initialize_raises_on_broken_persistor():
    """Persisters should return None when there is no state to be loaded and the default used."""
    await asyncio.sleep(0.00001)
    counter_action = base_counter_action_async.with_name("counter")
    result_action = Result("count").with_name("result")

    class AsyncBrokenPersister(AsyncDevNullPersister):
        async def load(
            self,
            partition_key: str,
            app_id: Optional[str],
            sequence_id: Optional[int] = None,
            **kwargs,
        ) -> Optional[PersistedStateData]:
            await asyncio.sleep(0.0001)
            return dict(
                partition_key="key",
                app_id="id",
                sequence_id=0,
                position="foo",
                state=None,
                created_at="",
                status="completed",
            )

    with pytest.raises(ValueError, match="but value for state was None"):
        await (
            ApplicationBuilder()
            .with_actions(counter_action, result_action)
            .with_transitions(("counter", "result", default))
            .initialize_from(
                AsyncBrokenPersister(),
                resume_at_next_action=True,
                default_state={},
                default_entrypoint="foo",
            )
            .abuild()
        )


def test_application__process_control_flow_params():
    @action(reads=[], writes=[], tags=["tag1", "tag2"])
    def test_action(state: State) -> State:
        return state

    @action(reads=[], writes=[], tags=["tag1", "tag3"])
    def test_action_2(state: State) -> State:
        return state

    app = (
        ApplicationBuilder()
        .with_state(count=0)
        .with_actions(test_action, test_action_2)
        .with_transitions(("test_action", "test_action_2"))
        .with_entrypoint("test_action")
        .build()
    )
    halt_before, halt_after, inputs = app._process_control_flow_params(
        halt_after=["@tag:tag1"], halt_before=["@tag:tag2"]
    )

    assert sorted(halt_after) == ["test_action", "test_action_2"]
    assert halt_before == ["test_action"]
    assert inputs == {}

def test_initialize_from_applies_override_state_values():
    class FakeStateLoader(BaseStateLoader):
        def load(self, partition_key, app_id, sequence_id):
            return {
                "state": State({"x": 1}),
                "position": None,
                "sequence_id": 0,
                "status": "completed",
            }

        def list_app_ids(self, partition_key):
            return []

    @action(reads=[], writes=[])
    def noop(state: State) -> State:
        return state

    builder = (
        ApplicationBuilder()
        .initialize_from(
            initializer=FakeStateLoader(),
            resume_at_next_action=False,
            default_state={},
            default_entrypoint="noop",
            override_state_values={"x": 100},
        )
        .with_actions(noop)
        .with_transitions()
    )

    app = builder.build()

    assert app.state["x"] == 100
