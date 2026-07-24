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

import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Tuple
from unittest.mock import Mock

import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.util.instrumentation import InstrumentationScope

from burr.core import ApplicationBuilder, State, action
from burr.integrations.langfuse import BURR_TRACER_NAME, LangfuseBridge, burr_span_export_filter
from burr.visibility import TracerFactory


@action(reads=[], writes=["count"])
def counter_action(state: State, increment: int, __tracer: TracerFactory) -> Tuple[dict, State]:
    with __tracer("inner_work"):
        __tracer.log_attributes(
            custom_attr="custom_value",
            complex_attr=[{"role": "user", "content": "hi"}],
            mixed_attr=[1, "two"],
        )
        result = {"count": state.get("count", 0) + increment}
    return result, state.update(**result)


@action(reads=["count"], writes=["done"])
def finish_action(state: State) -> Tuple[dict, State]:
    result = {"done": True}
    return result, state.update(**result)


@pytest.fixture
def span_capture():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer(BURR_TRACER_NAME)
    return exporter, tracer


def _build_app(bridge: LangfuseBridge):
    return (
        ApplicationBuilder()
        .with_actions(counter_action, finish_action)
        .with_transitions(("counter_action", "finish_action"))
        .with_entrypoint("counter_action")
        .with_state(count=0)
        .with_identifiers(app_id="test-app-id", partition_key="test-user")
        .with_hooks(bridge)
        .build()
    )


def test_langfuse_bridge_span_structure_and_attributes(span_capture):
    exporter, tracer = span_capture
    bridge = LangfuseBridge(langfuse_client=Mock(), tracer=tracer)
    app = _build_app(bridge)
    app.run(halt_after=["finish_action"], inputs={"increment": 5})

    spans = exporter.get_finished_spans()
    spans_by_name = {span.name: span for span in spans}
    # 1 trace root (run) + 2 steps + 1 tracer span
    assert set(spans_by_name) == {"run", "counter_action", "finish_action", "inner_work"}

    # all spans belong to a single trace, rooted at the execute call
    root = spans_by_name["run"]
    assert root.parent is None
    assert all(span.context.trace_id == root.context.trace_id for span in spans)
    assert spans_by_name["counter_action"].parent.span_id == root.context.span_id
    assert spans_by_name["finish_action"].parent.span_id == root.context.span_id
    assert (
        spans_by_name["inner_work"].parent.span_id
        == spans_by_name["counter_action"].context.span_id
    )

    # session/user attributes: app_id -> session, partition_key -> user
    for name in ["run", "counter_action", "finish_action"]:
        assert spans_by_name[name].attributes["langfuse.session.id"] == "test-app-id"
        assert spans_by_name[name].attributes["langfuse.user.id"] == "test-user"
        assert spans_by_name[name].attributes["session.id"] == "test-app-id"
        assert spans_by_name[name].attributes["user.id"] == "test-user"

    # step observation input/output
    step_input = json.loads(
        spans_by_name["counter_action"].attributes["langfuse.observation.input"]
    )
    assert step_input["inputs"] == {"increment": 5}
    step_output = json.loads(
        spans_by_name["counter_action"].attributes["langfuse.observation.output"]
    )
    assert step_output["state"] == {"count": 5}

    # trace-level input/output from application state
    trace_output = json.loads(root.attributes["langfuse.observation.output"])
    assert trace_output["count"] == 5
    assert trace_output["done"] is True

    # attributes logged via __tracer land in Langfuse observation metadata
    inner = spans_by_name["inner_work"]
    assert inner.attributes["langfuse.observation.metadata.custom_attr"] == "custom_value"
    # complex values (e.g. lists of dicts) are JSON-serialized, since OTel
    # attributes only accept primitives and flat sequences of primitives
    assert json.loads(inner.attributes["langfuse.observation.metadata.complex_attr"]) == [
        {"role": "user", "content": "hi"}
    ]
    assert json.loads(inner.attributes["langfuse.observation.metadata.mixed_attr"]) == [1, "two"]


def test_langfuse_bridge_capture_state_false(span_capture):
    exporter, tracer = span_capture
    bridge = LangfuseBridge(langfuse_client=Mock(), tracer=tracer, capture_state=False)
    app = _build_app(bridge)
    app.run(halt_after=["finish_action"], inputs={"increment": 5})

    for span in exporter.get_finished_spans():
        assert "langfuse.observation.input" not in span.attributes
        assert "langfuse.observation.output" not in span.attributes


def test_langfuse_bridge_session_and_user_overrides(span_capture):
    exporter, tracer = span_capture
    bridge = LangfuseBridge(
        langfuse_client=Mock(),
        tracer=tracer,
        session_id="override-session",
        user_id="override-user",
    )
    app = _build_app(bridge)
    app.run(halt_after=["finish_action"], inputs={"increment": 1})

    root = {span.name: span for span in exporter.get_finished_spans()}["run"]
    assert root.attributes["langfuse.session.id"] == "override-session"
    assert root.attributes["langfuse.user.id"] == "override-user"


def test_langfuse_bridge_records_exceptions(span_capture):
    exporter, tracer = span_capture

    @action(reads=[], writes=[])
    def failing_action(state: State) -> Tuple[dict, State]:
        raise RuntimeError("boom")

    bridge = LangfuseBridge(langfuse_client=Mock(), tracer=tracer)
    app = (
        ApplicationBuilder()
        .with_actions(failing_action)
        .with_transitions()
        .with_entrypoint("failing_action")
        .with_state()
        .with_identifiers(app_id="test-app-id")
        .with_hooks(bridge)
        .build()
    )
    with pytest.raises(RuntimeError):
        app.run(halt_after=["failing_action"])

    spans_by_name = {span.name: span for span in exporter.get_finished_spans()}
    assert not spans_by_name["failing_action"].status.is_ok


def test_langfuse_bridge_rejects_client_and_kwargs():
    with pytest.raises(ValueError):
        LangfuseBridge(langfuse_client=Mock(), public_key="pk-lf-123")


def test_langfuse_bridge_uses_custom_provider_and_propagates_trace_attributes(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    propagation_attributes = ContextVar("propagation_attributes", default=None)
    langfuse_constructor = Mock(return_value=Mock())

    @contextmanager
    def capture_propagation_attributes(**attributes):
        token = propagation_attributes.set(attributes)
        try:
            yield
        finally:
            propagation_attributes.reset(token)

    monkeypatch.setattr(
        "burr.integrations.langfuse.propagate_attributes", capture_propagation_attributes
    )
    monkeypatch.setattr("burr.integrations.langfuse.Langfuse", langfuse_constructor)

    @action(reads=[], writes=["propagation"])
    def propagated_action(state: State) -> Tuple[dict, State]:
        result = {"propagation": propagation_attributes.get()}
        return result, state.update(**result)

    bridge = LangfuseBridge(
        tracer_provider=provider,
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
    )
    app = (
        ApplicationBuilder()
        .with_actions(propagated_action)
        .with_transitions()
        .with_entrypoint("propagated_action")
        .with_identifiers(app_id="test-app-id", partition_key="test-user")
        .with_hooks(bridge)
        .build()
    )
    _, result, _ = app.run(halt_after=["propagated_action"])

    assert {span.name for span in exporter.get_finished_spans()} == {
        "run",
        "propagated_action",
    }
    assert result["propagation"] == {
        "session_id": "test-app-id",
        "user_id": "test-user",
    }
    assert langfuse_constructor.call_args.kwargs["tracer_provider"] is provider
    assert propagation_attributes.get() is None


def test_langfuse_bridge_falls_back_without_propagate_attributes(span_capture, monkeypatch):
    # langfuse < 3.9 has no propagate_attributes, and the bridge should still work with session/user set on Burr's own spans
    exporter, tracer = span_capture
    monkeypatch.setattr("burr.integrations.langfuse.propagate_attributes", None)
    bridge = LangfuseBridge(langfuse_client=Mock(), tracer=tracer)
    app = _build_app(bridge)
    app.run(halt_after=["finish_action"], inputs={"increment": 2})

    spans_by_name = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans_by_name) == {"run", "counter_action", "finish_action", "inner_work"}
    assert spans_by_name["run"].attributes["langfuse.session.id"] == "test-app-id"
    assert spans_by_name["run"].attributes["langfuse.user.id"] == "test-user"


def test_langfuse_bridge_rejects_tracer_and_provider(span_capture):
    _, tracer = span_capture
    with pytest.raises(ValueError):
        LangfuseBridge(
            langfuse_client=Mock(),
            tracer=tracer,
            tracer_provider=TracerProvider(),
        )


def _make_readable_span(scope_name, attributes=None) -> ReadableSpan:
    return ReadableSpan(
        name="test",
        instrumentation_scope=InstrumentationScope(name=scope_name),
        attributes=attributes or {},
    )


def test_burr_span_export_filter():
    assert burr_span_export_filter(_make_readable_span(BURR_TRACER_NAME))
    assert burr_span_export_filter(_make_readable_span(BURR_TRACER_NAME + ".sub"))
    # spans exported by langfuse's default filter still pass
    assert burr_span_export_filter(
        _make_readable_span("some.other.scope", {"gen_ai.system": "openai"})
    )
