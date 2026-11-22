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

"""One failing lifecycle hook must not starve the hooks registered after it.

Lifecycle dispatch runs every hook in a group and then re-raises the first failure. Previously it
aborted at the first exception, so a tracker whose ``post_run_step`` failed (full disk, a broken
serializer, ...) would silently skip the state persister registered after it and the step's state
would never be persisted.

The sync and async dispatch paths share this contract, hence the paired tests below. The string
``with_tracker("local", ...)`` configuration is the control case: it registers the persister hook
before the tracker, so it was already safe before this change.
"""

import pytest

from burr.core import ApplicationBuilder, State, action
from burr.core.artifacts import AsyncArtifactStore
from burr.core.persistence import AsyncBaseStatePersister, BaseStatePersister
from burr.lifecycle.base import PostRunStepHook
from burr.lifecycle.internal import LifecycleAdapterSet
from burr.tracking.client import AsyncLocalTrackingClient, LocalTrackingClient


class _NullAsyncStore(AsyncArtifactStore):
    """Forces the string-configured tracker to resolve to the async client."""

    async def put(self, data, key):
        return True

    async def get(self, key):
        raise KeyError(key)

    async def exists(self, key):
        return False


@action(reads=["counter"], writes=["counter"])
async def bump(state: State) -> State:
    return state.update(counter=state["counter"] + 1)


@action(reads=["counter"], writes=["counter"])
def bump_sync(state: State) -> State:
    return state.update(counter=state["counter"] + 1)


class _RecordingSyncPersister(BaseStatePersister):
    def __init__(self):
        self.saved = []

    def save(
        self, partition_key, app_id, sequence_id, position, state, status="completed", **kwargs
    ):
        self.saved.append((sequence_id, position, status))

    def list_app_ids(self, partition_key, **kwargs):
        return []

    def load(self, partition_key, app_id, sequence_id=None, **kwargs):
        return None


class _RecordingPersister(AsyncBaseStatePersister):
    def __init__(self):
        self.saved = []

    async def save(
        self,
        partition_key,
        app_id,
        sequence_id,
        position,
        state,
        status="completed",
        **kwargs,
    ):
        self.saved.append((sequence_id, position, status))

    async def list_app_ids(self, partition_key, **kwargs):
        return []

    async def load(self, partition_key, app_id, sequence_id=None, **kwargs):
        return None


@pytest.mark.asyncio
async def test_persister_still_saves_when_the_explicit_tracker_fails(tmp_path, monkeypatch):
    """An explicit async tracker's failure must not skip the async persister."""
    persister = _RecordingPersister()
    tracker = AsyncLocalTrackingClient("e1-regression", str(tmp_path))
    builder = (
        ApplicationBuilder()
        .with_actions(bump)
        .with_state(counter=0)
        .with_entrypoint("bump")
        .with_identifiers(app_id="e1-app")
        # Explicit instance: appended to lifecycle_adapters immediately, i.e. BEFORE the
        # persister hook (which is appended during abuild()). That ordering is what makes the
        # tracker run first and, without the remedy, abort the persister.
        .with_tracker(tracker)
        .with_state_persister(persister)
    )
    app = await builder.abuild()

    async def _failing_post_run_step(**kwargs):
        raise RuntimeError("tracker write failed")

    monkeypatch.setattr(tracker, "post_run_step", _failing_post_run_step)

    with pytest.raises(RuntimeError, match="tracker write failed"):
        await app.arun(halt_after=["bump"])

    assert persister.saved, "the async persister was skipped because the tracker failed"
    assert persister.saved[-1][0] == 0  # sequence_id of the single executed step
    assert app.state["counter"] == 1


@pytest.mark.asyncio
async def test_string_tracker_configuration_is_unaffected(tmp_path, monkeypatch):
    """Control case: the string configuration already ordered the persister first, so it saves."""
    persister = _RecordingPersister()
    builder = (
        ApplicationBuilder()
        .with_actions(bump)
        .with_state(counter=0)
        .with_entrypoint("bump")
        .with_identifiers(app_id="e1-string")
        .with_tracker("local", project="e1-regression", params={"storage_dir": str(tmp_path)})
        .with_object_store(_NullAsyncStore())
        .with_state_persister(persister)
    )
    app = await builder.abuild()
    tracker = app.builder.tracker

    async def _failing_post_run_step(**kwargs):
        raise RuntimeError("tracker write failed")

    monkeypatch.setattr(tracker, "post_run_step", _failing_post_run_step)

    with pytest.raises(RuntimeError, match="tracker write failed"):
        await app.arun(halt_after=["bump"])

    assert persister.saved, "string-configured persister should have saved before the tracker ran"


def test_sync_persister_still_saves_when_the_explicit_tracker_fails(tmp_path):
    """E-1 has a synchronous twin: the sync dispatch is fail-fast as well.

    This case is what distinguishes a symmetric remedy (``e1-fix-both.diff``) from an
    async-only one (``e1-fix.diff``): under the async-only fix this test still fails.
    """
    persister = _RecordingSyncPersister()
    tracker = LocalTrackingClient("e1-sync", str(tmp_path))
    builder = (
        ApplicationBuilder()
        .with_actions(bump_sync)
        .with_state(counter=0)
        .with_entrypoint("bump_sync")
        .with_identifiers(app_id="e1-sync-app")
        .with_tracker(tracker)
        .with_state_persister(persister)
    )
    app = builder.build()

    def _failing_post_run_step(**kwargs):
        raise RuntimeError("tracker write failed")

    tracker.post_run_step = _failing_post_run_step

    with pytest.raises(RuntimeError, match="tracker write failed"):
        app.run(halt_after=["bump_sync"])

    assert persister.saved, "the sync persister was skipped because the tracker failed"
    assert persister.saved[-1][0] == 0


# ---------------------------------------------------------------------------------------------
# PHASE 7-A: the synchronous phase must not abort the asynchronous phase
# ---------------------------------------------------------------------------------------------


async def test_sync_tracker_failure_does_not_starve_async_persister(tmp_path, monkeypatch):
    """A synchronous tracker's failure must not skip an asynchronous persister.

    The two hook families live in separate tables and are always dispatched sync-then-async, so
    registration order cannot fix this: the sync phase has to be non-fatal for the async phase.
    """
    persister = _RecordingPersister()
    tracker = LocalTrackingClient("mixed", str(tmp_path))
    builder = (
        ApplicationBuilder()
        .with_actions(bump)
        .with_state(counter=0)
        .with_entrypoint("bump")
        .with_identifiers(app_id="mixed-app")
        .with_tracker(tracker)  # synchronous step hooks
        .with_state_persister(persister)  # asynchronous step hooks
        .with_object_store(_NullAsyncStore())
    )
    app = await builder.abuild()

    def _failing_post_run_step(**kwargs):
        raise RuntimeError("sync tracker post failed")

    monkeypatch.setattr(tracker, "post_run_step", _failing_post_run_step)

    with pytest.raises(RuntimeError, match="sync tracker post failed"):
        await app.arun(halt_after=["bump"])

    assert persister.saved, "async persister was starved by the synchronous hook failure"
    assert persister.saved[-1][0] == 0


def _post_adapters(sync_hooks, async_hooks, async_exc=None):
    from burr.lifecycle.base import PostRunStepHook, PostRunStepHookAsync
    from burr.lifecycle.internal import LifecycleAdapterSet

    class _S(PostRunStepHook):
        def __init__(self, exc):
            self.exc = exc

        def post_run_step(self, **kwargs):
            raise self.exc

    class _A(PostRunStepHookAsync):
        def __init__(self, sink):
            self.sink = sink

        async def post_run_step(self, **kwargs):
            if async_exc is not None:
                raise async_exc
            self.sink.append("async-ran")

    return LifecycleAdapterSet(*[_S(e) for e in sync_hooks], *[_A(s) for s in async_hooks])


async def test_sync_phase_cancellation_propagates_immediately():
    """Cancellation is not an ordinary failure: it must not be deferred behind the async phase."""
    import asyncio

    sink = []
    aset = _post_adapters([asyncio.CancelledError()], [sink])
    with pytest.raises(asyncio.CancelledError):
        await aset.call_all_lifecycle_hooks_sync_and_async("post_run_step")
    assert sink == [], "async hooks must not run after a cancellation"


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
async def test_sync_phase_base_exceptions_are_not_swallowed(exc_type):
    """KeyboardInterrupt / SystemExit must propagate untouched."""
    sink = []
    aset = _post_adapters([exc_type()], [sink])
    with pytest.raises(exc_type):
        await aset.call_all_lifecycle_hooks_sync_and_async("post_run_step")
    assert sink == []


async def test_sync_failure_without_async_hooks_still_propagates():
    """With no async hook registered, the sync failure must still reach the caller."""
    aset = _post_adapters([RuntimeError("only sync")], [])
    with pytest.raises(RuntimeError, match="only sync"):
        await aset.call_all_lifecycle_hooks_sync_and_async("post_run_step")


async def test_first_failure_wins_across_phases():
    """The synchronous failure is reported even when the async phase also fails."""
    sink = []
    aset = _post_adapters(
        [RuntimeError("sync first")], [sink], async_exc=ValueError("async second")
    )
    with pytest.raises(RuntimeError, match="sync first"):
        await aset.call_all_lifecycle_hooks_sync_and_async("post_run_step")
    assert sink == [], "the async hook raised before appending"


async def test_every_synchronous_hook_runs_before_the_first_error_is_raised():
    """A failing synchronous hook must not starve the hooks registered after it.

    The asynchronous family is covered above. The synchronous family previously re-raised from
    inside the loop, so every hook after the failure was skipped -- which for a
    persister-after-tracker configuration meant the step's state was never saved. This pins the
    "run them all, then raise the first" contract for the synchronous path.
    """
    order = []

    class _Recorder(PostRunStepHook):
        def __init__(self, name, bad):
            self.name = name
            self.bad = bad

        def post_run_step(self, **kwargs):
            order.append(self.name)
            if self.bad:
                raise RuntimeError(f"boom-{self.name}")

    aset = LifecycleAdapterSet(_Recorder("a", True), _Recorder("b", False), _Recorder("c", False))
    with pytest.raises(RuntimeError, match="boom-a"):
        await aset.call_all_lifecycle_hooks_sync_and_async("post_run_step")
    assert order == ["a", "b", "c"], "later synchronous hooks must still run"
    assert order[-1] == "c", "the hook after the failure must have run"
