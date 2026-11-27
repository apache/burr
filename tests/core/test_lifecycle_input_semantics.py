# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# under the Apache License, Version 2.0 (the
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
"""Lifecycle/input semantics must be the same on every execution entry point.

Covers #979 (``pre_run_step`` handed the raw dict) and #1007 (inputs processed twice) for
``step``, ``astep``, ``stream_result``, ``astream_result`` and the two streaming-iterate
wrappers, over sync/async/streaming actions, sync and async hooks, and tracking on/off.

Observables, deliberately:

  * ``_process_inputs`` call count per action execution.
  * ``pre_run_step`` / ``post_run_step`` counts, and the order they and ``_process_inputs``
    happen in.
  * object identity between the ``__context`` the hook receives and the one the action
    receives. ``Application._context_factory`` returns a new ``ApplicationContext`` per
    call, so identity is a direct public-API probe for "were the inputs built once?" --
    it does not reach into ``_dependency_factory`` or any other private attribute.
  * exception type and message.

Nothing asserts on returned values: equal results are compatible with double processing.
"""

import tempfile
import uuid
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

from burr.core import ApplicationBuilder, State, action
from burr.core.action import streaming_action
from burr.core.application import Application, ApplicationContext
from burr.lifecycle.base import (
    PostEndStreamHook,
    PostRunStepHook,
    PostRunStepHookAsync,
    PreRunStepHook,
    PreRunStepHookAsync,
    PreStartStreamHook,
)
from burr.tracking.client import LocalTrackingClient

ACTION_CTX: List[Any] = []


@action(reads=[], writes=["value"])
def plain_sync(state: State, value: int, __context: ApplicationContext) -> State:
    ACTION_CTX.append(__context)
    return state.update(value=value)


@action(reads=[], writes=["value"])
async def plain_async(state: State, value: int, __context: ApplicationContext) -> State:
    ACTION_CTX.append(__context)
    return state.update(value=value)


@action(reads=[], writes=["value"])
def boom_sync(state: State, value: int, __context: ApplicationContext) -> State:
    ACTION_CTX.append(__context)
    raise ValueError("action exploded")


@action(reads=[], writes=["value"])
async def boom_async(state: State, value: int, __context: ApplicationContext) -> State:
    ACTION_CTX.append(__context)
    raise ValueError("action exploded")


# A single-step streaming action yields (result, Optional[State]) pairs.
@streaming_action(reads=[], writes=["value", "tokens"])
def stream_sync(state: State, value: int, __context: ApplicationContext):
    ACTION_CTX.append(__context)
    yield {"tokens": 1}, None
    yield {"tokens": 2}, state.update(value=value, tokens=2)


@streaming_action(reads=[], writes=["value", "tokens"])
async def stream_async(state: State, value: int, __context: ApplicationContext):
    ACTION_CTX.append(__context)
    yield {"tokens": 1}, None
    yield {"tokens": 2}, state.update(value=value, tokens=2)


ENTRIES = ["step", "astep", "stream_result", "astream_result", "stream_iterate", "astream_iterate"]
# The synchronous entry points dispatch sync hooks only (call_all_lifecycle_hooks_sync),
# so an async-only hook legitimately never fires there.
SYNC_ONLY_ENTRIES = {"step", "stream_result", "stream_iterate"}
GOOD = {"value": 1, "noise": 2}
SYNC_ACTS = {"plain": plain_sync, "boom": boom_sync, "stream": stream_sync}
ASYNC_ACTS = {"plain": plain_async, "boom": boom_async, "stream": stream_async}


class Hooks(PreRunStepHook, PostRunStepHook, PreStartStreamHook, PostEndStreamHook):
    def __init__(self, bag: Dict[str, Any]):
        self.bag = bag

    def pre_run_step(self, *, inputs, **kw):
        self.bag["order"].append("pre_run_step")
        self.bag["pre_inputs"].append(dict(inputs))

    def post_run_step(self, *, exception, **kw):
        self.bag["order"].append("post_run_step")
        self.bag["post_exc"].append(type(exception).__name__)

    def pre_start_stream(self, **kw):
        self.bag["order"].append("pre_start_stream")

    def post_end_stream(self, **kw):
        self.bag["order"].append("post_end_stream")


class AsyncHooks(PreRunStepHookAsync, PostRunStepHookAsync):
    def __init__(self, bag: Dict[str, Any]):
        self.bag = bag

    async def pre_run_step(self, *, inputs, **kw):
        self.bag["order"].append("pre_run_step")
        self.bag["pre_inputs"].append(dict(inputs))

    async def post_run_step(self, *, exception, **kw):
        self.bag["order"].append("post_run_step")


def blank_bag() -> Dict[str, Any]:
    return {"pre_inputs": [], "post_exc": [], "order": []}


async def drive(
    entry: str,
    flavor: str,
    inputs: Dict[str, Any],
    *,
    async_hooks: bool = False,
    tracked: bool = False,
):
    fn = (ASYNC_ACTS if entry.startswith("a") else SYNC_ACTS)[flavor]
    bag = blank_bag()
    hooks: List[Any] = [AsyncHooks(bag) if async_hooks else Hooks(bag)]
    tracker = (
        LocalTrackingClient(project="semantics", storage_dir=tempfile.mkdtemp())
        if tracked
        else None
    )
    if tracker is not None:
        hooks.append(tracker)
    name = fn.__name__
    app = (
        ApplicationBuilder()
        .with_actions(fn)
        .with_entrypoint(name)
        .with_identifiers(app_id=str(uuid.uuid4()))
        .with_hooks(*hooks)
        .build()
    )
    ACTION_CTX.clear()
    order: List[str] = []
    calls: List[str] = []
    real_process = Application._process_inputs

    def counted(this, raw_inputs, target_action):
        order.append("process_inputs")
        calls.append(target_action.name)
        return real_process(this, raw_inputs, target_action)

    err: Optional[BaseException] = None
    with mock.patch.object(Application, "_process_inputs", autospec=True, side_effect=counted):
        try:
            if entry == "step":
                app.step(inputs=inputs)
            elif entry == "astep":
                await app.astep(inputs=inputs)
            elif entry == "stream_result":
                _, container = app.stream_result(halt_after=[name], inputs=inputs)
                list(container)
            elif entry == "astream_result":
                _, container = await app.astream_result(halt_after=[name], inputs=inputs)
                _ = [r async for r in container]
                await container.get()
            elif entry == "stream_iterate":
                for _action, container in app.stream_iterate(halt_after=[name], inputs=inputs):
                    list(container)
            else:
                async for _action, container in app.astream_iterate(
                    halt_after=[name], inputs=inputs
                ):
                    _ = [r async for r in container]
                    await container.get()
        except Exception as caught:  # noqa: BLE001
            err = caught
    return {
        "bag": bag,
        "calls": calls,
        "err": err,
        "action_ctx": ACTION_CTX[0] if ACTION_CTX else None,
        "order": order + bag["order"],
        "stream_state": tracker.stream_state if tracker is not None else {},
        "name": name,
    }


# ------------------------------------------------------ one processing, hooks paired once
@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("flavor", ["plain", "stream", "boom"])
async def test_inputs_processed_once_and_step_announced_once(entry, flavor):
    out = await drive(entry, flavor, GOOD)
    if flavor == "stream" and entry in ("step", "astep"):
        pytest.skip("driving a streaming action as a plain step is a separate concern")
    assert out["calls"] == [out["name"]], f"{entry}/{flavor}: processed {out['calls']}"
    pre = out["order"].count("pre_run_step")
    post = out["order"].count("post_run_step")
    assert pre == post == 1, f"{entry}/{flavor}: pre={pre} post={post}"


@pytest.mark.parametrize("entry", ENTRIES)
async def test_sync_action_through_async_entry_is_not_processed_twice(entry):
    out = await drive(entry, "plain", GOOD)
    assert out["err"] is None, out["err"]
    assert out["calls"] == [out["name"]], f"{entry}: processed {out['calls']}"


# ------------------------------------------------------ hook and action share one dict
@pytest.mark.parametrize(
    "flavor", ["plain", "stream"], ids=["non_streaming_action", "streaming_action"]
)
@pytest.mark.parametrize("async_hooks", [False, True], ids=["sync_hooks", "async_hooks"])
@pytest.mark.parametrize("entry", ENTRIES)
async def test_hook_and_action_receive_the_same_injected_object(entry, async_hooks, flavor):
    if async_hooks and entry in SYNC_ONLY_ENTRIES:
        pytest.skip("sync entries dispatch sync hooks only")
    out = await drive(entry, flavor, GOOD, async_hooks=async_hooks)
    assert out["err"] is None, out["err"]
    assert out["bag"]["pre_inputs"], f"{entry}: pre_run_step never fired"
    seen = out["bag"]["pre_inputs"][0]
    assert "__context" in seen, (
        f"{entry}: hook got {sorted(seen)} -- the injected dependency is missing, so the hook "
        "cannot be observing what the action observes"
    )
    assert seen["__context"] is out["action_ctx"], f"{entry}: hook/action identity mismatch"


# ------------------------------------------------------ invalid input announces nothing
@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize(
    "bad", [{"__reserved": 1, "value": 1}, {}], ids=["reserved_key", "missing_required"]
)
async def test_invalid_input_is_rejected_before_any_step_is_announced(entry, bad):
    out = await drive(entry, "plain", bad, tracked=True)
    assert isinstance(out["err"], ValueError), f"{entry}: got {type(out['err']).__name__}"
    assert "pre_run_step" not in out["order"], f"{entry}: step announced before validation"
    assert "post_run_step" not in out["order"], f"{entry}: step closed without ever opening"
    assert not out["stream_state"], f"{entry}: stream_state left open: {list(out['stream_state'])}"


# ------------------------------------------------------ processing precedes the hook
@pytest.mark.parametrize("entry", ENTRIES)
async def test_inputs_are_processed_before_the_step_is_announced(entry):
    out = await drive(entry, "plain", GOOD)
    assert out["err"] is None, out["err"]
    assert out["order"].index("process_inputs") < out["order"].index("pre_run_step"), out["order"]


# ------------------------------------------------------ action errors keep their identity
@pytest.mark.parametrize("entry", ENTRIES)
async def test_action_exception_type_message_and_records_survive(entry):
    out = await drive(entry, "boom", GOOD, tracked=True)
    assert isinstance(out["err"], ValueError), f"{entry}: {type(out['err']).__name__}"
    assert "action exploded" in str(out["err"]), f"{entry}: message lost"
    assert out["bag"]["post_exc"] == [
        "ValueError"
    ], f"{entry}: post_run_step saw {out['bag']['post_exc']}"
    assert not out["stream_state"], f"{entry}: stream_state left open: {list(out['stream_state'])}"


# ------------------------------------------------------ streaming lifecycle intact
@pytest.mark.parametrize("entry", ENTRIES)
async def test_stream_lifecycle_pairs_and_cleans_up(entry):
    out = await drive(entry, "stream", GOOD, tracked=True)
    if entry in ("step", "astep"):
        pytest.skip("not a streaming path")
    assert out["err"] is None, out["err"]
    assert out["order"].count("pre_start_stream") == out["order"].count("post_end_stream"), out[
        "order"
    ]
    assert not out["stream_state"], f"{entry}: stream_state left open: {list(out['stream_state'])}"


async def test_valid_step_is_still_recorded_by_the_tracker():
    """The tightening must not silence tracking for steps that actually run."""
    from pathlib import Path

    storage = tempfile.mkdtemp()
    tracker = LocalTrackingClient(project="recorded", storage_dir=storage)
    app = (
        ApplicationBuilder()
        .with_actions(plain_sync)
        .with_entrypoint("plain_sync")
        .with_identifiers(app_id=str(uuid.uuid4()))
        .with_hooks(tracker)
        .build()
    )
    _, container = app.stream_result(halt_after=["plain_sync"], inputs={"value": 1})
    list(container)
    written = [
        line
        for path in Path(storage).rglob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert written, "a step that ran must still be persisted by the tracker"
