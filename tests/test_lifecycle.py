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

from burr.core import ApplicationBuilder, State, action
from burr.lifecycle import InMemoryExecutionRecorder, StateChange


@action(reads=["count"], writes=["count"])
def increment(state: State, amount: int = 1) -> State:
    return state.update(count=state.get("count", 0) + amount)


@action(reads=[], writes=[])
def fail(state: State) -> State:
    raise RuntimeError("tool failed")


@action(reads=[], writes=["nullable"])
def add_nullable(state: State) -> State:
    return state.update(nullable=None)


@action(reads=["count"], writes=["count"])
async def increment_async(state: State) -> State:
    return state.update(count=state.get("count", 0) + 1)


def test_in_memory_execution_recorder_captures_step_changes():
    recorder = InMemoryExecutionRecorder()
    app = (
        ApplicationBuilder()
        .with_actions(increment)
        .with_entrypoint("increment")
        .with_state(count=1)
        .with_identifiers(app_id="agent-run", partition_key="user-1")
        .with_hooks(recorder)
        .build()
    )

    app.step(inputs={"amount": 2})

    assert len(recorder.records) == 1
    record = recorder.records[0]
    assert record.app_id == "agent-run"
    assert record.partition_key == "user-1"
    assert record.sequence_id == 0
    assert record.action == "increment"
    assert record.inputs == {"amount": 2}
    assert record.result == {}
    assert record.exception is None
    assert record.state_changes == (
        StateChange(
            key="count",
            before_exists=True,
            before=1,
            after_exists=True,
            after=3,
        ),
    )


def test_in_memory_execution_recorder_captures_failed_step():
    recorder = InMemoryExecutionRecorder()
    app = (
        ApplicationBuilder().with_actions(fail).with_entrypoint("fail").with_hooks(recorder).build()
    )

    with pytest.raises(RuntimeError, match="tool failed"):
        app.step()

    assert len(recorder.records) == 1
    record = recorder.records[0]
    assert record.action == "fail"
    assert record.result is None
    assert isinstance(record.exception, RuntimeError)
    assert record.state_changes == ()


def test_in_memory_execution_recorder_clear_removes_records():
    recorder = InMemoryExecutionRecorder()
    app = (
        ApplicationBuilder()
        .with_actions(increment)
        .with_entrypoint("increment")
        .with_hooks(recorder)
        .build()
    )
    app.step()

    recorder.clear()

    assert recorder.records == ()


def test_in_memory_execution_recorder_distinguishes_missing_from_none():
    recorder = InMemoryExecutionRecorder()
    app = (
        ApplicationBuilder()
        .with_actions(add_nullable)
        .with_entrypoint("add_nullable")
        .with_hooks(recorder)
        .build()
    )

    app.step()

    assert recorder.records[0].state_changes == (
        StateChange(
            key="nullable",
            before_exists=False,
            before=None,
            after_exists=True,
            after=None,
        ),
    )


async def test_in_memory_execution_recorder_captures_async_steps():
    recorder = InMemoryExecutionRecorder()
    app = (
        ApplicationBuilder()
        .with_actions(increment_async)
        .with_entrypoint("increment_async")
        .with_hooks(recorder)
        .with_state(count=0)
        .build()
    )

    await app.astep()

    assert recorder.records[0].action == "increment_async"
    assert recorder.records[0].state_changes[0].after == 1


def test_in_memory_execution_recorder_handles_non_boolean_equality():
    class VectorLike:
        def __deepcopy__(self, memo):
            return self

        def __eq__(self, other):
            return self

        def __bool__(self):
            raise ValueError("truth value is ambiguous")

    recorder = InMemoryExecutionRecorder()
    app = (
        ApplicationBuilder()
        .with_actions(increment)
        .with_entrypoint("increment")
        .with_state(count=0, embeddings=VectorLike())
        .with_hooks(recorder)
        .build()
    )

    app.step()

    assert [change.key for change in recorder.records[0].state_changes] == ["count"]


def test_in_memory_execution_recorder_does_not_block_uncopyable_state():
    class Uncopyable:
        def __deepcopy__(self, memo):
            raise TypeError("cannot copy runtime handle")

    recorder = InMemoryExecutionRecorder()
    app = (
        ApplicationBuilder()
        .with_actions(increment)
        .with_entrypoint("increment")
        .with_state(count=0, handle=Uncopyable())
        .with_hooks(recorder)
        .build()
    )

    action_, result, state = app.step()

    assert action_.name == "increment"
    assert result == {}
    assert state["count"] == 1
    assert [change.key for change in recorder.records[0].state_changes] == ["count"]
