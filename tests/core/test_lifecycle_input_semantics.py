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
"""Lifecycle and input semantics must be the same on every execution entry point.

Covers #979 (``pre_run_step`` handed the raw dict), #1007 (inputs processed twice) and #1017 (the
injected ``ApplicationContext`` numbered at the previous position) across ``step``, ``astep``,
``stream_result``, ``astream_result``, ``stream_iterate`` and ``astream_iterate``, over synchronous,
asynchronous and streaming actions, synchronous and asynchronous hooks, tracking on and off, fresh
and resumed applications, and four input shapes.

Observables, deliberately:

  * **One shared, chronologically built event list.** The spy that counts ``_process_inputs`` calls,
    the lifecycle hooks and the actions all append to the *same* list as they run, so the order a
    test compares is the order that actually happened. An earlier version concatenated the spy's
    list with the hooks' list before indexing it, which made "inputs were processed before the step
    was announced" unfalsifiable: the spy's entries always came first by construction.
  * ``_process_inputs`` call count per action execution.
  * ``pre_run_step`` / ``post_run_step`` counts and how they pair.
  * Object identity between the ``__context`` a hook receives and the one its action receives.
    ``Application._context_factory`` builds a new ``ApplicationContext`` per injection, so identity
    is a direct public-API probe for "were the inputs built once?". No test here assigns to
    ``_dependency_factory`` or reads any other private attribute.
  * Exception type and message, and what the tracker persisted.

Nothing asserts on returned values: equal results are compatible with double processing.

Two conventions keep this honest:

  * Combinations are parametrised from ``LEGAL_PAIRS``, which was **measured** against the library
    rather than assumed, so a case is never executed only to be excused afterwards. The rejected
    combinations are asserted about in their own test instead.
  * A case that should have produced an injected context but did not is a **failure**, not a skip.
"""

import gc
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

import pytest

from burr.core import State, action
from burr.core.action import streaming_action
from burr.core.application import Application, ApplicationBuilder, ApplicationContext
from burr.lifecycle.base import (
    PostEndStreamHook,
    PostRunStepHook,
    PostRunStepHookAsync,
    PreRunStepHook,
    PreRunStepHookAsync,
    PreStartStreamHook,
)
from burr.tracking.client import LocalTrackingClient

ENTRIES = ["step", "astep", "stream_result", "astream_result", "stream_iterate", "astream_iterate"]
SYNC_ENTRIES = {"step", "stream_result", "stream_iterate"}
KINDS = ["sync", "async", "streaming_sync", "streaming_async"]
GOOD_INPUTS = {"value": 1, "undeclared": 2}
REJECTIONS = {"reserved_key": {"__reserved": 1, "value": 1}, "missing_required": {}}

# --------------------------------------------------------------------------- actions
OBSERVED: Dict[str, Any] = {"events": None, "contexts": []}


def _note(context: ApplicationContext) -> None:
    OBSERVED["contexts"].append(context)
    if OBSERVED["events"] is not None:
        OBSERVED["events"].append("action")


@action(reads=[], writes=["value"])
def plain_sync(state: State, value: int, __context: ApplicationContext) -> State:
    _note(__context)
    return state.update(value=value)


@action(reads=[], writes=["value"])
async def plain_async(state: State, value: int, __context: ApplicationContext) -> State:
    _note(__context)
    return state.update(value=value)


@action(reads=[], writes=["value"])
def boom_sync(state: State, value: int, __context: ApplicationContext) -> State:
    _note(__context)
    raise ValueError("action exploded")


@action(reads=[], writes=["value"])
async def boom_async(state: State, value: int, __context: ApplicationContext) -> State:
    _note(__context)
    raise ValueError("action exploded")


@streaming_action(reads=[], writes=["value", "tokens"])
def stream_sync(state: State, value: int, __context: ApplicationContext):
    _note(__context)
    yield {"tokens": 1}, None
    yield {"tokens": 2}, state.update(value=value, tokens=2)


@streaming_action(reads=[], writes=["value", "tokens"])
async def stream_async(state: State, value: int, __context: ApplicationContext):
    _note(__context)
    yield {"tokens": 1}, None
    yield {"tokens": 2}, state.update(value=value, tokens=2)


PLAIN_BY_KIND = {
    "sync": plain_sync,
    "async": plain_async,
    "streaming_sync": stream_sync,
    "streaming_async": stream_async,
}
BOOM_BY_KIND = {"sync": boom_sync, "async": boom_async}

# ---------------------------------------------------------------------------------
# Entry point x action kind legality, MEASURED against the library: every pairing was
# driven with an application id and recorded inputs, and accepted only if the action body
# actually ran and the state it wrote was the state expected. Two results are worth noting
# because they contradict a plausible reading of the API:
#
#   * a streaming action *can* be driven by step()/astep() -- it is executed as a single
#     step and updates state normally, so those are legal cases and not skipped axes;
#   * an async streaming action *can* be driven by astep(), but a *synchronous* streaming
#     action cannot be driven by astream_result()/astream_iterate(), which raises.
#
# The eight rejected pairings are asserted about in
# test_rejected_combinations_stay_rejected rather than quietly omitted.
# ---------------------------------------------------------------------------------
LEGAL_PAIRS: List[Tuple[str, str]] = [
    ("step", "sync"),
    ("step", "streaming_sync"),
    ("astep", "sync"),
    ("astep", "async"),
    ("astep", "streaming_sync"),
    ("astep", "streaming_async"),
    ("stream_result", "sync"),
    ("stream_result", "streaming_sync"),
    ("astream_result", "sync"),
    ("astream_result", "async"),
    ("astream_result", "streaming_async"),
    ("stream_iterate", "sync"),
    ("stream_iterate", "streaming_sync"),
    ("astream_iterate", "sync"),
    ("astream_iterate", "async"),
    ("astream_iterate", "streaming_async"),
]
REJECTED_PAIRS = {
    ("step", "async"): "an async action cannot run under a synchronous entry point",
    ("stream_result", "async"): "an async action cannot run under a synchronous entry point",
    ("stream_iterate", "async"): "an async action cannot run under a synchronous entry point",
    ("step", "streaming_async"): "an async streaming action cannot run under a synchronous entry",
    ("stream_result", "streaming_async"): "not iterable: the async generator is returned as a "
    "result rather than driven",
    ("stream_iterate", "streaming_async"): "not iterable: the async generator is returned as a "
    "result rather than driven",
    ("astream_result", "streaming_sync"): "astream_result refuses it: 'is not an async action, "
    "but is marked as streaming'",
    ("astream_iterate", "streaming_sync"): "astream_result refuses it: 'is not an async action, "
    "but is marked as streaming'",
}
LEGAL_PARAMS = [pytest.param(e, k, id=f"{e}-{k}") for e, k in LEGAL_PAIRS]
ASYNC_ENTRY_KIND_PAIRS = [(e, k) for e, k in LEGAL_PAIRS if e not in SYNC_ENTRIES]
# Pairs where a *synchronous* action is driven by an asynchronous entry point: the delegate
# branch of _astep, and the only place the _processed_inputs handoff is observable.
SYNC_VIA_ASYNC = [(e, "sync") for e in ("astep", "astream_result", "astream_iterate")]
# Pairs that reject inputs and are legal for both a sync and an async action where possible.
REJECTION_PAIRS = [("step", "sync")] + [
    (e, k) for e, k in LEGAL_PAIRS if k in ("sync", "async") and e != "step"
]
EXCEPTION_PAIRS = [
    ("step", "sync"),
    ("astep", "sync"),
    ("astep", "async"),
    ("stream_result", "sync"),
    ("stream_iterate", "sync"),
]
ASYNC_STREAMING_EXCEPTION_PAIRS = [
    (e, k) for e in ("astream_result", "astream_iterate") for k in ("sync", "async")
]


# ---------------------------------------------------------------------------- hooks
class Hook(PreRunStepHook, PostRunStepHook, PreStartStreamHook, PostEndStreamHook):
    """Appends to the same event list the input spy and the actions use."""

    def __init__(self, events: List[str], bag: Dict[str, Any]) -> None:
        self.events = events
        self.bag = bag

    def pre_run_step(self, *, inputs, sequence_id, **kwargs) -> None:
        self.events.append("pre_run_step")
        self.bag["pre_inputs"].append(dict(inputs))
        self.bag["pre_seq"].append(sequence_id)

    def post_run_step(self, *, exception, **kwargs) -> None:
        self.events.append("post_run_step")
        self.bag["post_exc"].append(type(exception).__name__)

    def pre_start_stream(self, **kwargs) -> None:
        self.events.append("pre_start_stream")

    def post_end_stream(self, **kwargs) -> None:
        self.events.append("post_end_stream")


class AsyncHook(PreRunStepHookAsync, PostRunStepHookAsync):
    def __init__(self, events: List[str], bag: Dict[str, Any]) -> None:
        self.events = events
        self.bag = bag

    async def pre_run_step(self, *, inputs, sequence_id, **kwargs) -> None:
        self.events.append("pre_run_step")
        self.bag["pre_inputs"].append(dict(inputs))
        self.bag["pre_seq"].append(sequence_id)

    async def post_run_step(self, *, exception, **kwargs) -> None:
        self.events.append("post_run_step")


def blank_bag() -> Dict[str, Any]:
    return {"pre_inputs": [], "pre_seq": [], "post_exc": []}


# --------------------------------------------------------------------------- driving
async def drive(
    entry: str,
    kind: str,
    inputs: Dict[str, Any],
    *,
    async_hooks: bool = False,
    tracked: bool = False,
    resume_at: Optional[int] = None,
    failing: bool = False,
    allow_unsupported: bool = False,
) -> Dict[str, Any]:
    """Run one step and report what the application announced.

    ``kind`` selects the action explicitly. An earlier version inferred it from whether the entry
    point's name began with ``a``, so the cases named for a sync action through an async entry ran
    an async action instead and never touched the delegate branch at all.

    ``allow_unsupported`` is used only by the test that pins the API boundary; everything else is
    refused, so an unsupported pairing can never be executed and then excused as a skip.
    """
    if not allow_unsupported and (entry, kind) not in LEGAL_PAIRS:
        raise AssertionError(
            f"{entry}/{kind} is not a supported pairing -- add it to REJECTED_PAIRS with the "
            "measured reason instead of driving it here"
        )
    if failing:
        assert kind in BOOM_BY_KIND, f"no failing variant defined for kind {kind!r}"
        chosen = BOOM_BY_KIND[kind]
    else:
        chosen = PLAIN_BY_KIND[kind]
    name = chosen.__name__

    events: List[str] = []
    bag = blank_bag()
    OBSERVED["events"] = events
    OBSERVED["contexts"] = []
    hooks: List[Any] = [AsyncHook(events, bag) if async_hooks else Hook(events, bag)]
    tracker = (
        LocalTrackingClient(project="semantics", storage_dir=tempfile.mkdtemp())
        if tracked
        else None
    )
    if tracker is not None:
        hooks.append(tracker)
    identifiers: Dict[str, Any] = {"app_id": str(uuid.uuid4())}
    if resume_at is not None:
        identifiers["sequence_id"] = resume_at
    app = (
        ApplicationBuilder()
        .with_actions(chosen)
        .with_transitions((name, name))
        .with_entrypoint(name)
        .with_identifiers(**identifiers)
        .with_hooks(*hooks)
        .build()
    )

    calls: List[str] = []
    real_process = Application._process_inputs

    def counted(this, raw_inputs, target_action, *extra, **kwextra):
        # *extra/**kwextra so the spy follows whichever signature the revision under test uses to
        # stamp the sequence id into the dependency factory.
        events.append("process_inputs")
        calls.append(target_action.name)
        return real_process(this, raw_inputs, target_action, *extra, **kwextra)

    err: Optional[BaseException] = None
    try:
        with mock.patch.object(Application, "_process_inputs", autospec=True, side_effect=counted):
            if entry == "step":
                app.step(inputs=inputs)
            elif entry == "astep":
                await app.astep(inputs=inputs)
            elif entry == "stream_result":
                _, container = app.stream_result(halt_after=[name], inputs=inputs)
                list(container)
            elif entry == "astream_result":
                _, container = await app.astream_result(halt_after=[name], inputs=inputs)
                _ = [item async for item in container]
                await container.get()
            elif entry == "stream_iterate":
                for _action, container in app.stream_iterate(halt_after=[name], inputs=inputs):
                    container.get()
            else:
                async for _action, container in app.astream_iterate(
                    halt_after=[name], inputs=inputs
                ):
                    _ = [item async for item in container]
                    await container.get()
    except BaseException as caught:  # noqa: BLE001 - the caller asserts on this
        err = caught
    finally:
        OBSERVED["events"] = None
    return {
        "events": events,
        "bag": bag,
        "calls": calls,
        "err": err,
        "contexts": list(OBSERVED["contexts"]),
        "stream_state": tracker.stream_state if tracker is not None else {},
        "seq_after": app.sequence_id,
        "pre_seq": bag["pre_seq"][0] if bag["pre_seq"] else None,
        "hook_inputs": bag["pre_inputs"][0] if bag["pre_inputs"] else None,
        "name": name,
    }


# ------------------------------------------------- one processing, one announced step
@pytest.mark.parametrize("entry,kind", LEGAL_PARAMS)
async def test_inputs_processed_once_and_step_announced_once(entry, kind):
    out = await drive(entry, kind, GOOD_INPUTS)
    assert out["err"] is None, f"{entry}/{kind}: {out['err']!r}"
    assert out["calls"] == [out["name"]], f"{entry}/{kind}: processed {out['calls']}"
    pre = out["events"].count("pre_run_step")
    post = out["events"].count("post_run_step")
    assert pre == post == 1, f"{entry}/{kind}: pre={pre} post={post}"


# ----------------------------------------------- the ordering claim is a real ordering
@pytest.mark.parametrize("entry,kind", LEGAL_PARAMS)
async def test_lifecycle_events_happen_in_the_only_valid_order(entry, kind):
    """Positions are compared inside one list that each producer appended to as it ran.

    The order this asserts is the order #1017 asks for: build the action's inputs, announce the
    step, run the action, close the step. A revision that announces before processing, or closes
    before running, fails here with the actual sequence in the message.
    """
    out = await drive(entry, kind, GOOD_INPUTS)
    assert out["err"] is None, f"{entry}/{kind}: {out['err']!r}"
    for expected in ("process_inputs", "pre_run_step", "action", "post_run_step"):
        assert expected in out["events"], f"{entry}/{kind}: {expected} never ran: {out['events']}"
    assert (
        out["events"].index("process_inputs")
        < out["events"].index("pre_run_step")
        < out["events"].index("action")
        < out["events"].index("post_run_step")
    ), f"{entry}/{kind}: events happened in the order {out['events']}"


# ------------------------------------------------------- hook and action share one dict
@pytest.mark.parametrize("entry,kind", LEGAL_PARAMS)
async def test_hook_and_action_receive_the_same_injected_object(entry, kind):
    out = await drive(entry, kind, GOOD_INPUTS)
    assert out["err"] is None, f"{entry}/{kind}: {out['err']!r}"
    assert out["hook_inputs"] is not None, f"{entry}/{kind}: pre_run_step never fired"
    assert out["contexts"], f"{entry}/{kind}: the action never reported its injected context"
    assert "__context" in out["hook_inputs"], (
        f"{entry}/{kind}: the hook received {sorted(out['hook_inputs'])} -- no injected "
        "dependency, so it cannot be observing what the action observes"
    )
    assert (
        out["hook_inputs"]["__context"] is out["contexts"][0]
    ), f"{entry}/{kind}: hook and action hold different objects, so the inputs were built twice"


@pytest.mark.parametrize("entry,kind", ASYNC_ENTRY_KIND_PAIRS)
async def test_async_hook_receives_the_same_injected_object(entry, kind):
    out = await drive(entry, kind, GOOD_INPUTS, async_hooks=True)
    assert out["err"] is None, f"{entry}/{kind}: {out['err']!r}"
    assert out["hook_inputs"] is not None, f"{entry}/{kind}: the async hook never fired"
    assert (
        "__context" in out["hook_inputs"]
    ), f"{entry}/{kind}: the async hook received {sorted(out['hook_inputs'])}"
    assert (
        out["hook_inputs"]["__context"] is out["contexts"][0]
    ), f"{entry}/{kind}: async hook and action hold different objects"


# ------------------------------------------------ a sync action through an async entry
@pytest.mark.parametrize("entry,kind", SYNC_VIA_ASYNC)
async def test_sync_action_through_async_entry_is_not_processed_twice(entry, kind):
    """``_astep`` delegates a synchronous action to ``_step``. If the already-processed dict is not
    handed over, the factory runs twice and the hook and the action diverge. This is reached only by
    asking for the ``sync`` kind explicitly: inferring the kind from the entry name would run an
    async action here and leave the delegate untested, which is what the previous version of this
    file did.
    """
    out = await drive(entry, kind, GOOD_INPUTS)
    assert out["err"] is None, f"{entry}/{kind}: {out['err']!r}"
    assert out["calls"] == [out["name"]], f"{entry}: _process_inputs ran {out['calls']}"
    assert out["events"].count("pre_run_step") == 1, f"{entry}: the step was announced twice"
    assert out["events"].count("post_run_step") == 1, f"{entry}: the step was closed twice"
    assert (
        out["hook_inputs"]["__context"] is out["contexts"][0]
    ), f"{entry}: hook and action diverged"


# ---------------------------------------------------- invalid input announces nothing
@pytest.mark.parametrize("entry,kind", REJECTION_PAIRS)
@pytest.mark.parametrize("bad", list(REJECTIONS), ids=list(REJECTIONS))
async def test_invalid_input_is_rejected_before_any_step_is_announced(entry, kind, bad):
    out = await drive(entry, kind, REJECTIONS[bad], tracked=True)
    assert isinstance(
        out["err"], ValueError
    ), f"{entry}/{kind}/{bad}: got {type(out['err']).__name__}"
    assert "pre_run_step" not in out["events"], f"{entry}/{kind}/{bad}: announced before validating"
    assert (
        "post_run_step" not in out["events"]
    ), f"{entry}/{kind}/{bad}: closed a step that never opened"
    assert out["calls"] == [out["name"]], f"{entry}/{kind}/{bad}: processing ran {out['calls']}"
    assert not out[
        "stream_state"
    ], f"{entry}/{kind}/{bad}: stream_state left open: {out['stream_state']}"


# -------------------------------------------------- rejected steps follow one numbering
@pytest.mark.parametrize("bad", list(REJECTIONS), ids=list(REJECTIONS))
async def test_rejected_step_follows_one_sequence_id_rule_across_entry_points(bad):
    """Whatever position the project takes on burning an id for a rejected step, the same graph
    driven through different public entry points must number it identically -- otherwise
    ``sequence_id`` stops being a usable resume/fork coordinate. This asserts only that the entry
    points agree, never which value is correct, so it does not pre-decide the policy question.
    """
    after: Dict[str, Any] = {}
    for entry, kind in [
        ("step", "sync"),
        ("astep", "async"),
        ("stream_result", "sync"),
        ("astream_result", "async"),
        ("stream_iterate", "sync"),
        ("astream_iterate", "async"),
    ]:
        out = await drive(entry, kind, REJECTIONS[bad], resume_at=5)
        assert isinstance(out["err"], ValueError), f"{entry}: {out['err']!r}"
        assert "pre_run_step" not in out["events"], f"{entry}: announced a rejected step"
        after[entry] = out["seq_after"]
    assert len(set(after.values())) == 1, f"entry points disagree on the post-failure id: {after}"


# -------------------------------------------------- the injected context's position
@pytest.mark.parametrize("entry,kind", LEGAL_PAIRS)
@pytest.mark.parametrize("resume_at", [None, 5], ids=["fresh_app", "resumed_at_5"])
async def test_injected_context_sequence_id_matches_the_announced_step(entry, kind, resume_at):
    out = await drive(entry, kind, GOOD_INPUTS, resume_at=resume_at)
    assert out["err"] is None, f"{entry}/{kind}: {out['err']!r}"
    assert out["contexts"], (
        f"{entry}/{kind}: the action did not run, so there is nothing to compare -- that is a "
        "failure, not a skip"
    )
    ctx = out["contexts"][0]
    assert isinstance(ctx.sequence_id, int), (
        f"{entry}/{kind}: __context.sequence_id is {ctx.sequence_id!r}; _context_factory declares "
        "int and docs/concepts/recursion.rst tells users to hand it to sub-applications"
    )
    assert ctx.sequence_id == out["pre_seq"], (
        f"{entry}/{kind}: the action's context says {ctx.sequence_id} but pre_run_step announced "
        f"{out['pre_seq']} -- inputs were processed on the wrong side of _increment_sequence_id()"
    )
    assert (
        out["pre_seq"] == out["seq_after"]
    ), f"{entry}/{kind}: announced {out['pre_seq']} but the application sits at {out['seq_after']}"


# ------------------------------------------------- action errors keep their identity
@pytest.mark.parametrize("entry,kind", EXCEPTION_PAIRS)
async def test_action_exception_type_message_and_records_survive(entry, kind):
    out = await drive(entry, kind, GOOD_INPUTS, tracked=True, failing=True)
    assert isinstance(
        out["err"], ValueError
    ), f"{entry}/{kind}: the action's ValueError was replaced by {type(out['err']).__name__}"
    assert "action exploded" in str(out["err"]), f"{entry}/{kind}: message lost"
    assert out["bag"]["post_exc"] == [
        "ValueError"
    ], f"{entry}/{kind}: post_run_step saw {out['bag']['post_exc']}"
    assert not out["stream_state"], f"{entry}/{kind}: stream_state left open: {out['stream_state']}"


# ---------------------------------------------------------------------------------
# #1000, not #1019. Under the asynchronous streaming entry points a failing *non-streaming*
# action still fires post_end_stream for a stream that never started; the resulting KeyError
# from TracerFactoryContextHook.post_run_step replaces the action's ValueError, so the caller
# sees an unrelated exception and the tracker keeps an unmatched lifecycle record.
#
# Marked strict on purpose: the moment #1000 lands this reports XPASS and fails, so the marker
# cannot go stale and the behaviour cannot silently become unasserted.
# ---------------------------------------------------------------------------------
@pytest.mark.parametrize("entry,kind", ASYNC_STREAMING_EXCEPTION_PAIRS)
@pytest.mark.xfail(
    reason="#1000: post_end_stream fires for a stream that never started and its KeyError "
    "masks the action's ValueError",
    strict=True,
)
async def test_action_exception_not_masked_under_async_streaming(entry, kind):
    out = await drive(entry, kind, GOOD_INPUTS, tracked=True, failing=True)
    assert isinstance(
        out["err"], ValueError
    ), f"{entry}/{kind}: the action's ValueError was replaced by {type(out['err']).__name__}"
    assert "action exploded" in str(out["err"]), f"{entry}/{kind}: message lost"


# ---------------------------------------------- streaming lifecycle pairs and cleans up
@pytest.mark.parametrize(
    "entry,kind",
    [
        ("stream_result", "streaming_sync"),
        ("stream_iterate", "streaming_sync"),
        ("astream_result", "streaming_async"),
        ("astream_iterate", "streaming_async"),
    ],
)
async def test_stream_lifecycle_pairs_and_cleans_up(entry, kind):
    out = await drive(entry, kind, GOOD_INPUTS, tracked=True)
    assert out["err"] is None, f"{entry}/{kind}: {out['err']!r}"
    assert (
        out["events"].count("pre_start_stream") == out["events"].count("post_end_stream") == 1
    ), f"{entry}/{kind}: {out['events']}"
    assert not out["stream_state"], f"{entry}/{kind}: stream_state left open: {out['stream_state']}"


# ------------------------------------------------------ the API boundary stays asserted
@pytest.mark.parametrize("entry,kind", sorted(REJECTED_PAIRS))
@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # unawaited coroutines are the point here
async def test_rejected_combinations_stay_rejected(entry, kind):
    """The combinations this matrix does not drive are not simply ignored: what the library does
    with them is pinned, so a future change that makes one of them silently work is visible here
    rather than in a production incident.
    """
    out = await drive(entry, kind, GOOD_INPUTS, allow_unsupported=True)
    assert out["err"] is not None, (
        f"{entry}/{kind} was expected to stay unsupported ({REJECTED_PAIRS[(entry, kind)]}) "
        "but it ran cleanly -- update LEGAL_PAIRS and extend the matrix if this is intended"
    )
    # These pairings leave coroutines that are never awaited. Collect them here, while this
    # test's warning filter is active, instead of letting the interpreter finalise them inside
    # some later unrelated test -- which attributes the RuntimeWarning to the wrong case and
    # puts noise in the CI log.
    del out
    gc.collect()


# ------------------------------------------------------ tracking still records
async def test_valid_step_is_still_recorded_by_the_tracker(tmp_path):
    """The tightening must not silence tracking for steps that actually ran."""
    tracker = LocalTrackingClient(project="recorded", storage_dir=str(tmp_path))
    app = (
        ApplicationBuilder()
        .with_actions(plain_sync)
        .with_entrypoint("plain_sync")
        .with_transitions(("plain_sync", "plain_sync"))
        .with_identifiers(app_id=str(uuid.uuid4()))
        .with_hooks(tracker)
        .build()
    )
    _, container = app.stream_result(halt_after=["plain_sync"], inputs={"value": 1})
    list(container)
    written = [f for f in tmp_path.rglob("*.jsonl") if f.stat().st_size > 0]
    assert written, "a step that ran must still be persisted by the tracker"
