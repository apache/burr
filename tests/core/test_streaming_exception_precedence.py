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

"""Streaming lifecycle: exception ownership and precedence.

Two independent defects are pinned here:

1. ``__iter__`` / ``__aiter__`` used ``sys.exc_info()[1]`` in their ``finally`` to decide what
   error to report for the step. ``sys.exc_info()`` is thread state, so an exception the *caller*
   happens to be handling was reported as the step's failure. A successful streaming step was
   then persisted as ``failed`` and, on resume, executed a second time.

2. ``post_run_step`` is dispatched from the container's ``finally``. When the action had already
   failed, a hook raising a plain ``Exception`` replaced the action's exception, and the remaining
   lifecycle callbacks (``post_end_stream``, execute-method post) never ran.

These tests keep #1027's contract intact: early stop reports ``GeneratorExit`` / cancellation,
cleanup errors win on ``close()``/``aclose()``, and repeated close raises the same error.
"""

import asyncio
import json
import sqlite3
from typing import List, Optional

import pytest

from burr.core import ApplicationBuilder, State, action
from burr.core.action import streaming_action
from burr.core.persistence import InMemoryPersister, SQLitePersister
from burr.lifecycle.base import (
    PostEndStreamHook,
    PostRunStepHook,
    PostRunStepHookAsync,
    PreStartStreamHook,
)


class ActionError(Exception):
    pass


class ActionBase(BaseException):
    pass


class HookError(Exception):
    pass


class HookBase(BaseException):
    pass


class CleanupError(Exception):
    pass


# ------------------------------------------------------------------ instrumentation
class RecordingPersister(InMemoryPersister):
    def __init__(self) -> None:
        super().__init__()
        self.statuses: List[str] = []

    def save(self, partition_key, app_id, sequence_id, action_name, state, status):
        self.statuses.append(status)
        return super().save(partition_key, app_id, sequence_id, action_name, state, status)


class Spy(PostRunStepHook, PostEndStreamHook, PreStartStreamHook):
    """Records lifecycle events; optionally raises from post_run_step."""

    def __init__(self, raises: Optional[BaseException] = None) -> None:
        self.raises = raises
        self.events: List[str] = []
        self.exceptions: List[Optional[str]] = []

    def pre_start_stream(self, **kwargs):
        self.events.append("pre_start_stream")

    def post_run_step(self, *, exception=None, **kwargs):
        self.events.append("post_run_step")
        self.exceptions.append(type(exception).__name__ if exception is not None else None)
        if self.raises is not None:
            raise self.raises

    def post_end_stream(self, **kwargs):
        self.events.append("post_end_stream")


class SpyAsync(PostRunStepHookAsync):
    def __init__(self, raises: Optional[BaseException] = None) -> None:
        self.raises = raises
        self.events: List[str] = []
        self.exceptions: List[Optional[str]] = []

    async def post_run_step(self, *, exception=None, **kwargs):
        self.events.append("post_run_step")
        self.exceptions.append(type(exception).__name__ if exception is not None else None)
        if self.raises is not None:
            raise self.raises


# ------------------------------------------------------------------ action factories
def sync_stream(kind: str = "ok", cleanup_log: Optional[List[str]] = None):
    @streaming_action(reads=[], writes=["x"])
    def act(state: State):
        try:
            yield {"chunk": 0}, None
            yield {"chunk": 1}, None
            if kind == "fail":
                raise ActionError("action exploded")
            if kind == "fail_base":
                raise ActionBase("action control flow")
            yield {"chunk": "final"}, state.update(x=1)
        finally:
            if cleanup_log is not None:
                cleanup_log.append("sync")
            if kind == "cleanup_fail":
                raise CleanupError("cleanup exploded")

    return act


def async_stream(kind: str = "ok", cleanup_log: Optional[List[str]] = None):
    @streaming_action(reads=[], writes=["x"])
    async def act(state: State):
        try:
            yield {"chunk": 0}, None
            await asyncio.sleep(0)
            yield {"chunk": 1}, None
            if kind == "fail":
                raise ActionError("action exploded")
            if kind == "fail_base":
                raise ActionBase("action control flow")
            yield {"chunk": "final"}, state.update(x=1)
        finally:
            if cleanup_log is not None:
                cleanup_log.append("async")
            if kind == "cleanup_fail":
                raise CleanupError("cleanup exploded")

    return act


def build(act, hooks=(), persister=None):
    builder = ApplicationBuilder().with_actions(a=act).with_entrypoint("a")
    if hooks:
        builder = builder.with_hooks(*hooks)
    if persister is not None:
        builder = builder.with_state_persister(persister)
    return builder.build()


# ------------------------------------------------------------------ 1. caller exception isolation
@pytest.mark.parametrize("method", ["get", "iterate"])
def test_caller_exception_is_not_reported_as_a_step_failure_sync(method):
    spy = Spy()
    persister = RecordingPersister()
    app = build(sync_stream(), hooks=[spy], persister=persister)

    try:
        raise ValueError("the caller's own error")
    except ValueError:
        _, container = app.stream_result(halt_after=["a"])
        if method == "get":
            container.get()
        else:
            for _ in container:
                pass

    assert spy.exceptions == [None], "the caller's exception was attributed to the step"
    assert persister.statuses == ["completed"], "a successful step was persisted as failed"
    assert app.state["x"] == 1


@pytest.mark.parametrize("method", ["get", "iterate"])
def test_caller_exception_is_not_reported_as_a_step_failure_async(method):
    spy = SpyAsync()
    persister = RecordingPersister()
    app = build(async_stream(), hooks=[spy], persister=persister)

    async def consume():
        _, container = await app.astream_result(halt_after=["a"])
        if method == "get":
            await container.get()
        else:
            async for _ in container:
                pass

    try:
        raise ValueError("the caller's own error")
    except ValueError:
        asyncio.run(consume())

    assert spy.exceptions == [None]
    assert persister.statuses == ["completed"]
    assert app.state["x"] == 1


def test_caller_exception_does_not_poison_the_local_tracker(tmp_path):
    from burr.tracking import LocalTrackingClient

    tracker = LocalTrackingClient(project="probe", storage_dir=str(tmp_path))
    app = (
        ApplicationBuilder()
        .with_actions(a=sync_stream())
        .with_entrypoint("a")
        .with_tracker(tracker)
        .with_identifiers(app_id="app", partition_key="pk")
        .build()
    )
    try:
        raise ValueError("the caller's own error")
    except ValueError:
        _, container = app.stream_result(halt_after=["a"])
        container.get()

    log = tmp_path / "probe" / "app" / "log.jsonl"
    end_entries = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("type") == "end_entry"
    ]
    assert end_entries, "the tracker did not record the step"
    assert end_entries[-1]["exception"] is None, "the tracker recorded the caller's error"


def test_caller_exception_does_not_duplicate_work_on_resume(tmp_path):
    """A successful step recorded as failed makes resume re-run it: pin that this cannot happen."""
    db_path = str(tmp_path / "state.sqlite")
    persister = SQLitePersister.from_values(db_path=db_path, table_name="burr_state")
    persister.initialize()
    charges = []

    @streaming_action(reads=[], writes=["count"])
    def charge(state: State):
        charges.append("charge")
        yield {"chunk": 0}, None
        yield {"chunk": "final"}, state.update(count=state.get("count", 0) + 1)

    @action(reads=["count"], writes=[])
    def done(state: State) -> State:
        charges.append("done")
        return state

    def builder():
        return (
            ApplicationBuilder()
            .with_actions(charge=charge, done=done)
            .with_transitions(("charge", "done"))
            .with_identifiers(app_id="app", partition_key="pk")
            .initialize_from(
                persister,
                resume_at_next_action=True,
                default_state={"count": 0},
                default_entrypoint="charge",
            )
            .with_state_persister(persister)
            .build()
        )

    app = builder()
    try:
        raise ValueError("the caller's own error")
    except ValueError:
        _, container = app.stream_result(halt_after=["charge"])
        container.get()

    con = sqlite3.connect(db_path)
    try:
        statuses = [r[0] for r in con.execute("select status from burr_state").fetchall()]
    finally:
        con.close()
    assert statuses == ["completed"], f"first step stored as {statuses}"

    charges.clear()
    resumed = builder()
    assert resumed.get_next_action().name == "done", "resume re-runs the completed step"
    resumed.step()
    assert charges == ["done"], f"side effect repeated: {charges}"
    assert resumed.state["count"] == 1


# ------------------------------------------------------------------ 2. exception precedence
@pytest.mark.parametrize(
    "act_kind,expected",
    [("fail", ActionError), ("fail_base", ActionBase)],
)
def test_action_error_wins_over_hook_exception_sync(act_kind, expected):
    spy = Spy(raises=HookError("hook exploded"))
    app = build(sync_stream(act_kind), hooks=[spy])
    _, container = app.stream_result(halt_after=["a"])
    with pytest.raises(expected):
        container.get()
    assert spy.exceptions == [expected.__name__]
    assert "post_end_stream" in spy.events, "a failing hook stopped the rest of the lifecycle"


@pytest.mark.parametrize(
    "act_kind,expected",
    [("fail", ActionError), ("fail_base", ActionBase)],
)
def test_action_error_wins_over_hook_exception_async(act_kind, expected):
    spy = SpyAsync(raises=HookError("hook exploded"))
    app = build(async_stream(act_kind), hooks=[spy])

    async def consume():
        _, container = await app.astream_result(halt_after=["a"])
        await container.get()

    with pytest.raises(expected):
        asyncio.run(consume())
    assert spy.exceptions == [expected.__name__]


@pytest.mark.parametrize("is_async", [False, True])
def test_hook_base_exception_still_propagates(is_async):
    """A control-flow exception raised by a hook must not be swallowed."""
    spy = SpyAsync(raises=HookBase()) if is_async else Spy(raises=HookBase())
    app = build(async_stream("fail") if is_async else sync_stream("fail"), hooks=[spy])

    if is_async:

        async def consume():
            _, container = await app.astream_result(halt_after=["a"])
            await container.get()

        with pytest.raises(HookBase):
            asyncio.run(consume())
    else:
        _, container = app.stream_result(halt_after=["a"])
        with pytest.raises(HookBase):
            container.get()


@pytest.mark.parametrize("is_async", [False, True])
def test_hook_error_on_a_successful_step_still_propagates(is_async):
    spy = SpyAsync(raises=HookError("hook exploded")) if is_async else Spy(raises=HookError())
    app = build(async_stream() if is_async else sync_stream(), hooks=[spy])

    async def consume_async():
        _, container = await app.astream_result(halt_after=["a"])
        await container.get()

    if is_async:
        with pytest.raises(HookError):
            asyncio.run(consume_async())
    else:
        _, container = app.stream_result(halt_after=["a"])
        with pytest.raises(HookError):
            container.get()
    assert app.state["x"] == 1


def test_post_end_stream_runs_when_post_run_step_fails():
    spy = Spy(raises=HookError("hook exploded"))
    app = build(sync_stream(), hooks=[spy])
    _, container = app.stream_result(halt_after=["a"])
    with pytest.raises(HookError):
        container.get()
    assert spy.events == ["pre_start_stream", "post_run_step", "post_end_stream"]


# ------------------------------------------------------------------ 3. #1027 contract preserved
def test_break_reports_generator_exit_and_failed_status():
    spy = Spy()
    persister = RecordingPersister()
    app = build(sync_stream(), hooks=[spy], persister=persister)
    _, container = app.stream_result(halt_after=["a"])
    for _ in container:
        break
    assert spy.exceptions == ["GeneratorExit"]
    assert persister.statuses == ["failed"]
    assert app.state.get("x") is None


def test_close_reports_cleanup_error_and_repeats_it():
    cleanup = []
    spy = Spy()
    app = build(sync_stream("cleanup_fail", cleanup), hooks=[spy])
    _, container = app.stream_result(halt_after=["a"])
    for _ in container:
        break
    errors = []
    for _ in range(2):
        with pytest.raises(CleanupError):
            container.close()
        errors.append("CleanupError")
    assert errors == ["CleanupError", "CleanupError"]
    assert spy.exceptions == ["CleanupError"], "cleanup error must win over the step report"
    assert cleanup == ["sync"], "cleanup must run exactly once"


def test_cleanup_error_wins_over_a_failing_hook_on_close():
    """#1027's rule: when the cleanup itself fails, its error is the one that surfaces -- even
    if a post_run_step hook also fails."""
    cleanup = []
    spy = Spy(raises=HookError("hook exploded"))
    app = build(sync_stream("cleanup_fail", cleanup), hooks=[spy])
    _, container = app.stream_result(halt_after=["a"])
    for _ in container:
        break
    for _ in range(2):
        with pytest.raises(CleanupError):
            container.close()
    assert cleanup == ["sync"]


def test_close_without_cleanup_error_is_idempotent():
    cleanup = []
    app = build(sync_stream("ok", cleanup))
    _, container = app.stream_result(halt_after=["a"])
    for _ in container:
        break
    container.close()
    container.close()
    assert cleanup == ["sync"]


def test_cancel_scope_reports_cancellation_as_failed(caplog):
    import anyio

    spy = SpyAsync()
    persister = RecordingPersister()
    app = build(async_stream(), hooks=[spy], persister=persister)

    async def consume():
        _, container = await app.astream_result(halt_after=["a"])
        with anyio.CancelScope() as scope:
            async for _ in container:
                scope.cancel()
                break

    asyncio.run(consume())
    assert spy.exceptions and spy.exceptions[0] in ("CancelledError", "GeneratorExit")
    assert persister.statuses == ["failed"], "a cancelled step must not be recorded as completed"
    assert app.state.get("x") is None


# ------------------------------------------------------------------ 4. other consumption paths
@pytest.mark.parametrize("is_async", [False, True])
def test_stream_iterate_marks_every_step_completed_under_a_caller_exception(is_async):
    """stream_iterate/astream_iterate wrap stream_result: each step gets its own container, so
    the caller's exception used to be attributed to *every* step."""

    @streaming_action(reads=[], writes=["a"])
    async def first_a(state: State):
        yield {"chunk": 0}, None
        yield {"chunk": "f"}, state.update(a=1)

    @streaming_action(reads=[], writes=["a"])
    def first_s(state: State):
        yield {"chunk": 0}, None
        yield {"chunk": "f"}, state.update(a=1)

    @streaming_action(reads=["a"], writes=["b"])
    async def second_a(state: State):
        yield {"chunk": 0}, None
        yield {"chunk": "s"}, state.update(b=2)

    @streaming_action(reads=["a"], writes=["b"])
    def second_s(state: State):
        yield {"chunk": 0}, None
        yield {"chunk": "s"}, state.update(b=2)

    hook = SpyAsync() if is_async else Spy()
    persister = RecordingPersister()
    first, second = (first_a, second_a) if is_async else (first_s, second_s)
    app = (
        ApplicationBuilder()
        .with_actions(first=first, second=second)
        .with_transitions(("first", "second"))
        .with_entrypoint("first")
        .with_hooks(hook)
        .with_state_persister(persister)
        .build()
    )

    if is_async:

        async def run():
            async for _action, container in app.astream_iterate(halt_after=["second"]):
                await container.get()

        try:
            raise ValueError("the caller's own error")
        except ValueError:
            asyncio.run(run())
    else:
        try:
            raise ValueError("the caller's own error")
        except ValueError:
            for _action, container in app.stream_iterate(halt_after=["second"]):
                container.get()

    assert hook.exceptions == [None, None], f"steps were reported as {hook.exceptions}"
    assert persister.statuses == ["completed", "completed"]
    assert app.state["a"] == 1 and app.state["b"] == 2


def test_get_after_break_still_reports_generator_exit_with_a_caller_exception():
    """Draining a broken stream is still an early stop, not a success."""
    spy = Spy()
    persister = RecordingPersister()
    app = build(sync_stream(), hooks=[spy], persister=persister)
    try:
        raise ValueError("the caller's own error")
    except ValueError:
        _, container = app.stream_result(halt_after=["a"])
        for _ in container:
            break
        container.get()
    assert spy.exceptions == ["GeneratorExit"]
    assert persister.statuses == ["failed"]


def test_callback_runs_once_when_get_is_called_twice():
    spy = Spy()
    persister = RecordingPersister()
    app = build(sync_stream(), hooks=[spy], persister=persister)
    try:
        raise ValueError("the caller's own error")
    except ValueError:
        _, container = app.stream_result(halt_after=["a"])
        container.get()
        container.get()
    assert spy.exceptions == [None], "the post-step callback ran more than once"
    assert persister.statuses == ["completed"]
