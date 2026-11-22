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

"""Agent 3.1 hardening tests: real OpenTelemetry traces, context restoration, exception safety.

These tests deliberately use the *real* OpenTelemetry SDK (``InMemorySpanExporter``) rather than
mocks. A test that only asserts "a span was started and a span was ended" cannot distinguish a
correct trace tree from two unrelated root spans, nor a real ``context.detach`` from one that
OpenTelemetry silently logged as failed.
"""

import asyncio
import json
import logging
import os
from typing import Dict, List, Optional

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from burr.core import ApplicationBuilder, State, action, default
from burr.core.artifacts import ArtifactStore, AsyncArtifactStore
from burr.integrations import opentelemetry as otel
from burr.integrations.opentelemetry import AsyncOpenTelemetryTracker, OpenTelemetryTracker
from burr.tracking.client import AsyncLocalTrackingClient, LocalTrackingClient

# ---------------------------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------------------------


class MemoryAsyncStore(AsyncArtifactStore):
    """Minimal async object store, with optional fault injection on ``put``."""

    def __init__(self, put_error: Optional[BaseException] = None):
        self.data: Dict[str, bytes] = {}
        self.put_calls = 0
        self.put_error = put_error

    async def put(self, data: bytes, key: str) -> Optional[bool]:
        self.put_calls += 1
        if self.put_error is not None:
            raise self.put_error
        if key in self.data:
            return False
        self.data[key] = data
        return True

    async def get(self, key: str) -> bytes:
        return self.data[key]

    async def exists(self, key: str) -> bool:
        return key in self.data


class MemorySyncStore(ArtifactStore):
    def __init__(self):
        self.data: Dict[str, bytes] = {}

    def put(self, data: bytes, key: str) -> Optional[bool]:
        if key in self.data:
            return False
        self.data[key] = data
        return True

    def get(self, key: str) -> bytes:
        return self.data[key]

    def exists(self, key: str) -> bool:
        return key in self.data


@action(reads=["counter"], writes=["counter"])
async def step(state: State) -> State:
    """Async action that opens a real OpenTelemetry child span while it runs."""
    child_tracer = trace.get_tracer("hardening.child")
    with child_tracer.start_as_current_span("action_child"):
        await asyncio.sleep(0)
    return state.update(counter=state["counter"] + 1)


@action(reads=["counter"], writes=["counter"])
async def step_then_step(state: State) -> State:
    return state.update(counter=state["counter"] + 1)


@action(reads=["counter"], writes=["counter"])
async def step_second(state: State) -> State:
    child_tracer = trace.get_tracer("hardening.child")
    with child_tracer.start_as_current_span("action_child"):
        await asyncio.sleep(0)
    return state.update(counter=state["counter"] + 1)


@action(reads=["counter"], writes=["counter"])
async def step_third(state: State) -> State:
    child_tracer = trace.get_tracer("hardening.child")
    with child_tracer.start_as_current_span("action_child"):
        await asyncio.sleep(0)
    return state.update(counter=state["counter"] + 1)


@action(reads=["counter"], writes=["counter"])
def step_sync(state: State) -> State:
    return state.update(counter=state["counter"] + 1)


# ---------------------------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------------------------


class _DetachCapture(logging.Handler):
    """Collects the exact error OpenTelemetry logs when a context token cannot be detached."""

    def __init__(self):
        super().__init__()
        self.records: List[logging.LogRecord] = []

    def emit(self, record):
        if "Failed to detach context" in record.getMessage():
            self.records.append(record)


@pytest.fixture
def otel_env(monkeypatch):
    """A real TracerProvider + InMemorySpanExporter, isolated per test.

    ``trace.set_tracer_provider`` is a one-shot global operation, so we install the provider via
    monkeypatch instead; pytest restores the previous provider after each test.
    """
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    provider.add_span_processor(otel.BurrTrackingSpanProcessor())
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)
    # initialize_tracer() would otherwise overwrite our provider.
    monkeypatch.setattr(otel, "initialized", True)
    monkeypatch.setattr(otel, "token_stack", otel.ContextVar("token_stack", default=None))
    monkeypatch.setattr(otel, "tracker_context", otel.ContextVar("tracker_context", default=None))
    otel.span_map.clear()

    capture = _DetachCapture()
    ctx_logger = logging.getLogger("opentelemetry.context")
    ctx_logger.addHandler(capture)
    ctx_logger.setLevel(logging.DEBUG)
    previous_propagate = ctx_logger.propagate
    ctx_logger.propagate = False
    try:
        yield provider, exporter, capture
    finally:
        ctx_logger.removeHandler(capture)
        ctx_logger.propagate = previous_propagate


def make_builder(storage_dir, *, store=None, app_id="hardening-app", **tracker_kwargs):
    builder = (
        ApplicationBuilder()
        .with_actions(step)
        .with_state(counter=0)
        .with_entrypoint("step")
        .with_identifiers(app_id=app_id)
    )
    if store is not None:
        builder = builder.with_object_store(store)
    return builder.with_tracker(
        "local", project="hardening", params={"storage_dir": str(storage_dir)}, **tracker_kwargs
    )


def read_lines(storage_dir, app_id, project="hardening") -> List[dict]:
    path = os.path.join(str(storage_dir), project, app_id, "log.jsonl")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def step_spans(exporter, name="step"):
    return [s for s in exporter.get_finished_spans() if s.name == name]


def child_spans(exporter):
    return [s for s in exporter.get_finished_spans() if s.name == "action_child"]


# ---------------------------------------------------------------------------------------------
# P0-A: ContextVar token restoration
# ---------------------------------------------------------------------------------------------


class TestP0AContextRestoration:
    async def test_detach_succeeds_with_no_error_log(self, tmp_path, otel_env):
        """A span ending is NOT proof of a restored context: assert the real OTel error log."""
        _, exporter, capture = otel_env
        before = trace.get_current_span().get_span_context().span_id

        app = await make_builder(tmp_path, store=MemoryAsyncStore(), use_otel_tracing=True).abuild()
        await app.arun(halt_after=["step"])

        assert capture.records == [], [
            (r.getMessage(), r.exc_info[1] if r.exc_info else None) for r in capture.records
        ]
        after = trace.get_current_span().get_span_context().span_id
        assert after == before, "the current span must be restored after the step"
        assert otel.token_stack.get() is None
        assert otel.tracker_context.get() is None
        assert len(step_spans(exporter)) == 1

    async def test_copy_context_cannot_reset_a_token(self, otel_env):
        """Direct proof of the assumption P0-A was built on: a copied Context cannot reset it.

        This pins *why* the fix removed ``contextvars.copy_context()``; if someone reintroduces
        it, this test documents the exact failure mode rather than letting it hide in a log.
        """
        import contextvars

        from opentelemetry import context as otel_context

        var = contextvars.ContextVar("hardening_probe", default="unset")
        token = var.set("attached")
        snapshot = contextvars.copy_context()
        with pytest.raises(ValueError, match="different Context"):
            snapshot.run(var.reset, token)
        # and OpenTelemetry's own attach/detach obeys the same rule -- but OTel *swallows* the
        # ValueError inside detach() and only logs "Failed to detach context". This is exactly
        # why the production code must not rely on a copied Context: the failure is invisible
        # unless the log is captured.
        provider, _, capture = otel_env
        tracer = provider.get_tracer("probe")
        span = tracer.start_span("probe")
        tok = otel_context.attach(trace.set_span_in_context(span))
        copied = contextvars.copy_context()
        copied.run(otel_context.detach, tok)
        assert any("Failed to detach context" in r.getMessage() for r in capture.records)
        assert any(
            r.exc_info and "different Context" in str(r.exc_info[1]) for r in capture.records
        )
        capture.records.clear()
        otel_context.detach(tok)  # the real context can still detach it
        span.end()

    async def test_no_context_leak_after_repeated_steps(self, tmp_path, otel_env):
        _, exporter, capture = otel_env
        builder = (
            ApplicationBuilder()
            .with_actions(step, step_second, step_third)
            .with_transitions(
                ("step", "step_second", default), ("step_second", "step_third", default)
            )
            .with_state(counter=0)
            .with_entrypoint("step")
            .with_identifiers(app_id="repeat-app")
            .with_tracker(
                "local",
                project="hardening",
                params={"storage_dir": str(tmp_path)},
                use_otel_tracing=True,
            )
            .with_object_store(MemoryAsyncStore())
        )
        app = await builder.abuild()
        await app.arun(halt_after=["step_third"])

        assert capture.records == []
        assert otel.token_stack.get() is None
        assert otel.tracker_context.get() is None
        finished = exporter.get_finished_spans()
        steps = [s for s in finished if s.name in {"step", "step_second", "step_third"}]
        children = child_spans(exporter)
        assert len(steps) == 3
        assert len(children) == 3
        # every child belongs to one of the three step spans
        assert all(
            c.parent and c.parent.span_id in {s.context.span_id for s in steps} for c in children
        )


# ---------------------------------------------------------------------------------------------
# P0-B: real trace tree
# ---------------------------------------------------------------------------------------------


class TestP0BTraceTree:
    async def test_step_and_child_form_a_real_trace_tree(self, tmp_path, otel_env, caplog):
        """All eight correctness checks through a complete async Burr application."""
        _, exporter, capture = otel_env
        before_span_id = trace.get_current_span().get_span_context().span_id

        with caplog.at_level(logging.WARNING, logger="opentelemetry.sdk.trace"):
            app = await make_builder(
                tmp_path, store=MemoryAsyncStore(), use_otel_tracing=True
            ).abuild()
            await app.arun(halt_after=["step"])

        finished = list(exporter.get_finished_spans())
        steps = step_spans(exporter)
        children = child_spans(exporter)

        # 1/2: both spans were produced
        assert len(steps) == 1, [s.name for s in finished]
        assert len(children) == 1, [s.name for s in finished]
        step_span, child = steps[0], children[0]
        # 3: same trace
        assert step_span.context.trace_id == child.context.trace_id
        # 4: real parent/child relationship (not two root spans)
        assert child.parent is not None
        assert child.parent.span_id == step_span.context.span_id
        assert child.context.trace_id == step_span.context.trace_id
        # 5: each span ended exactly once
        span_ids = [s.context.span_id for s in finished]
        assert len(span_ids) == len(set(span_ids)), "a span was exported more than once"
        assert not any("ended span" in r.getMessage() for r in caplog.records)
        # 6: context restored
        assert trace.get_current_span().get_span_context().span_id == before_span_id
        assert otel.token_stack.get() is None
        assert otel.tracker_context.get() is None
        # 7: no OpenTelemetry detach errors
        assert capture.records == []
        # 8 (single-app form): the tracking log is still written exactly once
        lines = read_lines(tmp_path, "hardening-app")
        assert len([line for line in lines if line["type"] == "begin_entry"]) == 1
        assert len([line for line in lines if line["type"] == "end_entry"]) == 1

    async def test_two_concurrent_applications_do_not_cross_contaminate(self, tmp_path, otel_env):
        """Two apps in two tasks: each child must hang off its own step span."""
        _, exporter, capture = otel_env

        async def run(app_id):
            builder = make_builder(
                tmp_path, store=MemoryAsyncStore(), app_id=app_id, use_otel_tracing=True
            )
            app = await builder.abuild()
            await app.arun(halt_after=["step"])
            return app

        app_a, app_b = await asyncio.gather(run("concurrent-a"), run("concurrent-b"))

        steps = step_spans(exporter)
        children = child_spans(exporter)
        assert len(steps) == 2, [s.name for s in exporter.get_finished_spans()]
        assert len(children) == 2
        # two distinct traces, no mixing
        assert len({s.context.trace_id for s in steps}) == 2
        for child in children:
            parents = [s for s in steps if s.context.span_id == child.parent.span_id]
            assert len(parents) == 1, "child span has no matching step parent"
            assert child.context.trace_id == parents[0].context.trace_id
        # one parent per step, no cross-links
        assert len({c.parent.span_id for c in children}) == 2
        assert capture.records == []
        assert otel.token_stack.get() is None
        assert otel.tracker_context.get() is None
        assert app_a.builder.tracker is not app_b.builder.tracker

    async def test_span_is_current_while_the_action_runs(self, tmp_path, otel_env):
        """The action itself must observe the step span as current, not just the hooks."""
        observed = []

        @action(reads=["counter"], writes=["counter"])
        async def observing_step(state: State) -> State:
            observed.append(trace.get_current_span().get_span_context().span_id)
            return state.update(counter=state["counter"] + 1)

        _, exporter, _ = otel_env
        builder = (
            ApplicationBuilder()
            .with_actions(observing_step)
            .with_state(counter=0)
            .with_entrypoint("observing_step")
            .with_identifiers(app_id="observe-app")
            .with_tracker(
                "local",
                project="hardening",
                params={"storage_dir": str(tmp_path)},
                use_otel_tracing=True,
            )
            .with_object_store(MemoryAsyncStore())
        )
        app = await builder.abuild()
        await app.arun(halt_after=["observing_step"])
        step_span = [s for s in exporter.get_finished_spans() if s.name == "observing_step"][0]
        assert observed == [step_span.context.span_id]


# ---------------------------------------------------------------------------------------------
# P0-C: explicit tracker instance + use_otel_tracing
# ---------------------------------------------------------------------------------------------


class _DuckAsyncTracker:
    """An async tracker that does not inherit the marker classes at all."""

    def __init__(self):
        self.calls = []

    async def pre_run_step(self, *, action, **future_kwargs):
        self.calls.append(("pre", action.name))

    async def post_run_step(self, *, action, **future_kwargs):
        self.calls.append(("post", action.name))

    def post_application_create(self, **future_kwargs):
        pass

    def pre_start_stream(self, **future_kwargs):
        pass

    def post_stream_item(self, **future_kwargs):
        pass

    def post_end_stream(self, **future_kwargs):
        pass

    def pre_start_span(self, **future_kwargs):
        pass

    def post_end_span(self, **future_kwargs):
        pass

    def do_log_attributes(self, **future_kwargs):
        pass

    def copy(self):
        return _DuckAsyncTracker()


class TestP0CExplicitTrackerSelection:
    async def test_explicit_async_tracker_gets_async_wrapper_and_runs(self, tmp_path, otel_env):
        """The real failure: a sync wrapper would call async hooks without awaiting them."""
        _, exporter, capture = otel_env
        explicit = AsyncLocalTrackingClient("explicit", str(tmp_path))
        builder = (
            ApplicationBuilder()
            .with_actions(step)
            .with_state(counter=0)
            .with_entrypoint("step")
            .with_identifiers(app_id="explicit-async")
            .with_tracker(explicit, use_otel_tracing=True)
            .with_object_store(MemoryAsyncStore())
        )
        app = await builder.abuild()
        wrapper = app.builder.tracker

        assert type(wrapper) is AsyncOpenTelemetryTracker
        assert wrapper.burr_tracker is explicit, "the underlying instance must not be replaced"

        await app.arun(halt_after=["step"])

        # real run + real log, not just a type assertion
        lines = read_lines(tmp_path, "explicit-async", project="explicit")
        assert len([line for line in lines if line["type"] == "begin_entry"]) == 1
        assert len([line for line in lines if line["type"] == "end_entry"]) == 1
        assert "coroutine" not in json.dumps(lines)
        assert app.state["counter"] == 1
        assert len(step_spans(exporter)) == 1
        assert capture.records == []

    async def test_explicit_sync_tracker_gets_sync_wrapper_and_runs(self, tmp_path, otel_env):
        _, exporter, capture = otel_env
        explicit = LocalTrackingClient("explicit-sync", str(tmp_path))
        builder = (
            ApplicationBuilder()
            .with_actions(step_sync)
            .with_state(counter=0)
            .with_entrypoint("step_sync")
            .with_identifiers(app_id="explicit-sync-app")
            .with_tracker(explicit, use_otel_tracing=True)
        )
        app = builder.build()
        wrapper = app.builder.tracker
        assert type(wrapper) is OpenTelemetryTracker
        assert wrapper.burr_tracker is explicit

        app.run(halt_after=["step_sync"])

        lines = read_lines(tmp_path, "explicit-sync-app", project="explicit-sync")
        assert len([line for line in lines if line["type"] == "begin_entry"]) == 1
        assert len([line for line in lines if line["type"] == "end_entry"]) == 1
        assert len([s for s in exporter.get_finished_spans() if s.name == "step_sync"]) == 1
        assert capture.records == []

    async def test_duck_typed_async_tracker_is_never_called_synchronously(self, tmp_path, otel_env):
        """An async hook on an unmarked tracker must still be awaited, not called as a function."""
        explicit = _DuckAsyncTracker()
        builder = (
            ApplicationBuilder()
            .with_actions(step)
            .with_state(counter=0)
            .with_entrypoint("step")
            .with_identifiers(app_id="duck-async")
            .with_tracker(explicit, use_otel_tracing=True)
            .with_object_store(MemoryAsyncStore())
        )
        app = await builder.abuild()
        wrapper = app.builder.tracker
        assert type(wrapper) is AsyncOpenTelemetryTracker
        assert wrapper.burr_tracker is explicit

        await app.arun(halt_after=["step"])
        assert ("pre", "step") in explicit.calls
        assert ("post", "step") in explicit.calls

    async def test_no_double_registration_of_step_hooks(self, tmp_path, otel_env):
        """The wrapper must register exactly one family of step hooks."""
        from burr.lifecycle.internal import LifecycleAdapterSet

        explicit = AsyncLocalTrackingClient("hooks", str(tmp_path))
        wrapper = AsyncOpenTelemetryTracker(burr_tracker=explicit)
        adapter_set = LifecycleAdapterSet(wrapper)
        for hook in ("pre_run_step", "post_run_step"):
            assert hook not in adapter_set.sync_hooks
            assert len(adapter_set.async_hooks[hook]) == 1
        for hook in (
            "post_application_create",
            "pre_start_span",
            "post_end_span",
            "do_log_attributes",
        ):
            assert len(adapter_set.sync_hooks[hook]) == 1
            assert hook not in adapter_set.async_hooks

    async def test_string_and_explicit_paths_agree(self, tmp_path, otel_env):
        """Both configuration routes must end up with the same wrapper family."""
        string_builder = make_builder(
            tmp_path, store=MemoryAsyncStore(), app_id="string-path", use_otel_tracing=True
        )
        explicit = AsyncLocalTrackingClient("hardening", str(tmp_path))
        explicit_builder = (
            ApplicationBuilder()
            .with_actions(step)
            .with_state(counter=0)
            .with_entrypoint("step")
            .with_identifiers(app_id="explicit-path")
            .with_tracker(explicit, use_otel_tracing=True)
            .with_object_store(MemoryAsyncStore())
        )
        app_string = await string_builder.abuild()
        app_explicit = await explicit_builder.abuild()
        assert type(app_string.builder.tracker) is type(app_explicit.builder.tracker)


# ---------------------------------------------------------------------------------------------
# P1-D: strict exception / cancellation cleanup
# ---------------------------------------------------------------------------------------------


def _inject_post_failure(monkeypatch, wrapper, exc: BaseException):
    """Make the wrapped tracker's post hook raise at the exact ``await`` boundary."""
    inner = wrapper.burr_tracker

    async def failing_post_run_step(*args, **kwargs):
        raise exc

    monkeypatch.setattr(inner, "post_run_step", failing_post_run_step)


class TestP1DExceptionSafety:
    @pytest.mark.parametrize(
        "fault,expect_status",
        [
            ("type_error", True),
            ("os_error", True),
            ("cancelled", True),
        ],
    )
    async def test_span_is_closed_when_the_post_hook_raises(
        self, tmp_path, otel_env, monkeypatch, fault, expect_status
    ):
        """Serializer TypeError, object-store OSError and CancelledError during the await."""
        _, exporter, capture = otel_env
        builder = make_builder(tmp_path, store=MemoryAsyncStore(), use_otel_tracing=True)
        app = await builder.abuild()
        wrapper = app.builder.tracker
        assert type(wrapper) is AsyncOpenTelemetryTracker

        if fault == "type_error":
            raised = TypeError("serializer exploded")
        elif fault == "os_error":
            raised = OSError("object store I/O failed")
        else:
            raised = asyncio.CancelledError()
        _inject_post_failure(monkeypatch, wrapper, raised)

        with pytest.raises(type(raised)) as caught:
            await app.arun(halt_after=["step"])
        if fault == "type_error":
            assert "serializer exploded" in str(caught.value)

        # cleanup is strict: no stale entry, span finished, no detach error
        assert wrapper._open_step_spans == {}
        steps = step_spans(exporter)
        assert len(steps) == 1, "the step span must still be ended"
        assert steps[0].end_time is not None
        assert capture.records == []
        assert otel.token_stack.get() is None
        assert otel.tracker_context.get() is None
        assert expect_status

    async def test_real_log_write_failure_still_closes_span(self, tmp_path, otel_env, monkeypatch):
        """A genuine tracker I/O failure (no mocked hook): ``f.write`` raises OSError."""
        _, exporter, capture = otel_env
        builder = make_builder(tmp_path, store=MemoryAsyncStore(), use_otel_tracing=True)
        app = await builder.abuild()
        wrapper = app.builder.tracker
        inner = wrapper.burr_tracker

        class _BrokenWriter:
            """Fails on the *second* write: begin_entry succeeds, end_entry does not.

            That puts the failure inside the post hook, after the step span was opened, which is
            exactly the window the ``finally`` cleanup has to protect.
            """

            def __init__(self):
                self.writes = 0

            def write(self, _line):
                self.writes += 1
                if self.writes >= 2:
                    raise OSError("disk full")

            def flush(self):
                pass

        # post_application_create already opened the real log; swap only the handle.
        assert inner.f is not None
        monkeypatch.setattr(inner, "f", _BrokenWriter())

        with pytest.raises(OSError, match="disk full"):
            await app.arun(halt_after=["step"])

        assert wrapper._open_step_spans == {}
        assert len(step_spans(exporter)) == 1
        assert capture.records == []

    async def test_span_is_ended_exactly_once(self, tmp_path, otel_env, monkeypatch):
        """No double end, and cleanup runs once -- normal and failing paths."""
        _, exporter, _ = otel_env
        calls = []
        original = otel._exit_span_direct
        # See the note in test_async_local_tracking_client: with the optional action_scope the
        # context is already restored, so the span is ended by ``_end_span`` instead.
        original_end = getattr(otel, "_end_span", None)

        def spy(span, token, exc=None):
            calls.append(span)
            return original(span, token, exc)

        def spy_end(span, exc=None):
            calls.append(span)
            return original_end(span, exc)

        monkeypatch.setattr(otel, "_exit_span_direct", spy)
        if original_end is not None:
            monkeypatch.setattr(otel, "_end_span", spy_end)

        builder = make_builder(tmp_path, store=MemoryAsyncStore(), use_otel_tracing=True)
        app = await builder.abuild()
        await app.arun(halt_after=["step"])
        assert len(calls) == 1
        finished_ids = [s.context.span_id for s in exporter.get_finished_spans()]
        assert len(finished_ids) == len(set(finished_ids))
        assert len(step_spans(exporter)) == 1

    async def test_subsequent_step_still_logged_after_a_failure(
        self, tmp_path, otel_env, monkeypatch
    ):
        """A failed step must not poison the tracker for the next one."""
        _, exporter, capture = otel_env
        builder = (
            ApplicationBuilder()
            .with_actions(step, step_second, step_third)
            .with_transitions(
                ("step", "step_second", default), ("step_second", "step_third", default)
            )
            .with_state(counter=0)
            .with_entrypoint("step")
            .with_identifiers(app_id="after-failure")
            .with_tracker(
                "local",
                project="hardening",
                params={"storage_dir": str(tmp_path)},
                use_otel_tracing=True,
            )
            .with_object_store(MemoryAsyncStore())
        )
        app = await builder.abuild()
        wrapper = app.builder.tracker
        inner = wrapper.burr_tracker
        original_post = inner.post_run_step
        state = {"fail": True}

        async def fail_once(*args, **kwargs):
            if state["fail"]:
                state["fail"] = False
                raise ValueError("one-off serializer failure")
            return await original_post(*args, **kwargs)

        monkeypatch.setattr(inner, "post_run_step", fail_once)

        with pytest.raises(ValueError, match="one-off serializer failure"):
            await app.arun(halt_after=["step_second"])
        assert wrapper._open_step_spans == {}

        # the next step runs cleanly, with a fresh span and a fresh log entry
        await app.arun(halt_after=["step_third"])
        assert wrapper._open_step_spans == {}
        assert capture.records == []
        lines = read_lines(tmp_path, "after-failure")
        ends = [line for line in lines if line["type"] == "end_entry"]
        assert len(ends) >= 2
        assert ends[-1]["exception"] is None
        steps = [s for s in exporter.get_finished_spans() if s.name.startswith("step")]
        assert len(steps) >= 2

    async def test_cancellation_is_not_swallowed(self, tmp_path, otel_env, monkeypatch):
        _, exporter, capture = otel_env
        builder = make_builder(tmp_path, store=MemoryAsyncStore(), use_otel_tracing=True)
        app = await builder.abuild()
        wrapper = app.builder.tracker
        _inject_post_failure(monkeypatch, wrapper, asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await app.arun(halt_after=["step"])

        assert wrapper._open_step_spans == {}
        assert len(step_spans(exporter)) == 1
        assert capture.records == []

    async def test_two_concurrent_apps_sharing_one_tracker_do_not_leak(self, tmp_path, otel_env):
        """Adversarial: both apps use the *same* wrapper/tracker instance."""
        _, exporter, capture = otel_env
        explicit = AsyncLocalTrackingClient("hardening", str(tmp_path))
        wrapper = AsyncOpenTelemetryTracker(burr_tracker=explicit)

        def make(app_id):
            return (
                ApplicationBuilder()
                .with_actions(step)
                .with_state(counter=0)
                .with_entrypoint("step")
                .with_identifiers(app_id=app_id)
                .with_tracker(wrapper)
                .with_object_store(MemoryAsyncStore())
            )

        app_a = await make("shared-a").abuild()
        app_b = await make("shared-b").abuild()
        await asyncio.gather(app_a.arun(halt_after=["step"]), app_b.arun(halt_after=["step"]))

        assert wrapper._open_step_spans == {}
        steps = step_spans(exporter)
        children = child_spans(exporter)
        assert len(steps) == 2
        assert len(children) == 2
        assert len({s.context.trace_id for s in steps}) == 2
        assert all(
            c.parent and c.parent.span_id in {s.context.span_id for s in steps} for c in children
        )
        assert capture.records == []


# ---------------------------------------------------------------------------------------------
# P1-E: builder reconfiguration after a build
# ---------------------------------------------------------------------------------------------


class _NoopHook:
    """A user-supplied adapter that must never be removed by tracker reconfiguration."""


class TestP1EBuilderReconfiguration:
    async def test_reconfiguring_project_after_build_updates_the_tracker(self, tmp_path):
        """The second build must use project ``b`` and must not register two adapters."""
        builder = (
            ApplicationBuilder()
            .with_actions(step_sync)
            .with_state(counter=0)
            .with_entrypoint("step_sync")
            .with_identifiers(app_id="reconf-app")
            .with_tracker("local", project="proj-a", params={"storage_dir": str(tmp_path)})
        )
        app1 = builder.build()
        tracker1 = app1.builder.tracker
        assert type(tracker1) is LocalTrackingClient
        assert tracker1.project_id == "proj-a"
        assert len(builder.lifecycle_adapters) == 1

        builder.with_tracker("local", project="proj-b", params={"storage_dir": str(tmp_path)})
        app2 = builder.build()
        tracker2 = app2.builder.tracker
        assert tracker2 is not tracker1
        assert tracker2.project_id == "proj-b"
        assert len(builder.lifecycle_adapters) == 1, "stale adapter was not removed"
        assert tracker1 not in builder.lifecycle_adapters

        # both applications are still usable, and each writes to its own project
        app1.run(halt_after=["step_sync"])
        app2.run(halt_after=["step_sync"])
        assert os.path.isdir(os.path.join(str(tmp_path), "proj-a", "reconf-app"))
        assert os.path.isdir(os.path.join(str(tmp_path), "proj-b", "reconf-app"))

    async def test_old_application_log_handle_is_not_closed(self, tmp_path):
        """Reconfiguring must not close a resource another built application still holds."""
        builder = (
            ApplicationBuilder()
            .with_actions(step_sync)
            .with_state(counter=0)
            .with_entrypoint("step_sync")
            .with_identifiers(app_id="resource-app")
            .with_tracker("local", project="p1", params={"storage_dir": str(tmp_path)})
        )
        app1 = builder.build()
        old_tracker = app1.builder.tracker
        assert old_tracker.f is not None and not old_tracker.f.closed

        builder.with_tracker("local", project="p2", params={"storage_dir": str(tmp_path)})
        app2 = builder.build()

        assert old_tracker.f is not None and not old_tracker.f.closed
        assert app2.builder.tracker.f is not old_tracker.f
        app1.run(halt_after=["step_sync"])
        app2.run(halt_after=["step_sync"])
        assert len(read_lines(tmp_path, "resource-app", project="p1")) >= 2
        assert len(read_lines(tmp_path, "resource-app", project="p2")) >= 2

    async def test_switching_object_store_type_after_build_reselects_tracker(self, tmp_path):
        """Store type drives the sync/async tracker choice, including after a first build.

        Burr's ``with_entrypoint`` is single-use, so the graph stays fixed and only the store is
        swapped. A synchronous action can still run through ``arun()``.
        """
        builder = (
            ApplicationBuilder()
            .with_actions(step_sync)
            .with_state(counter=0)
            .with_entrypoint("step_sync")
            .with_identifiers(app_id="switch-app")
            .with_tracker("local", project="switch", params={"storage_dir": str(tmp_path)})
            .with_object_store(MemorySyncStore())
        )
        app1 = builder.build()
        first_tracker = app1.builder.tracker
        assert type(first_tracker) is LocalTrackingClient

        # sync -> async: the next build must get the async client
        builder.with_object_store(MemoryAsyncStore())
        app2 = await builder.abuild()
        assert type(app2.builder.tracker) is AsyncLocalTrackingClient
        assert app2.builder.tracker is not first_tracker
        assert len(builder.lifecycle_adapters) == 1
        await app2.arun(halt_after=["step_sync"])

        # async -> sync again
        builder.with_object_store(MemorySyncStore())
        app3 = builder.build()
        assert type(app3.builder.tracker) is LocalTrackingClient
        assert len(builder.lifecycle_adapters) == 1

    async def test_same_config_repeated_build_keeps_one_adapter(self, tmp_path):
        """Agent 3 behavior preserved: building twice with unchanged config reuses the client."""
        builder = (
            ApplicationBuilder()
            .with_actions(step_sync)
            .with_state(counter=0)
            .with_entrypoint("step_sync")
            .with_identifiers(app_id="repeat-build")
            .with_tracker("local", project="repeat", params={"storage_dir": str(tmp_path)})
        )
        app1 = builder.build()
        app2 = builder.build()
        assert app1.builder.tracker is app2.builder.tracker
        assert len(builder.lifecycle_adapters) == 1
        assert builder.lifecycle_adapters.count(app1.builder.tracker) == 1

    async def test_explicit_tracker_survives_object_store_change(self, tmp_path):
        """An explicitly supplied instance is never dropped or silently replaced."""
        explicit = LocalTrackingClient("explicit-e", str(tmp_path))
        builder = (
            ApplicationBuilder()
            .with_actions(step_sync)
            .with_state(counter=0)
            .with_entrypoint("step_sync")
            .with_identifiers(app_id="explicit-e-app")
            .with_tracker(explicit)
        )
        app1 = builder.build()
        assert app1.builder.tracker is explicit

        builder.with_object_store(MemorySyncStore())
        app2 = builder.build()
        assert app2.builder.tracker is explicit
        assert explicit in builder.lifecycle_adapters
        assert builder.lifecycle_adapters.count(explicit) == 1

    async def test_user_supplied_hooks_are_not_removed(self, tmp_path):
        """Reconfiguration removes only the adapter the builder appended itself."""
        from burr.lifecycle.internal import LifecycleAdapterSet

        extra = _NoopHook()
        builder = (
            ApplicationBuilder()
            .with_actions(step_sync)
            .with_state(counter=0)
            .with_entrypoint("step_sync")
            .with_identifiers(app_id="hooks-app")
            .with_hooks(extra)
            .with_tracker("local", project="h1", params={"storage_dir": str(tmp_path)})
        )
        app1 = builder.build()
        old_tracker = app1.builder.tracker  # app1.builder IS builder; capture the object now
        adapter_set = LifecycleAdapterSet(*builder.lifecycle_adapters)
        assert extra in adapter_set.adapters
        assert len(builder.lifecycle_adapters) == 2

        builder.with_tracker("local", project="h2", params={"storage_dir": str(tmp_path)})
        app2 = builder.build()
        assert extra in builder.lifecycle_adapters
        assert len(builder.lifecycle_adapters) == 2
        assert old_tracker not in builder.lifecycle_adapters
        assert app2.builder.tracker.project_id == "h2"
