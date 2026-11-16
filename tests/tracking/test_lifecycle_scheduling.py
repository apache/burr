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

"""Characterisation tests for how asynchronous lifecycle hooks are scheduled.

These pin the *gathered* scheduling contract: each asynchronous hook runs in its own
``asyncio.Task`` created by ``gather``, so hooks overlap, each has its own task identity, and a
``ContextVar`` written by one hook is invisible to the others and to the caller.

That isolation is exactly why a step span cannot be published from a hook: a hook's
``context.attach()`` never reaches the task that runs the action. The alternative candidate
solves this with an optional ``action_scope`` boundary entered in the action's own task, which
keeps this contract intact. The serial candidate instead awaits hooks in the caller's task and
carries the opposite assertions.
"""

import asyncio
from contextvars import ContextVar

import pytest

from burr.lifecycle.base import PostRunStepHookAsync, PreRunStepHookAsync
from burr.lifecycle.internal import LifecycleAdapterSet


class _Recorder(PreRunStepHookAsync):
    def __init__(self, name, delay, order, tasks, seen, var):
        self.name = name
        self.delay = delay
        self.order = order
        self.tasks = tasks
        self.seen = seen
        self.var = var

    async def pre_run_step(self, **kwargs):
        self.order.append(f"{self.name}:enter")
        self.tasks.append((self.name, asyncio.current_task()))
        self.seen[self.name] = self.var.get()
        self.var.set(self.name)
        await asyncio.sleep(self.delay)
        self.order.append(f"{self.name}:exit")


async def test_async_hooks_are_dispatched_concurrently_in_their_own_tasks():
    """Hooks overlap and each runs in its own task, not the caller's.

    This is the counterpart of the serial-dispatch test: gathered dispatch keeps the original
    concurrency contract, and the trace/context problem it creates is solved by the optional
    ``action_scope`` boundary rather than by serialising the hooks.
    """
    order, tasks, seen = [], [], {}
    var = ContextVar("scheduling_probe", default="unset")
    caller = asyncio.current_task()
    # "a" sleeps longer, so under concurrent dispatch "b" enters and exits first.
    aset = LifecycleAdapterSet(
        _Recorder("a", 0.02, order, tasks, seen, var),
        _Recorder("b", 0.001, order, tasks, seen, var),
    )

    await aset.call_all_lifecycle_hooks_sync_and_async("pre_run_step")

    assert order == ["a:enter", "b:enter", "b:exit", "a:exit"], "hooks must interleave"
    assert [name for name, _ in tasks] == ["a", "b"], "registration order is preserved"
    assert all(task is not caller for _, task in tasks), "each hook runs in its own task"


async def test_hook_contextvar_writes_are_isolated():
    """Each hook sees its own Context copy; the caller is not modified.

    Keeping this isolation is precisely why the step span cannot be published from a hook, and
    why ``action_scope`` exists as a separate boundary.
    """
    order, tasks, seen = [], [], {}
    var = ContextVar("scheduling_probe", default="unset")
    aset = LifecycleAdapterSet(
        _Recorder("a", 0, order, tasks, seen, var),
        _Recorder("b", 0, order, tasks, seen, var),
    )

    await aset.call_all_lifecycle_hooks_sync_and_async("pre_run_step")

    assert seen["a"] == "unset"
    assert seen["b"] == "unset", "a hook must not observe another hook's ContextVar write"
    assert var.get() == "unset", "the caller's context is not modified by hook writes"


async def test_async_hooks_still_run_after_a_synchronous_failure():
    """The async phase is not skipped when the synchronous phase raised (see failure isolation)."""
    from burr.lifecycle.base import PostRunStepHook

    class _SyncBoom(PostRunStepHook):
        def post_run_step(self, **kwargs):
            raise RuntimeError("sync failed")

    class _AsyncRecorder(PostRunStepHookAsync):
        def __init__(self):
            self.ran = False

        async def post_run_step(self, **kwargs):
            self.ran = True

    recorder = _AsyncRecorder()
    aset = LifecycleAdapterSet(_SyncBoom(), recorder)
    with pytest.raises(RuntimeError, match="sync failed"):
        await aset.call_all_lifecycle_hooks_sync_and_async("post_run_step")
    assert recorder.ran, "the async hook must still run"
