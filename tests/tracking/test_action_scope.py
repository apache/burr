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

"""Tests for the optional ``action_scope`` lifecycle capability.

``action_scope`` is the integration boundary that makes a span (or any other context) current
*while the action runs* without requiring asynchronous hooks to be dispatched serially. These
tests pin the three properties that make that useful:

1. the scope is entered in the task that runs the action, so ``current_task()`` matches;
2. the action sees the context the scope established, even when the hooks that prepared it ran
   in their own tasks;
3. entering the scope does not change how hooks are dispatched.

They are deliberately independent of OpenTelemetry except for the two end-to-end tests at the
bottom, which assert the trace tree a user actually sees.
"""

import asyncio
import contextlib
import contextvars

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from burr.core import ApplicationBuilder, State, action
from burr.integrations import opentelemetry as otel
from burr.lifecycle.base import PostRunStepHookAsync, PreRunStepHookAsync
from burr.lifecycle.internal import LifecycleAdapterSet
from burr.tracking.client import AsyncLocalTrackingClient

VALUE = contextvars.ContextVar("action_scope_probe", default="unset")


class _ScopedAdapter(PreRunStepHookAsync, PostRunStepHookAsync):
    """An adapter that publishes a value for the action through ``action_scope``."""

    def __init__(self, record):
        self.record = record

    async def pre_run_step(self, **kwargs):
        # Deliberately *not* in the scope: this runs in its own task when hooks are gathered.
        self.record["pre_task"] = asyncio.current_task()

    @contextlib.contextmanager
    def action_scope(self, **kwargs):
        self.record["scope_entered"] = True
        self.record["scope_task"] = asyncio.current_task()
        self.record["action_saw_before"] = VALUE.get()
        token = VALUE.set("set-by-scope")
        try:
            yield
        finally:
            VALUE.reset(token)
            self.record["scope_exited"] = True
            self.record["action_saw_in_body"] = self.record.get("action_saw")

    async def post_run_step(self, **kwargs):
        self.record["post_task"] = asyncio.current_task()


class _PlainAdapter(PreRunStepHookAsync):
    """No ``action_scope`` -- must be skipped without error."""

    def __init__(self):
        self.ran = False

    async def pre_run_step(self, **kwargs):
        self.ran = True


async def _run_one_step(adapters, record):
    @action(reads=[], writes=["x"])
    async def act(state: State) -> State:
        record["action_task"] = asyncio.current_task()
        record["action_saw"] = VALUE.get()
        await asyncio.sleep(0)
        return state.update(x=1)

    app = await (
        ApplicationBuilder()
        .with_actions(act)
        .with_state(State())
        .with_entrypoint("act")
        .with_hooks(*adapters)
        .abuild()
    )
    await app.astep(inputs={})


async def test_action_scope_runs_in_the_actions_task():
    """The whole point: the scope body and the action share one task, so a token is legal."""
    record = {}
    await _run_one_step([_ScopedAdapter(record)], record)

    assert record["scope_entered"] is True
    assert record["scope_exited"] is True
    assert record["scope_task"] is record["action_task"]


async def test_action_sees_what_the_scope_established():
    """A value published by the scope is visible in the action and gone afterwards."""
    record = {}
    await _run_one_step([_ScopedAdapter(record)], record)

    assert record["action_saw_before"] == "unset"
    assert record["action_saw"] == "set-by-scope"
    assert VALUE.get() == "unset", "the scope must restore the previous value on exit"


async def test_pre_hook_still_runs_in_its_own_task():
    """Entering a scope must not drag the hooks back into the caller's task."""
    record = {}
    await _run_one_step([_ScopedAdapter(record)], record)

    assert record["pre_task"] is not record["action_task"]
    assert record["post_task"] is not record["action_task"]


async def test_adapters_without_action_scope_are_ignored():
    plain = _PlainAdapter()
    record = {}
    await _run_one_step([plain, _ScopedAdapter(record)], record)

    assert plain.ran is True
    assert record["scope_entered"] is True


async def test_action_scope_exits_when_the_action_raises():
    record = {}

    @action(reads=[], writes=["x"])
    async def boom(state: State) -> State:
        raise ValueError("action failed")

    class _Scope(PreRunStepHookAsync):
        @contextlib.contextmanager
        def action_scope(self, **kwargs):
            record["entered"] = True
            try:
                yield
            finally:
                record["exited"] = True

        async def pre_run_step(self, **kwargs):
            pass

    app = await (
        ApplicationBuilder()
        .with_actions(boom)
        .with_state(State())
        .with_entrypoint("boom")
        .with_hooks(_Scope())
        .abuild()
    )
    with pytest.raises(ValueError, match="action failed"):
        await app.astep(inputs={})

    assert record == {"entered": True, "exited": True}


async def test_scopes_nest_in_registration_order():
    """Two adapters that both scope: entered in order, exited in reverse."""
    order = []

    class _Marker(PreRunStepHookAsync):
        def __init__(self, name):
            self.name = name

        @contextlib.contextmanager
        def action_scope(self, **kwargs):
            order.append(f"{self.name}:enter")
            try:
                yield
            finally:
                order.append(f"{self.name}:exit")

        async def pre_run_step(self, **kwargs):
            pass

    record = {}
    await _run_one_step([_Marker("a"), _Marker("b")], record)

    assert order == ["a:enter", "b:enter", "b:exit", "a:exit"]


async def test_async_hooks_are_still_dispatched_concurrently():
    """The scope is an alternative to serialising hooks, so concurrency must survive."""
    order = []

    class _Sleeper(PreRunStepHookAsync):
        def __init__(self, name, delay):
            self.name = name
            self.delay = delay

        async def pre_run_step(self, **kwargs):
            order.append(f"{self.name}:enter")
            await asyncio.sleep(self.delay)
            order.append(f"{self.name}:exit")

    aset = LifecycleAdapterSet(_Sleeper("a", 0.03), _Sleeper("b", 0.03))
    await aset.call_all_lifecycle_hooks_sync_and_async("pre_run_step")

    assert order == ["a:enter", "b:enter", "a:exit", "b:exit"], "hooks must overlap"
    assert set(order) == {"a:enter", "b:enter", "a:exit", "b:exit"}


# ---------------------------------------------------------------------------------------------
# End to end: the trace tree a user sees
# ---------------------------------------------------------------------------------------------


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
    return provider, exporter


async def test_child_span_inside_the_action_is_parented_to_the_step_span(tmp_path, otel_env):
    _, exporter = otel_env

    @action(reads=[], writes=["x"])
    async def act(state: State) -> State:
        with trace.get_tracer("action-scope-tests").start_as_current_span("action_child"):
            await asyncio.sleep(0)
        return state.update(x=1)

    tracker = AsyncLocalTrackingClient("scope-project", str(tmp_path))
    app = await (
        ApplicationBuilder()
        .with_actions(act)
        .with_state(State())
        .with_entrypoint("act")
        .with_identifiers(app_id="scope-app")
        .with_tracker(tracker, use_otel_tracing=True)
        .abuild()
    )
    await app.astep(inputs={})

    spans = {span.name: span for span in exporter.get_finished_spans()}
    step, child = spans["act"], spans["action_child"]

    assert child.parent is not None, "the child span must not be a root"
    assert child.parent.span_id == step.get_span_context().span_id
    assert child.get_span_context().trace_id == step.get_span_context().trace_id


async def test_step_span_covers_the_action(tmp_path, otel_env):
    """The span must start before the action and end after it -- not close in the pre hook."""
    _, exporter = otel_env

    @action(reads=[], writes=["x"])
    async def act(state: State) -> State:
        with trace.get_tracer("action-scope-tests").start_as_current_span("action_child"):
            await asyncio.sleep(0.01)
        return state.update(x=1)

    tracker = AsyncLocalTrackingClient("scope-project", str(tmp_path))
    app = await (
        ApplicationBuilder()
        .with_actions(act)
        .with_state(State())
        .with_entrypoint("act")
        .with_identifiers(app_id="scope-app")
        .with_tracker(tracker, use_otel_tracing=True)
        .abuild()
    )
    await app.astep(inputs={})

    spans = {span.name: span for span in exporter.get_finished_spans()}
    step, child = spans["act"], spans["action_child"]

    assert step.start_time <= child.start_time
    assert step.end_time >= child.end_time
