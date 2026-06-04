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

"""End-to-end tests -- these are more like integration tests,
but they're specifically meant to be a smoke-screen. If you ever
see failures in these tests, you should make a unit test, demonstrate the failure there,
then fix both in that test and the end-to-end test."""
import asyncio
import datetime
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from typing import Any, AsyncGenerator, Dict, Generator, Literal, Optional, Tuple
from unittest.mock import patch

import pytest

from burr.core import (
    Action,
    ApplicationBuilder,
    ApplicationContext,
    GraphBuilder,
    State,
    action,
    persistence,
)
from burr.core.action import Input, Result, expr
from burr.core.parallelism import MapStates, RunnableGraph, SubgraphType
from burr.lifecycle import base


def test_end_to_end_collatz_with_function_api():
    """End-to-end test for collatz conjecture. This is a fun (unproven) finite state machine."""

    class CountHook(base.PostRunStepHook):
        def __init__(self):
            self.count = 0

        def post_run_step(self, action: "Action", **future_kwargs: Any):
            if action.name != "result":
                self.count += 1

    hook = CountHook()

    @action(reads=["n"], writes=["n", "n_history"])
    def even(state: State) -> Tuple[dict, State]:
        result = {"n": state["n"] // 2}
        return result, state.update(**result).append(n_history=result["n"])

    @action(reads=["n"], writes=["n", "n_history"])
    def odd(state: State) -> Tuple[dict, State]:
        result = {"n": 3 * state["n"] + 1}
        return result, state.update(**result).append(n_history=result["n"])

    done = expr("n == 1")
    is_even = expr("n % 2 == 0")
    is_odd = expr("n % 2 != 0")
    application = (
        ApplicationBuilder()
        .with_state(n_history=[])
        .with_actions(
            original=Input("n"),
            even=even,
            odd=odd,
            result=Result("n_history"),
        )
        .with_transitions(
            (["original", "even"], "result", done),
            (["original", "even", "odd"], "even", is_even),
            (["original", "even", "odd"], "odd", is_odd),
        )
        .with_entrypoint("original")
        .with_hooks(hook)
        .build()
    )
    run_action, result, state = application.run(halt_after=["result"], inputs={"n": 1000})
    assert result["n_history"][-1] == 1
    assert hook.count == 112


def test_end_to_end_parallel_collatz_many_unreliable_tasks(tmpdir):
    """Tests collatz conjecture search on multiple tasks.
    Each of these persists its own capabilities and state.
    This uses the in memory persister to store the state of each task.
    Each task is unreliable -- it will break every few times. We will restart
    to ensure it is eventually successful using a while loop.

    This simulates running a complex workflow in parallel.
    """

    MIN_NUMBER = 80
    MAX_NUMBER = 100
    FAILURE_ODDS = 0.05  # 1 in twenty chance of failure, will be hit but not all the time

    seen = set()

    class UnreliableFailureError(Exception):
        pass

    def _fail_at_random():
        import random

        if random.random() < FAILURE_ODDS:
            raise UnreliableFailureError("Random failure")

    # dummy as we want an initial action to decide between odd/even next
    @action(reads=["n"], writes=["n", "original_n"])
    def initial(state: State, __context: ApplicationContext) -> State:
        # This assert ensures we only visit once per app, globally
        # Thus if we're restarting this will break
        assert __context.app_id not in seen, f"App id {__context.app_id} already seen"
        seen.add(__context.app_id)
        return state.update(original_n=state["n"])

    @action(reads=["n"], writes=["n", "n_history"])
    def even(state: State) -> State:
        _fail_at_random()
        result = {"n": state["n"] // 2}
        return state.update(**result).append(n_history=result["n"])

    @action(reads=["n"], writes=["n", "n_history"])
    def odd(state: State) -> Tuple[dict, State]:
        _fail_at_random()
        result = {"n": 3 * state["n"] + 1}
        return result, state.update(**result).append(n_history=result["n"])

    collatz_graph = (
        GraphBuilder()
        .with_actions(
            initial,
            even,
            odd,
            result=Result("n_history"),
        )
        .with_transitions(
            (["initial", "even"], "result", expr("n == 1")),
            (["initial", "even", "odd"], "even", expr("n % 2 == 0")),
            (["initial", "even", "odd"], "odd", expr("n % 2 != 0")),
        )
        .build()
    )

    @action(reads=[], writes=["ns"])
    def map_step(state: State, min_number: int = MIN_NUMBER, max_number: int = MAX_NUMBER) -> State:
        return state.update(ns=list(range(min_number, max_number)))

    class ParallelCollatz(MapStates):
        def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[State, None, None]:
            for item in state["ns"]:
                yield state.update(n=item)

        def action(self, state: State, inputs: Dict[str, Any]) -> SubgraphType:
            return RunnableGraph(
                collatz_graph,
                entrypoint="initial",
                halt_after=["result"],
            )

        def reduce(self, state: State, results: Generator[State, None, None]) -> State:
            new_state = state
            count_mapping = {}
            for result in results:
                count_mapping[result["original_n"]] = len(result["n_history"])
            return new_state.update(counts=count_mapping)

        @property
        def writes(self) -> list[str]:
            return ["counts"]

        @property
        def reads(self) -> list[str]:
            return ["ns"]

    persister = persistence.InMemoryPersister()

    app_id = f"collatz_test_{str(uuid.uuid4())}"
    final_state = None
    while final_state is None:
        try:
            containing_application = (
                ApplicationBuilder()
                .with_actions(
                    map_step,
                    parallel_collatz=ParallelCollatz(),
                    final=Result("counts"),
                )
                .with_transitions(
                    ("map_step", "parallel_collatz"),
                    ("parallel_collatz", "final"),
                )
                .with_state_persister(persister)
                .with_identifiers(app_id=app_id)
                .initialize_from(
                    persister,
                    resume_at_next_action=True,
                    default_state={},
                    default_entrypoint="map_step",
                )
                # Uncomment for debugging/visualizing
                # .with_tracker("local", project="test_persister")
                .with_parallel_executor(lambda: ThreadPoolExecutor(max_workers=10))
                .build()
            )
            *_, final_state = containing_application.run(halt_after=["final"])
        except UnreliableFailureError:
            continue

        # We want to ensure that initial is called once per app
        assert len(seen) == len(range(MIN_NUMBER, MAX_NUMBER)), "Should have seen all numbers"


async def test_end_to_end_parallel_collatz_many_unreliable_tasks_async(tmpdir):
    """Tests collatz conjecture search on multiple tasks.
    Each of these persists its own capabilities and state.
    This uses the in memory persister to store the state of each task.
    Each task is unreliable -- it will break every few times. We will restart
    to ensure it is eventually successful using a while loop.

    This simulates running a complex workflow in parallel.
    """

    MIN_NUMBER = 80
    MAX_NUMBER = 100
    FAILURE_ODDS = 0.05  # 1 in twenty chance of failure, will be hit but not all the time

    seen = set()

    class UnreliableFailureError(Exception):
        pass

    def _fail_at_random():
        import random

        if random.random() < FAILURE_ODDS:
            raise UnreliableFailureError("Random failure")

    # dummy as we want an initial action to decide between odd/even next
    @action(reads=["n"], writes=["n", "original_n"])
    async def initial(state: State, __context: ApplicationContext) -> State:
        # This assert ensures we only visit once per app, globally
        # Thus if we're restarting this will break
        await asyncio.sleep(0.001)
        assert __context.app_id not in seen, f"App id {__context.app_id} already seen"
        seen.add(__context.app_id)
        return state.update(original_n=state["n"])

    @action(reads=["n"], writes=["n", "n_history"])
    async def even(state: State) -> State:
        await asyncio.sleep(0.001)
        _fail_at_random()
        result = {"n": state["n"] // 2}
        return state.update(**result).append(n_history=result["n"])

    @action(reads=["n"], writes=["n", "n_history"])
    async def odd(state: State) -> Tuple[dict, State]:
        await asyncio.sleep(0.001)
        _fail_at_random()
        result = {"n": 3 * state["n"] + 1}
        return result, state.update(**result).append(n_history=result["n"])

    collatz_graph = (
        GraphBuilder()
        .with_actions(
            initial,
            even,
            odd,
            result=Result("n_history"),
        )
        .with_transitions(
            (["initial", "even"], "result", expr("n == 1")),
            (["initial", "even", "odd"], "even", expr("n % 2 == 0")),
            (["initial", "even", "odd"], "odd", expr("n % 2 != 0")),
        )
        .build()
    )

    @action(reads=[], writes=["ns"])
    def map_step(state: State, min_number: int = MIN_NUMBER, max_number: int = MAX_NUMBER) -> State:
        return state.update(ns=list(range(min_number, max_number)))

    class ParallelCollatz(MapStates):
        async def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> AsyncGenerator[State, None]:
            for item in state["ns"]:
                yield state.update(n=item)

        def action(self, state: State, inputs: Dict[str, Any]) -> SubgraphType:
            return RunnableGraph(
                collatz_graph,
                entrypoint="initial",
                halt_after=["result"],
            )

        async def reduce(self, state: State, results: AsyncGenerator[State, None]) -> State:
            new_state = state
            count_mapping = {}
            async for result in results:
                count_mapping[result["original_n"]] = len(result["n_history"])
            return new_state.update(counts=count_mapping)

        @property
        def writes(self) -> list[str]:
            return ["counts"]

        @property
        def reads(self) -> list[str]:
            return ["ns"]

        def is_async(self) -> bool:
            return True

    persister = persistence.InMemoryPersister()
    app_id = f"collatz_test_{str(uuid.uuid4())}"
    final_state = None
    while final_state is None:
        try:
            containing_application = (
                ApplicationBuilder()
                .with_actions(
                    map_step,
                    parallel_collatz=ParallelCollatz(),
                    final=Result("counts"),
                )
                .with_transitions(
                    ("map_step", "parallel_collatz"),
                    ("parallel_collatz", "final"),
                )
                .with_state_persister(persister)
                .with_identifiers(app_id=app_id)
                .initialize_from(
                    persister,
                    resume_at_next_action=True,
                    default_state={},
                    default_entrypoint="map_step",
                )
                .build()
            )
            *_, final_state = await containing_application.arun(halt_after=["final"])
        except UnreliableFailureError:
            continue

        # We want to ensure that initial is called once per app
        assert len(seen) == len(range(MIN_NUMBER, MAX_NUMBER)), "Should have seen all numbers"


def test_echo_bot():
    @action(reads=["prompt"], writes=["response"])
    def echo(state: State) -> Tuple[dict, State]:
        return {"response": state["prompt"]}, state.update(response=state["prompt"])

    application = (
        ApplicationBuilder()
        .with_actions(
            prompt=Input("prompt"),
            response=echo,
        )
        .with_transitions(("prompt", "response"))
        .with_entrypoint("prompt")
        .build()
    )
    prompt = "hello"
    with patch("sys.stdin", new=StringIO(prompt)):
        run_action, result, state = application.run(
            halt_after=["response"], inputs={"prompt": input()}
        )

    application.visualize(
        output_file_path="digraph",
        include_conditions=True,
        view=False,
        include_state=True,
        format="png",
    )
    assert result["response"] == prompt


async def test_async_save_and_load_from_persister_end_to_end():
    await asyncio.sleep(0.00001)

    @action(reads=[], writes=["prompt", "chat_history"])
    async def dummy_input(state: State) -> Tuple[dict, State]:
        await asyncio.sleep(0.0001)
        if state["chat_history"]:
            new = state["chat_history"][-1] + 1
        else:
            new = 1
        return (
            {"prompt": "PROMPT"},
            state.update(prompt="PROMPT").append(chat_history=new),
        )

    @action(reads=["chat_history"], writes=["response", "chat_history"])
    async def dummy_response(state: State) -> Tuple[dict, State]:
        await asyncio.sleep(0.0001)
        if state["chat_history"]:
            new = state["chat_history"][-1] + 1
        else:
            new = 1
        return (
            {"response": "RESPONSE"},
            state.update(response="RESPONSE").append(chat_history=new),
        )

    class AsyncDummyPersister(persistence.AsyncBaseStatePersister):
        def __init__(self):
            self.persisted_state = None

        async def load(
            self,
            partition_key: str,
            app_id: Optional[str],
            sequence_id: Optional[int] = None,
            **kwargs,
        ) -> Optional[persistence.PersistedStateData]:
            await asyncio.sleep(0.0001)
            return self.persisted_state

        async def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
            return []

        async def save(
            self,
            partition_key: Optional[str],
            app_id: str,
            sequence_id: int,
            position: str,
            state: State,
            status: Literal["completed", "failed"],
            **kwargs,
        ):
            await asyncio.sleep(0.0001)
            self.persisted_state: persistence.PersistedStateData = {
                "partition_key": partition_key or "",
                "app_id": app_id,
                "sequence_id": sequence_id,
                "position": position,
                "state": state,
                "created_at": datetime.datetime.now().isoformat(),
                "status": status,
            }

    dummy_persister = AsyncDummyPersister()
    app = await (
        ApplicationBuilder()
        .with_actions(dummy_input, dummy_response)
        .with_transitions(("dummy_input", "dummy_response"), ("dummy_response", "dummy_input"))
        .initialize_from(
            initializer=dummy_persister,
            resume_at_next_action=True,
            default_state={"chat_history": []},
            default_entrypoint="dummy_input",
        )
        .with_state_persister(dummy_persister)
        .abuild()
    )

    *_, state = await app.arun(halt_after=["dummy_response"])

    assert state["chat_history"][0] == 1
    assert state["chat_history"][1] == 2
    del app

    new_app = await (
        ApplicationBuilder()
        .with_actions(dummy_input, dummy_response)
        .with_transitions(("dummy_input", "dummy_response"), ("dummy_response", "dummy_input"))
        .initialize_from(
            initializer=dummy_persister,
            resume_at_next_action=True,
            default_state={"chat_history": []},
            default_entrypoint="dummy_input",
        )
        .with_state_persister(dummy_persister)
        .abuild()
    )

    assert new_app.state["chat_history"][0] == 1
    assert new_app.state["chat_history"][1] == 2

    *_, state = await new_app.arun(halt_after=["dummy_response"])
    assert state["chat_history"][2] == 3
    assert state["chat_history"][3] == 4

    with pytest.raises(ValueError, match="The application was build with .abuild()"):
        *_, state = new_app.run(halt_after=["dummy_response"])
