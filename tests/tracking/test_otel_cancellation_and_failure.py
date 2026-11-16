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

"""OpenTelemetry span lifecycle under cancellation and wrapped-tracker failure.

Two failure modes are covered that a "span was started and ended" assertion cannot catch:

1. A pending cancellation can surface *before* ``post_run_step`` starts (a cancel scope
   re-cancels the next await). The hook then never runs -- which is what the ASGI early-close
   contract requires -- but the step span must still be ended and the tracker must not keep a
   stale entry.
2. The wrapped tracker's own ``post_run_step`` can raise. The span must be closed anyway, and its
   status must reflect that failure rather than the action's ``exception`` argument (which is
   ``None`` when the action succeeded).
"""

import asyncio
import contextlib
import logging

import anyio
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from burr.core import ApplicationBuilder, State, action
from burr.core.action import streaming_action
from burr.core.persistence import AsyncBaseStatePersister
from burr.integrations import opentelemetry as otel
from burr.integrations.opentelemetry import AsyncOpenTelemetryTracker, OpenTelemetryTracker
from burr.tracking.client import AsyncLocalTrackingClient, LocalTrackingClient

TOKENS = ["Burr ", "streams ", "tokens ", "as ", "they ", "arrive "]


@streaming_action(reads=[], writes=["response"])
async def slow_stream(state: State):
    """Streams with a delay, so a cancel scope can land mid-stream."""
    response = ""
    for token in TOKENS:
        await asyncio.sleep(0.05)
        response += token
        yield {"token": token}, None
    yield {"token": ""}, state.update(response=response)


@action(reads=[], writes=["x"])
async def step_with_child(state: State) -> State:
    with trace.get_tracer("cancellation-tests").start_as_current_span("action_child"):
        await asyncio.sleep(0)
    return state.update(x=1)


@action(reads=[], writes=["x"])
def sync_step(state: State) -> State:
    return state.update(x=1)


class _RecordingAsyncPersister(AsyncBaseStatePersister):
    def __init__(self):
        self.saved = []

    async def save(self, pk, app_id, sequence_id, position, state, status="completed", **kw):
        self.saved.append((sequence_id, status))

    async def list_app_ids(self, pk, **kwargs):
        return []

    async def load(self, pk, app_id, sequence_id=None, **kwargs):
        return None


class _DetachCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        if "Failed to detach context" in record.getMessage():
            self.records.append(record)


@pytest.fixture
def otel_env(monkeypatch):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    provider.add_span_processor(otel.BurrTrackingSpanProcessor())
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)
    monkeypatch.setattr(otel, "initialized", True)
    monkeypatch.setattr(otel, "token_stack", otel.ContextVar("token_stack", default=None))
    monkeypatch.setattr(otel, "tracker_context", otel.ContextVar("tracker_context", default=None))
    otel.span_map.clear()

    capture = _DetachCapture()
    logger = logging.getLogger("opentelemetry.context")
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)
    prev = logger.propagate
    logger.propagate = False
    try:
        yield provider, exporter, capture
    finally:
        logger.removeHandler(capture)
        logger.propagate = prev


async def _build_stream_app(tmp_path, app_id, persister=None):
    tracker = AsyncLocalTrackingClient(app_id, str(tmp_path))
    builder = (
        ApplicationBuilder()
        .with_actions(slow_stream)
        .with_state(State())
        .with_entrypoint("slow_stream")
        .with_identifiers(app_id=app_id)
        .with_tracker(tracker, use_otel_tracing=True)
    )
    if persister is not None:
        builder = builder.with_state_persister(persister)
    app = await builder.abuild()
    return app, tracker


async def _consume_until_cancelled(app, cancel_after: float) -> None:
    async def consume():
        async with contextlib.aclosing(app.astream_iterate(halt_after=["slow_stream"])) as steps:
            async for _action, container in steps:
                async for _item in container:
                    pass

    async with anyio.create_task_group() as tg:
        tg.start_soon(consume)
        await asyncio.sleep(cancel_after)
        tg.cancel_scope.cancel()


# ---------------------------------------------------------------------------------------------
# B: cancellation cleanup
# ---------------------------------------------------------------------------------------------


async def test_cancel_scope_ends_span_and_keeps_the_early_close_contract(tmp_path, otel_env):
    """The step is not recorded, but its span is still ended and nothing leaks."""
    _, exporter, capture = otel_env
    persister = _RecordingAsyncPersister()
    app, tracker = await _build_stream_app(tmp_path, "disc-app", persister)
    wrapper = app.builder.tracker
    assert type(wrapper) is AsyncOpenTelemetryTracker

    await _consume_until_cancelled(app, cancel_after=0.12)
    await asyncio.sleep(0.05)  # let the task-end cleanup callback run

    spans = [s for s in exporter.get_finished_spans() if s.name == "slow_stream"]
    assert len(spans) == 1, "the step span must be ended even though the hook never ran"
    assert spans[0].end_time is not None
    assert spans[0].status.status_code is trace.StatusCode.ERROR
    assert wrapper._open_step_spans == {}, "no stale open-span entry"
    assert persister.saved == [], "a cancelled step must not be persisted"
    assert capture.records == []
    assert otel.token_stack.get() is None
    assert otel.tracker_context.get() is None


async def test_followup_app_after_cancellation_has_a_correct_trace(tmp_path, otel_env):
    """Cancellation must not poison later runs: parent/child still line up."""
    _, exporter, _ = otel_env
    app, _ = await _build_stream_app(tmp_path, "disc-first")
    await _consume_until_cancelled(app, cancel_after=0.12)
    await asyncio.sleep(0.05)

    exporter.clear()
    tracker = AsyncLocalTrackingClient("follow-up", str(tmp_path))
    app2 = await (
        ApplicationBuilder()
        .with_actions(step_with_child)
        .with_state(x=0)
        .with_entrypoint("step_with_child")
        .with_identifiers(app_id="follow-up-app")
        .with_tracker(tracker, use_otel_tracing=True)
        .abuild()
    )
    await app2.arun(halt_after=["step_with_child"])

    spans = list(exporter.get_finished_spans())
    step = next(s for s in spans if s.name == "step_with_child")
    child = next(s for s in spans if s.name == "action_child")
    assert step.context.trace_id == child.context.trace_id
    assert child.parent is not None
    assert child.parent.span_id == step.context.span_id


async def test_task_cancel_still_records_a_failed_step(tmp_path, otel_env):
    """A plain ``task.cancel()`` must still produce a failed step with a closed span."""
    _, exporter, capture = otel_env
    app, tracker = await _build_stream_app(tmp_path, "tc-app")
    wrapper = app.builder.tracker

    async def consume():
        async for _action, container in app.astream_iterate(halt_after=["slow_stream"]):
            async for _item in container:
                pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.12)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.05)

    spans = [s for s in exporter.get_finished_spans() if s.name == "slow_stream"]
    assert len(spans) == 1
    assert spans[0].status.status_code is trace.StatusCode.ERROR
    assert wrapper._open_step_spans == {}
    assert capture.records == []


# ---------------------------------------------------------------------------------------------
# C: wrapped-tracker failure
# ---------------------------------------------------------------------------------------------


def test_sync_wrapper_ends_span_when_tracker_post_raises(tmp_path, otel_env):
    """Synchronous wrapper: a raising tracker must not leave the span open or marked OK."""
    _, exporter, capture = otel_env
    tracker = LocalTrackingClient("sync-fail", str(tmp_path))
    app = (
        ApplicationBuilder()
        .with_actions(sync_step)
        .with_state(x=0)
        .with_entrypoint("sync_step")
        .with_identifiers(app_id="sync-fail-app")
        .with_tracker(tracker, use_otel_tracing=True)
        .build()
    )
    wrapper = app.builder.tracker
    assert type(wrapper) is OpenTelemetryTracker

    def boom(**kwargs):
        raise RuntimeError("sync tracker post failed")

    tracker.post_run_step = boom

    with pytest.raises(RuntimeError, match="sync tracker post failed"):
        app.run(halt_after=["sync_step"])

    spans = [s for s in exporter.get_finished_spans() if s.name == "sync_step"]
    assert len(spans) == 1, "the span must be ended even though the tracker raised"
    assert spans[0].status.status_code is trace.StatusCode.ERROR
    assert capture.records == []


async def test_async_wrapper_ends_span_when_tracker_post_raises(tmp_path, otel_env):
    """Asynchronous wrapper: same contract, and the span must not be reported as OK."""
    _, exporter, capture = otel_env
    tracker = AsyncLocalTrackingClient("async-fail", str(tmp_path))
    app = await (
        ApplicationBuilder()
        .with_actions(step_with_child)
        .with_state(x=0)
        .with_entrypoint("step_with_child")
        .with_identifiers(app_id="async-fail-app")
        .with_tracker(tracker, use_otel_tracing=True)
        .abuild()
    )
    wrapper = app.builder.tracker
    assert type(wrapper) is AsyncOpenTelemetryTracker

    async def boom(**kwargs):
        raise RuntimeError("async tracker post failed")

    tracker.post_run_step = boom

    with pytest.raises(RuntimeError, match="async tracker post failed"):
        await app.arun(halt_after=["step_with_child"])

    spans = [s for s in exporter.get_finished_spans() if s.name == "step_with_child"]
    assert len(spans) == 1
    assert spans[0].status.status_code is trace.StatusCode.ERROR
    assert wrapper._open_step_spans == {}
    assert capture.records == []


async def test_cancellation_inside_the_post_hook_still_ends_the_span(tmp_path, otel_env):
    """Cancellation surfacing *inside* the wrapped post hook must also close the span."""
    _, exporter, capture = otel_env
    tracker = AsyncLocalTrackingClient("inside-cancel", str(tmp_path))
    app = await (
        ApplicationBuilder()
        .with_actions(step_with_child)
        .with_state(x=0)
        .with_entrypoint("step_with_child")
        .with_identifiers(app_id="inside-cancel-app")
        .with_tracker(tracker, use_otel_tracing=True)
        .abuild()
    )
    wrapper = app.builder.tracker

    async def slow_post(**kwargs):
        await asyncio.sleep(5)  # cancellation will land here

    tracker.post_run_step = slow_post

    task = asyncio.create_task(app.arun(halt_after=["step_with_child"]))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.05)

    spans = [s for s in exporter.get_finished_spans() if s.name == "step_with_child"]
    assert len(spans) == 1, "the span must be closed when the hook body is cancelled"
    assert spans[0].status.status_code is trace.StatusCode.ERROR
    assert wrapper._open_step_spans == {}
    assert capture.records == []
