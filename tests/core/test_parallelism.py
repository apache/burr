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
import concurrent.futures
import dataclasses
import datetime
from random import random
from typing import Any, AsyncGenerator, Callable, Dict, Generator, List, Literal, Optional, Union

import pytest

from burr.common import types as burr_types
from burr.core import (
    Action,
    ApplicationBuilder,
    ApplicationContext,
    ApplicationGraph,
    State,
    action,
)
from burr.core.action import Input, Result
from burr.core.graph import GraphBuilder
from burr.core.parallelism import (
    MapActions,
    MapActionsAndStates,
    MapStates,
    RunnableGraph,
    SubGraphTask,
    TaskBasedParallelAction,
    _cascade_adapter,
    map_reduce_action,
)
from burr.core.persistence import BaseStateLoader, BaseStateSaver, PersistedStateData
from burr.tracking.base import SyncTrackingClient
from burr.visibility import ActionSpan

old_action = action


async def sleep_random():
    await asyncio.sleep(random() / 1000)


# Single action/callable subgraph
@action(reads=["input_number", "number_to_add"], writes=["output_number"])
def simple_single_fn_subgraph(
    state: State, additional_number: int = 1, identifying_number: int = 1000
) -> State:
    return state.update(
        output_number=state["input_number"]
        + state["number_to_add"]
        + additional_number
        + identifying_number
    )


# Single action/callable subgraph
@action(reads=["input_number", "number_to_add"], writes=["output_number"])
async def simple_single_fn_subgraph_async(
    state: State, additional_number: int = 1, identifying_number: int = 1000
) -> State:
    await sleep_random()
    return state.update(
        output_number=state["input_number"]
        + state["number_to_add"]
        + additional_number
        + identifying_number
    )


class ClassBasedAction(Action):
    def __init__(self, identifying_number: int, name: str = "class_based_action"):
        super().__init__()
        self._name = name
        self.identifying_number = identifying_number

    @property
    def reads(self) -> list[str]:
        return ["input_number", "number_to_add"]

    def run(self, state: State, **run_kwargs) -> dict:
        return {
            "output_number": state["input_number"]
            + state["number_to_add"]
            + run_kwargs.get("additional_number", 1)
            + self.identifying_number
        }

    @property
    def writes(self) -> list[str]:
        return ["output_number"]

    def update(self, result: dict, state: State) -> State:
        return state.update(**result)


class ClassBasedActionAsync(ClassBasedAction):
    async def run(self, state: State, **run_kwargs) -> dict:
        await sleep_random()
        return super().run(state, **run_kwargs)


@action(reads=["input_number"], writes=["current_number"])
def entry_action_for_subgraph(state: State) -> State:
    return state.update(current_number=state["input_number"])


@action(reads=["current_number", "number_to_add"], writes=["current_number"])
def add_number_to_add(state: State) -> State:
    return state.update(current_number=state["current_number"] + state["number_to_add"])


@action(reads=["current_number"], writes=["current_number"])
def add_additional_number_to_add(
    state: State, additional_number: int = 1, identifying_number: int = 3000
) -> State:
    return state.update(
        current_number=state["current_number"] + additional_number + identifying_number
    )  # 1000 is the one that marks this as different


@action(reads=["current_number"], writes=["output_number"])
def final_result(state: State) -> State:
    return state.update(output_number=state["current_number"])


@action(reads=["input_number"], writes=["current_number"])
async def entry_action_for_subgraph_async(state: State) -> State:
    await sleep_random()
    return entry_action_for_subgraph(state)


@action(reads=["current_number", "number_to_add"], writes=["current_number"])
async def add_number_to_add_async(state: State) -> State:
    await sleep_random()
    return add_number_to_add(state)


@action(reads=["current_number"], writes=["current_number"])
async def add_additional_number_to_add_async(
    state: State, additional_number: int = 1, identifying_number: int = 3000
) -> State:
    await sleep_random()
    return add_additional_number_to_add(
        state, additional_number=additional_number, identifying_number=identifying_number
    )  # 1000 is the one that marks this as different


@action(reads=["current_number"], writes=["output_number"])
async def final_result_async(state: State) -> State:
    await sleep_random()
    return final_result(state)


SubGraphType = Union[Action, Callable, RunnableGraph]


def create_full_subgraph(identifying_number: int = 0) -> SubGraphType:
    return RunnableGraph(
        graph=(
            GraphBuilder()
            .with_actions(
                entry_action_for_subgraph,
                add_number_to_add,
                add_additional_number_to_add.bind(identifying_number=identifying_number),
                final_result,
            )
            .with_transitions(
                ("entry_action_for_subgraph", "add_number_to_add"),
                ("add_number_to_add", "add_additional_number_to_add"),
                ("add_additional_number_to_add", "final_result"),
            )
            .build()
        ),
        entrypoint="entry_action_for_subgraph",
        halt_after=["final_result"],
    )


def create_full_subgraph_async(identifying_number: int = 0) -> SubGraphType:
    return RunnableGraph(
        graph=GraphBuilder()
        .with_actions(
            entry_action_for_subgraph=entry_action_for_subgraph_async,
            add_number_to_add=add_number_to_add_async,
            add_additional_number_to_add=add_additional_number_to_add_async.bind(
                identifying_number=identifying_number
            ),
            final_result=final_result_async,
        )
        .with_transitions(
            ("entry_action_for_subgraph", "add_number_to_add"),
            ("add_number_to_add", "add_additional_number_to_add"),
            ("add_additional_number_to_add", "final_result"),
        )
        .build(),
        entrypoint="entry_action_for_subgraph",
        halt_after=["final_result"],
    )


FULL_SUBGRAPH: SubGraphType = create_full_subgraph(identifying_number=3000)
FULL_SUBGRAPH_ASYNC: SubGraphType = create_full_subgraph_async(identifying_number=3000)


@dataclasses.dataclass
class RecursiveActionTracked:
    state_before: Optional[State]
    state_after: Optional[State]
    action: Action
    app_id: str
    partition_key: str
    sequence_id: int
    children: List["RecursiveActionTracked"] = dataclasses.field(default_factory=list)


class RecursiveActionTracker(SyncTrackingClient):
    """Simple test tracking client for a recursive action"""

    def __init__(
        self,
        events: List[RecursiveActionTracked],
        parent: Optional["RecursiveActionTracker"] = None,
    ):
        self.events = events
        self.parent = parent

    def copy(self):
        """Quick way to copy from the current state. This assumes linearity (which is true in this case, as parallelism is delegated)"""
        if self.events:
            current_event = self.events[-1]
            if current_event.state_after is not None:
                raise ValueError("Don't copy if you're not in the middle of an event")
            return RecursiveActionTracker(current_event.children, parent=self)
        raise ValueError("Don't copy if you're not in the middle of an event")

    def post_application_create(
        self,
        *,
        app_id: str,
        partition_key: Optional[str],
        state: "State",
        application_graph: "ApplicationGraph",
        parent_pointer: Optional[burr_types.ParentPointer],
        spawning_parent_pointer: Optional[burr_types.ParentPointer],
        **future_kwargs: Any,
    ):
        pass

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
        self.events.append(
            RecursiveActionTracked(
                state_before=state,
                state_after=None,
                action=action,
                app_id=app_id,
                partition_key=partition_key,
                sequence_id=sequence_id,
            )
        )

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
        self.events[-1].state_after = state

    def pre_start_span(
        self,
        *,
        action: str,
        action_sequence_id: int,
        span: "ActionSpan",
        span_dependencies: list[str],
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass

    def post_end_span(
        self,
        *,
        action: str,
        action_sequence_id: int,
        span: "ActionSpan",
        span_dependencies: list[str],
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass

    def do_log_attributes(
        self,
        *,
        attributes: Dict[str, Any],
        action: str,
        action_sequence_id: int,
        span: Optional["ActionSpan"],
        tags: dict,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
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


def _group_events_by_app_id(
    events: List[RecursiveActionTracked],
) -> Dict[str, List[RecursiveActionTracked]]:
    grouped_events = {}
    for event in events:
        if event.app_id not in grouped_events:
            grouped_events[event.app_id] = []
        grouped_events[event.app_id].append(event)
    return grouped_events


def test_map_actions_default_state():
    class MapActionsAllApproaches(MapActions):
        def actions(
            self, state: State, inputs: Dict[str, Any], context: ApplicationContext
        ) -> Generator[Union[Action, Callable, RunnableGraph], None, None]: ...

        def reduce(self, state: State, states: Generator[State, None, None]) -> State: ...

        @property
        def writes(self) -> list[str]:
            return []

        @property
        def reads(self) -> list[str]:
            return []

    state_to_test = State({"foo": "bar", "baz": "qux"})
    assert MapActionsAllApproaches().state(state_to_test, {}).get_all() == state_to_test.get_all()


def test_e2e_map_actions_sync_subgraph():
    """Tests map actions over multiple action types (runnable graph, function, action class...)"""

    class MapActionsAllApproaches(MapActions):
        def actions(
            self, state: State, inputs: Dict[str, Any], context: ApplicationContext
        ) -> Generator[Union[Action, Callable, RunnableGraph], None, None]:
            for graph_ in [
                simple_single_fn_subgraph.bind(identifying_number=1000),
                ClassBasedAction(2000),
                create_full_subgraph(3000),
            ]:
                yield graph_

        def state(self, state: State, inputs: Dict[str, Any]):
            return state.update(input_number=state["input_number_in_state"], number_to_add=10)

        def reduce(self, state: State, states: Generator[State, None, None]) -> State:
            # TODO -- ensure that states is in the correct order...
            # Or decide to key it?
            new_state = state
            for output_state in states:
                new_state = new_state.append(output_numbers_in_state=output_state["output_number"])
            return new_state

        @property
        def writes(self) -> list[str]:
            return ["output_numbers_in_state"]

        @property
        def reads(self) -> list[str]:
            return ["input_number_in_state"]

    app = (
        ApplicationBuilder()
        .with_actions(
            initial_action=Input("input_number_in_state"),
            map_action=MapActionsAllApproaches(),
            final_action=Result("output_numbers_in_state"),
        )
        .with_transitions(("initial_action", "map_action"), ("map_action", "final_action"))
        .with_entrypoint("initial_action")
        .with_tracker(RecursiveActionTracker(events := []))
        .build()
    )
    action, result, state = app.run(
        halt_after=["final_action"], inputs={"input_number_in_state": 100}
    )
    assert state["output_numbers_in_state"] == [1111, 2111, 3111]  # esnsure order correct
    assert len(events) == 3  # three parent actions
    _, map_event, __ = events
    grouped_events = _group_events_by_app_id(map_event.children)
    assert len(grouped_events) == 3  # three unique App IDs, one for each launching subgraph


async def test_e2e_map_actions_async_subgraph():
    """Tests map actions over multiple action types (runnable graph, function, action class...)"""

    class MapActionsAllApproachesAsync(MapActions):
        def actions(
            self, state: State, inputs: Dict[str, Any], context: ApplicationContext
        ) -> Generator[Union[Action, Callable, RunnableGraph], None, None]:
            for graph_ in [
                simple_single_fn_subgraph_async.bind(identifying_number=1000),
                ClassBasedActionAsync(2000),
                create_full_subgraph_async(3000),
            ]:
                yield graph_

        def is_async(self) -> bool:
            return True

        def state(self, state: State, inputs: Dict[str, Any]):
            return state.update(input_number=state["input_number_in_state"], number_to_add=10)

        async def reduce(self, state: State, states: AsyncGenerator[State, None]) -> State:
            # TODO -- ensure that states is in the correct order...
            # Or decide to key it?
            new_state = state
            async for output_state in states:
                new_state = new_state.append(output_numbers_in_state=output_state["output_number"])
            return new_state

        @property
        def writes(self) -> list[str]:
            return ["output_numbers_in_state"]

        @property
        def reads(self) -> list[str]:
            return ["input_number_in_state"]

    app = (
        ApplicationBuilder()
        .with_actions(
            initial_action=Input("input_number_in_state"),
            map_action=MapActionsAllApproachesAsync(),
            final_action=Result("output_numbers_in_state"),
        )
        .with_transitions(("initial_action", "map_action"), ("map_action", "final_action"))
        .with_entrypoint("initial_action")
        .with_tracker(RecursiveActionTracker(events := []))
        .build()
    )
    action, result, state = await app.arun(
        halt_after=["final_action"], inputs={"input_number_in_state": 100}
    )
    assert state["output_numbers_in_state"] == [1111, 2111, 3111]  # ensure order correct
    assert len(events) == 3  # three parent actions
    _, map_event, __ = events
    grouped_events = _group_events_by_app_id(map_event.children)
    assert len(grouped_events) == 3  # three unique App IDs, one for each launching subgraph


@pytest.mark.parametrize(
    "action",
    [
        simple_single_fn_subgraph.bind(identifying_number=0),
        ClassBasedAction(0),
        create_full_subgraph(0),
    ],
)
def test_e2e_map_states_sync_subgraph(action: SubGraphType):
    """Tests the map states action with a subgraph that is run in parallel.
    Collatz conjecture over different starting points"""

    class MapStatesSync(MapStates):
        def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[State, None, None]:
            for input_number in state["input_numbers_in_state"]:
                yield state.update(input_number=input_number, number_to_add=10)

        def action(
            self, state: State, inputs: Dict[str, Any]
        ) -> Union[Action, Callable, RunnableGraph]:
            return action

        def is_async(self) -> bool:
            return False

        def reduce(self, state: State, states: Generator[State, None, None]) -> State:
            # TODO -- ensure that states is in the correct order...
            # Or decide to key it?
            new_state = state
            for output_state in states:
                new_state = new_state.append(output_numbers_in_state=output_state["output_number"])
            return new_state

        @property
        def writes(self) -> list[str]:
            return ["output_numbers_in_state"]

        @property
        def reads(self) -> list[str]:
            return ["input_numbers_in_state"]

    app = (
        ApplicationBuilder()
        .with_actions(
            initial_action=Input("input_numbers_in_state"),
            map_action=MapStatesSync(),
            final_action=Result("output_numbers_in_state"),
        )
        .with_transitions(("initial_action", "map_action"), ("map_action", "final_action"))
        .with_entrypoint("initial_action")
        .with_tracker(RecursiveActionTracker(events := []))
        .build()
    )
    action, result, state = app.run(
        halt_after=["final_action"], inputs={"input_numbers_in_state": [100, 200, 300]}
    )
    assert state["output_numbers_in_state"] == [111, 211, 311]  # ensure order correct
    assert len(events) == 3
    _, map_event, __ = events
    grouped_events = _group_events_by_app_id(map_event.children)
    assert len(grouped_events) == 3


@pytest.mark.parametrize(
    "action",
    [
        simple_single_fn_subgraph_async.bind(identifying_number=0),
        ClassBasedActionAsync(0),
        create_full_subgraph_async(0),
    ],
)
async def test_e2e_map_states_async_subgraph(action: SubGraphType):
    """Tests the map states action with a subgraph that is run in parallel.
    Collatz conjecture over different starting points"""

    class MapStatesAsync(MapStates):
        def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[State, None, None]:
            for input_number in state["input_numbers_in_state"]:
                yield state.update(input_number=input_number, number_to_add=10)

        def action(
            self, state: State, inputs: Dict[str, Any]
        ) -> Union[Action, Callable, RunnableGraph]:
            return action

        def is_async(self) -> bool:
            return True

        async def reduce(self, state: State, states: AsyncGenerator[State, None]) -> State:
            # TODO -- ensure that states is in the correct order...
            # Or decide to key it?
            new_state = state
            async for output_state in states:
                new_state = new_state.append(output_numbers_in_state=output_state["output_number"])
            return new_state

        @property
        def writes(self) -> list[str]:
            return ["output_numbers_in_state"]

        @property
        def reads(self) -> list[str]:
            return ["input_numbers_in_state"]

    app = (
        ApplicationBuilder()
        .with_actions(
            initial_action=Input("input_numbers_in_state"),
            map_action=MapStatesAsync(),
            final_action=Result("output_numbers_in_state"),
        )
        .with_transitions(("initial_action", "map_action"), ("map_action", "final_action"))
        .with_entrypoint("initial_action")
        .with_tracker(RecursiveActionTracker(events := []))
        .build()
    )
    action, result, state = await app.arun(
        halt_after=["final_action"], inputs={"input_numbers_in_state": [100, 200, 300]}
    )
    assert state["output_numbers_in_state"] == [111, 211, 311]  # ensure order correct
    assert len(events) == 3
    _, map_event, __ = events
    grouped_events = _group_events_by_app_id(map_event.children)
    assert len(grouped_events) == 3


def test_e2e_map_actions_and_states_sync():
    """Tests the map states action with a subgraph that is run in parallel.
    Collatz conjecture over different starting points"""

    class MapStatesSync(MapActionsAndStates):
        def actions(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[Union[Action, Callable, RunnableGraph], None, None]:
            for graph_ in [
                simple_single_fn_subgraph.bind(identifying_number=1000),
                ClassBasedAction(2000),
                create_full_subgraph(3000),
            ]:
                yield graph_

        def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[State, None, None]:
            for input_number in state["input_numbers_in_state"]:
                yield state.update(input_number=input_number, number_to_add=10)

        def is_async(self) -> bool:
            return False

        def reduce(self, state: State, states: Generator[State, None, None]) -> State:
            # TODO -- ensure that states is in the correct order...
            # Or decide to key it?
            new_state = state
            for output_state in states:
                new_state = new_state.append(output_numbers_in_state=output_state["output_number"])
            return new_state

        @property
        def writes(self) -> list[str]:
            return ["output_numbers_in_state"]

        @property
        def reads(self) -> list[str]:
            return ["input_numbers_in_state"]

    app = (
        ApplicationBuilder()
        .with_actions(
            initial_action=Input("input_numbers_in_state"),
            map_action=MapStatesSync(),
            final_action=Result("output_numbers_in_state"),
        )
        .with_transitions(("initial_action", "map_action"), ("map_action", "final_action"))
        .with_entrypoint("initial_action")
        .with_tracker(RecursiveActionTracker(events := []))
        .build()
    )
    action, result, state = app.run(
        halt_after=["final_action"], inputs={"input_numbers_in_state": [100, 200, 300]}
    )
    assert state["output_numbers_in_state"] == [
        1111,
        1211,
        1311,
        2111,
        2211,
        2311,
        3111,
        3211,
        3311,
    ]
    assert len(events) == 3
    _, map_event, __ = events
    grouped_events = _group_events_by_app_id(map_event.children)
    assert len(grouped_events) == 9  # cartesian product of 3 actions and 3 states


async def test_e2e_map_actions_and_states_async():
    """Tests the map states action with a subgraph that is run in parallel.
    Collatz conjecture over different starting points"""

    class MapStatesAsync(MapActionsAndStates):
        def actions(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[Union[Action, Callable, RunnableGraph], None, None]:
            for graph_ in [
                simple_single_fn_subgraph_async.bind(identifying_number=1000),
                ClassBasedActionAsync(2000),
                create_full_subgraph_async(3000),
            ]:
                yield graph_

        def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> AsyncGenerator[State, None]:
            for input_number in state["input_numbers_in_state"]:
                yield state.update(input_number=input_number, number_to_add=10)

        def is_async(self) -> bool:
            return True

        async def reduce(self, state: State, states: AsyncGenerator[State, None]) -> State:
            # TODO -- ensure that states is in the correct order...
            # Or decide to key it?
            new_state = state
            async for output_state in states:
                new_state = new_state.append(output_numbers_in_state=output_state["output_number"])
            return new_state

        @property
        def writes(self) -> list[str]:
            return ["output_numbers_in_state"]

        @property
        def reads(self) -> list[str]:
            return ["input_numbers_in_state"]

    app = (
        ApplicationBuilder()
        .with_actions(
            initial_action=Input("input_numbers_in_state"),
            map_action=MapStatesAsync(),
            final_action=Result("output_numbers_in_state"),
        )
        .with_transitions(("initial_action", "map_action"), ("map_action", "final_action"))
        .with_entrypoint("initial_action")
        .with_tracker(RecursiveActionTracker(events := []))
        .build()
    )
    action, result, state = await app.arun(
        halt_after=["final_action"], inputs={"input_numbers_in_state": [100, 200, 300]}
    )
    assert state["output_numbers_in_state"] == [
        1111,
        1211,
        1311,
        2111,
        2211,
        2311,
        3111,
        3211,
        3311,
    ]
    assert len(events) == 3
    _, map_event, __ = events
    grouped_events = _group_events_by_app_id(map_event.children)
    assert len(grouped_events) == 9  # cartesian product of 3 actions and 3 states


def test_task_level_API_e2e_sync():
    """Tests the map states action with a subgraph that is run in parallel.
    Collatz conjecture over different starting points"""

    class TaskBasedAction(TaskBasedParallelAction):
        def tasks(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[SubGraphTask, None, None]:
            for j, action in enumerate(
                [
                    simple_single_fn_subgraph.bind(identifying_number=1000),
                    ClassBasedAction(2000),
                    create_full_subgraph(3000),
                ]
            ):
                for i, input_number in enumerate(state["input_numbers_in_state"]):
                    yield SubGraphTask(
                        graph=RunnableGraph.create(action),
                        inputs={},
                        state=state.update(input_number=input_number, number_to_add=10),
                        application_id=f"{i}_{j}",
                        tracker=context.tracker.copy(),
                    )

        def reduce(self, state: State, states: Generator[State, None, None]) -> State:
            # TODO -- ensure that states is in the correct order...
            # Or decide to key it?
            new_state = state
            for output_state in states:
                new_state = new_state.append(output_numbers_in_state=output_state["output_number"])
            return new_state

        @property
        def writes(self) -> list[str]:
            return ["output_numbers_in_state"]

        @property
        def reads(self) -> list[str]:
            return ["input_numbers_in_state"]

    app = (
        ApplicationBuilder()
        .with_actions(
            initial_action=Input("input_numbers_in_state"),
            map_action=TaskBasedAction(),
            final_action=Result("output_numbers_in_state"),
        )
        .with_transitions(("initial_action", "map_action"), ("map_action", "final_action"))
        .with_entrypoint("initial_action")
        .with_tracker(RecursiveActionTracker(events := []))
        .build()
    )
    action, result, state = app.run(
        halt_after=["final_action"], inputs={"input_numbers_in_state": [100, 200, 300]}
    )
    assert state["output_numbers_in_state"] == [
        1111,
        1211,
        1311,
        2111,
        2211,
        2311,
        3111,
        3211,
        3311,
    ]
    assert len(events) == 3
    _, map_event, __ = events
    grouped_events = _group_events_by_app_id(map_event.children)
    assert len(grouped_events) == 9  # cartesian product of 3 actions and 3 states


async def test_task_level_API_e2e_async():
    """Tests the map states action with a subgraph that is run in parallel.
    Collatz conjecture over different starting points"""

    class TaskBasedActionAsync(TaskBasedParallelAction):
        async def tasks(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> AsyncGenerator[SubGraphTask, None]:
            for j, action in enumerate(
                [
                    simple_single_fn_subgraph.bind(identifying_number=1000),
                    ClassBasedAction(2000),
                    create_full_subgraph(3000),
                ]
            ):
                for i, input_number in enumerate(state["input_numbers_in_state"]):
                    yield SubGraphTask(
                        graph=RunnableGraph.create(action),
                        inputs={},
                        state=state.update(input_number=input_number, number_to_add=10),
                        application_id=f"{i}_{j}",
                        tracker=context.tracker.copy(),
                    )

        async def reduce(self, state: State, states: AsyncGenerator[State, None]) -> State:
            # TODO -- ensure that states is in the correct order...
            # Or decide to key it?
            new_state = state
            async for output_state in states:
                new_state = new_state.append(output_numbers_in_state=output_state["output_number"])
            return new_state

        @property
        def writes(self) -> list[str]:
            return ["output_numbers_in_state"]

        @property
        def reads(self) -> list[str]:
            return ["input_numbers_in_state"]

        def is_async(self) -> bool:
            return True

    app = (
        ApplicationBuilder()
        .with_actions(
            initial_action=Input("input_numbers_in_state"),
            map_action=TaskBasedActionAsync(),
            final_action=Result("output_numbers_in_state"),
        )
        .with_transitions(("initial_action", "map_action"), ("map_action", "final_action"))
        .with_entrypoint("initial_action")
        .with_tracker(RecursiveActionTracker(events := []))
        .build()
    )
    action, result, state = await app.arun(
        halt_after=["final_action"], inputs={"input_numbers_in_state": [100, 200, 300]}
    )
    assert state["output_numbers_in_state"] == [
        1111,
        1211,
        1311,
        2111,
        2211,
        2311,
        3111,
        3211,
        3311,
    ]
    assert len(events) == 3
    _, map_event, __ = events
    grouped_events = _group_events_by_app_id(map_event.children)
    assert len(grouped_events) == 9  # cartesian product of 3 actions and 3 states


def test_map_reduce_function_e2e():
    mre = map_reduce_action(
        action=[
            simple_single_fn_subgraph.bind(identifying_number=1000),
            ClassBasedAction(2000),
            create_full_subgraph(3000),
        ],
        reads=["input_numbers_in_state"],
        writes=["output_numbers_in_state"],
        state=lambda state, context, inputs: (
            state.update(input_number=input_number, number_to_add=10)
            for input_number in state["input_numbers_in_state"]
        ),
        inputs=[],
        reducer=lambda state, states: state.extend(
            output_numbers_in_state=[output_state["output_number"] for output_state in states]
        ),
    )

    app = (
        ApplicationBuilder()
        .with_actions(
            initial_action=Input("input_numbers_in_state"),
            map_action=mre,
            final_action=Result("output_numbers_in_state"),
        )
        .with_transitions(("initial_action", "map_action"), ("map_action", "final_action"))
        .with_entrypoint("initial_action")
        .with_tracker(RecursiveActionTracker(events := []))
        .build()
    )
    action, result, state = app.run(
        halt_after=["final_action"], inputs={"input_numbers_in_state": [100, 200, 300]}
    )
    assert state["output_numbers_in_state"] == [
        1111,
        1211,
        1311,
        2111,
        2211,
        2311,
        3111,
        3211,
        3311,
    ]
    assert len(events) == 3
    _, map_event, __ = events
    grouped_events = _group_events_by_app_id(map_event.children)
    assert len(grouped_events) == 9  # cartesian product of 3 actions and 3 states


class DummyTracker(SyncTrackingClient):
    def __init__(self, parent: Optional["DummyTracker"] = None):
        self.parent = parent

    def copy(self):
        return DummyTracker(parent=self)

    def post_application_create(
        self,
        *,
        app_id: str,
        partition_key: Optional[str],
        state: "State",
        application_graph: "ApplicationGraph",
        parent_pointer: Optional[burr_types.ParentPointer],
        spawning_parent_pointer: Optional[burr_types.ParentPointer],
        **future_kwargs: Any,
    ):
        pass

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
        pass

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
        pass

    def pre_start_span(
        self,
        *,
        action: str,
        action_sequence_id: int,
        span: "ActionSpan",
        span_dependencies: list[str],
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass

    def post_end_span(
        self,
        *,
        action: str,
        action_sequence_id: int,
        span: "ActionSpan",
        span_dependencies: list[str],
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass

    def do_log_attributes(
        self,
        *,
        attributes: Dict[str, Any],
        action: str,
        action_sequence_id: int,
        span: Optional["ActionSpan"],
        tags: dict,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
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


class DummyPersister(BaseStateSaver, BaseStateLoader):
    def __init__(self, parent: Optional["DummyPersister"] = None):
        self.parent = parent

    def copy(self) -> "DummyPersister":
        return DummyPersister(parent=self)

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
        self, partition_key: str, app_id: Optional[str], sequence_id: Optional[int] = None, **kwargs
    ) -> Optional[PersistedStateData]:
        pass

    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        pass


def test_cascade_adapter_cascade():
    # Tests that cascading the adapter results in a cloned adapter with `copy()` called
    adapter = DummyTracker()
    cascaded = _cascade_adapter("cascade", adapter)
    assert cascaded.parent is adapter


def test_cascade_adapter_none():
    # Tests that setting the adapter behavior to None results in no adapter
    adapter = DummyTracker()
    cascaded = _cascade_adapter(None, adapter)
    assert cascaded is None


def test_cascade_adapter_fixed():
    # Tests that setting the adapter behavior to a fixed value results in that value
    current_adapter = DummyTracker()
    next_adapter = DummyTracker()
    cascaded = _cascade_adapter(next_adapter, current_adapter)
    assert cascaded is next_adapter


def test_map_actions_and_states_uses_same_persister_as_loader():
    """This tests the MapActionsAndStates functionality of using the correct persister. Specifically
    we want it to use the same instance for the saver as it does the loader, as that is
    what the parent app does."""

    class SimpleMapStates(MapActionsAndStates):
        def actions(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[Union[Action, Callable, RunnableGraph], None, None]:
            for graph_ in [
                simple_single_fn_subgraph.bind(identifying_number=1000),
            ]:
                yield graph_

        def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[State, None, None]:
            yield state.update(input_number=0, number_to_add=0)

        def reduce(self, state: State, states: Generator[State, None, None]) -> State:
            # TODO -- ensure that states is in the correct order...
            # Or decide to key it?
            new_state = state
            for output_state in states:
                new_state = new_state.append(output_numbers_in_state=output_state["output_number"])
            return new_state

        @property
        def writes(self) -> list[str]:
            return ["output_numbers_in_state"]

        @property
        def reads(self) -> list[str]:
            return ["input_numbers_in_state"]

    action = SimpleMapStates()
    persister = DummyPersister()
    tracker = DummyTracker()

    task_generator = action.tasks(
        state=State(),
        context=ApplicationContext(
            app_id="app_id",
            partition_key="partition_key",
            sequence_id=0,
            tracker=tracker,
            state_persister=persister,
            state_initializer=persister,
            parallel_executor_factory=lambda: concurrent.futures.ThreadPoolExecutor(),
            action_name=action.name,
        ),
        inputs={},
    )
    (task,) = task_generator  # one task
    assert task.state_persister is not None
    assert task.state_initializer is not None
    assert task.tracker is not None
    assert task.state_persister is task.state_initializer  # This ensures they're the same
