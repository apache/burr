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
import logging
from collections import abc
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Tuple

from burr.integrations.base import require_plugin

logger = logging.getLogger(__name__)

try:
    from langfuse import Langfuse
    from opentelemetry import trace
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.trace import get_current_span
except ImportError as e:
    require_plugin(
        e,
        "langfuse",
    )

try:
    # propagate_attributes copies session/user attributes onto all child spans, including spans from third-party OTel instrumentation.
    # available on langfuse>=3.9; on older versions we fall back to setting the attributes on Burr's own spans only (see _set_trace_attributes).
    from langfuse import propagate_attributes
except ImportError:
    propagate_attributes = None

try:
    # Available on langfuse>=4 -- v4 only exports LLM-relevant spans by default,
    # so we extend the default filter to also export Burr spans.
    # On langfuse v3 all spans on the global tracer provider are exported,
    # so no filter is necessary.
    from langfuse import is_default_export_span
except ImportError:
    is_default_export_span = None

from burr.core import Action, State, serde
from burr.integrations.opentelemetry import OpenTelemetryBridge
from burr.lifecycle.base import ExecuteMethod
from burr.visibility import ActionSpan

BURR_TRACER_NAME = "burr.integrations.langfuse"

# Langfuse-recognized OpenTelemetry span attributes
# https://langfuse.com/integrations/native/opentelemetry (attribute mapping)
_LANGFUSE_OBSERVATION_INPUT = "langfuse.observation.input"
_LANGFUSE_OBSERVATION_OUTPUT = "langfuse.observation.output"
_LANGFUSE_OBSERVATION_METADATA_PREFIX = "langfuse.observation.metadata."
_LANGFUSE_SESSION_ID = "langfuse.session.id"
_LANGFUSE_USER_ID = "langfuse.user.id"
# Langfuse v3 uses the OpenTelemetry semantic convention attribute names.
_LANGFUSE_V3_SESSION_ID = "session.id"
_LANGFUSE_V3_USER_ID = "user.id"

# Attribute namespaces we pass through unprefixed so users can deliberately log Langfuse-mapped or GenAI semantic convention attributes.
_PASSTHROUGH_ATTRIBUTE_PREFIXES = ("langfuse.", "gen_ai.")


def burr_span_export_filter(span: "ReadableSpan") -> bool:
    """
    You only need this if you construct the :py:class:`Langfuse <langfuse.Langfuse>`
    client yourself -- :py:class:`LangfuseBridge` applies it automatically when it
    creates the client for you:

    .. code-block:: python

        from langfuse import Langfuse
        from burr.integrations.langfuse import LangfuseBridge, burr_span_export_filter

        client = Langfuse(should_export_span=burr_span_export_filter)
        app = ApplicationBuilder().with_hooks(LangfuseBridge(langfuse_client=client))...
    """
    scope = span.instrumentation_scope
    if scope is not None and (
        scope.name == BURR_TRACER_NAME or scope.name.startswith(BURR_TRACER_NAME + ".")
    ):
        return True
    if is_default_export_span is not None:
        return is_default_export_span(span)
    return True


def _serialize_for_langfuse(value: Any) -> str:
    # Serializes a value to a JSON string for the ``langfuse.observation.input``/ ``.output`` attributes, falling back to ``str`` on failure."""
    try:
        return json.dumps(serde.serialize(value))
    except Exception as e:
        logger.warning(f"Failed to serialize value for Langfuse: {e}")
        return str(value)


_OTEL_ATTRIBUTE_PRIMITIVES = (str, bool, int, float)


def _convert_attribute(value: Any) -> Any:
    """
    Converts a logged attribute value to a valid OpenTelemetry attribute value.
    OTel attributes only accept primitives and flat sequences of primitives, so
    anything else (dicts, lists of dicts, ...) is JSON-serialized -- Langfuse
    renders JSON strings in metadata.
    """
    if isinstance(value, _OTEL_ATTRIBUTE_PRIMITIVES):
        return value
    if isinstance(value, abc.Sequence):
        primitive_types = {type(item) for item in value}
        if len(primitive_types) <= 1 and all(
            isinstance(item, _OTEL_ATTRIBUTE_PRIMITIVES) for item in value
        ):
            return list(value)
    return _serialize_for_langfuse(value)


class LangfuseBridge(OpenTelemetryBridge):
    """
    Adapter to log Burr application execution to `Langfuse <https://langfuse.com>`_.

    1. Each application execution call (``run``/``step``/``iterate``/``stream_result``/...)
       opens a root span, which defines the Langfuse trace
    2. Each step opens a span, capturing the action's inputs/read state as the
       observation input and its result/written state as the observation output
    3. Each span opened through Burr's tracing API (``__tracer``) opens a span
    4. Attributes logged through ``__tracer.log_attribute(s)`` are captured as
       observation metadata

    Burr's ``app_id`` maps to the Langfuse session (so multiple execution calls of the
    same application group together), and the ``partition_key`` maps to the Langfuse
    user - both can be overridden.

    Basic usage - credentials are read from the standard ``LANGFUSE_PUBLIC_KEY``,
    ``LANGFUSE_SECRET_KEY``, and ``LANGFUSE_HOST`` environment variables:

    .. code-block:: python

        from burr.integrations.langfuse import LangfuseBridge

        app = (
            ApplicationBuilder()
            .with_graph(graph)
            .with_entrypoint("prompt")
            .with_hooks(LangfuseBridge())
            .build()
        )
        app.run(halt_after=["response"])  # logs one trace to Langfuse

    You can also pass credentials explicitly, or pass a pre-constructed client:

    .. code-block:: python

        LangfuseBridge(public_key="pk-lf-...", secret_key="sk-lf-...", host="...")
        # or, equivalently
        LangfuseBridge(langfuse_client=my_langfuse_client)

    The underlying client is available as ``bridge.langfuse_client`` -- for example to
    ``flush()`` in short-lived scripts, or to score traces.

    .. note::

        With langfuse v4+, spans are filtered before export, and only LLM-relevant
        spans are exported by default. If you construct the ``Langfuse`` client
        yourself, pass ``should_export_span=burr_span_export_filter`` to its
        constructor so Burr spans are exported (see
        :py:func:`burr_span_export_filter`). When ``LangfuseBridge`` constructs
        the client for you, this is applied automatically.
    """

    def __init__(
        self,
        langfuse_client: Optional["Langfuse"] = None,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        capture_state: bool = True,
        tracer: Optional["trace.Tracer"] = None,
        tracer_provider: Optional["trace.TracerProvider"] = None,
        **langfuse_kwargs: Any,
    ):
        """
        Initializes the Langfuse bridge.

        :param langfuse_client: A pre-constructed Langfuse client to use. If not passed,
            one is created from ``langfuse_kwargs`` (falling back to the standard
            ``LANGFUSE_*`` environment variables), with the Burr span export filter applied.
        :param session_id: Langfuse session ID to group traces under. Defaults to the
            Burr ``app_id``.
        :param user_id: Langfuse user ID to attach to traces. Defaults to the Burr
            ``partition_key`` (if set).
        :param capture_state: Whether to capture state/inputs/results as observation
            input/output. Set to False if your state contains data you do not want
            sent to Langfuse.
        :param tracer: OpenTelemetry tracer to use -- for testing/advanced use. Defaults
            to a tracer named ``burr.integrations.langfuse`` from the global provider.
        :param tracer_provider: OpenTelemetry tracer provider to use for both the
            Langfuse client and Burr spans. When passing a pre-constructed client that
            uses a custom provider, pass the same provider here.
        :param langfuse_kwargs: Keyword arguments forwarded to the
            :py:class:`Langfuse <langfuse.Langfuse>` constructor (e.g. ``public_key``,
            ``secret_key``, ``host``). Only valid if ``langfuse_client`` is not passed.
        """
        if tracer is not None and tracer_provider is not None:
            raise ValueError("Only pass one of tracer or tracer_provider, not both.")
        if langfuse_client is not None and langfuse_kwargs:
            raise ValueError(
                f"Only pass one of langfuse_client or langfuse constructor kwargs, not both. "
                f"Got: langfuse_client={langfuse_client} and kwargs={list(langfuse_kwargs)}"
            )
        if langfuse_client is None:
            if is_default_export_span is not None:
                langfuse_kwargs.setdefault("should_export_span", burr_span_export_filter)
            if tracer_provider is not None:
                langfuse_kwargs["tracer_provider"] = tracer_provider
            langfuse_client = Langfuse(**langfuse_kwargs)
        self.langfuse_client = langfuse_client
        self.session_id = session_id
        self.user_id = user_id
        self.capture_state = capture_state
        self._propagation_context_stack: ContextVar[Optional[List[Any]]] = ContextVar(
            f"langfuse_propagation_context_stack_{id(self)}", default=None
        )
        # Note: the Langfuse client registers its span processor on the global
        # tracer provider on construction, so we grab the tracer afterwards.
        if tracer is None:
            tracer = (
                tracer_provider.get_tracer(BURR_TRACER_NAME)
                if tracer_provider is not None
                else trace.get_tracer(BURR_TRACER_NAME)
            )
        super().__init__(tracer=tracer)

    def _trace_attributes(
        self, app_id: str, partition_key: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        session_id = self.session_id if self.session_id is not None else app_id
        user_id = self.user_id if self.user_id is not None else partition_key
        return session_id, user_id

    def _set_trace_attributes(self, span: "trace.Span", app_id: str, partition_key: Optional[str]):
        # sets Langfuse trace-level attributes (session/user) on a span
        session_id, user_id = self._trace_attributes(app_id, partition_key)
        if session_id is not None:
            span.set_attribute(_LANGFUSE_SESSION_ID, session_id)
            span.set_attribute(_LANGFUSE_V3_SESSION_ID, session_id)
        if user_id is not None:
            span.set_attribute(_LANGFUSE_USER_ID, user_id)
            span.set_attribute(_LANGFUSE_V3_USER_ID, user_id)

    def _enter_trace_attribute_context(self, app_id: str, partition_key: Optional[str]) -> None:
        if propagate_attributes is None:  # langfuse < 3.9
            return
        session_id, user_id = self._trace_attributes(app_id, partition_key)
        propagation_context = propagate_attributes(session_id=session_id, user_id=user_id)
        propagation_context.__enter__()
        stack = (self._propagation_context_stack.get() or [])[:]
        stack.append(propagation_context)
        self._propagation_context_stack.set(stack)

    def _exit_trace_attribute_context(self) -> None:
        if propagate_attributes is None:  # nothing was entered
            return
        stack = (self._propagation_context_stack.get() or [])[:]
        if not stack:
            logger.warning("No Langfuse trace attribute context to exit")
            return
        propagation_context = stack.pop()
        self._propagation_context_stack.set(stack)
        propagation_context.__exit__(None, None, None)

    def pre_run_execute_call(
        self,
        *,
        app_id: str,
        partition_key: str,
        state: "State",
        method: ExecuteMethod,
        **future_kwargs: Any,
    ):
        super().pre_run_execute_call(method=method, **future_kwargs)
        span = get_current_span()
        # trace-level attributes must be present on the root span
        self._set_trace_attributes(span, app_id, partition_key)
        span.set_attribute(_LANGFUSE_OBSERVATION_METADATA_PREFIX + "burr.app_id", app_id)
        if partition_key is not None:
            span.set_attribute(
                _LANGFUSE_OBSERVATION_METADATA_PREFIX + "burr.partition_key", partition_key
            )
        if self.capture_state:
            span.set_attribute(
                _LANGFUSE_OBSERVATION_INPUT, _serialize_for_langfuse(state.get_all())
            )
        # Langfuse's propagation context copies session/user attributes to all child
        # spans, including spans emitted by third-party OpenTelemetry instrumentation.
        self._enter_trace_attribute_context(app_id, partition_key)

    def post_run_execute_call(
        self,
        *,
        state: "State",
        exception: Optional[Exception],
        **future_kwargs: Any,
    ):
        try:
            if self.capture_state and exception is None:
                span = get_current_span()
                span.set_attribute(
                    _LANGFUSE_OBSERVATION_OUTPUT, _serialize_for_langfuse(state.get_all())
                )
        finally:
            try:
                self._exit_trace_attribute_context()
            finally:
                super().post_run_execute_call(exception=exception, **future_kwargs)

    def pre_run_step(
        self,
        *,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        state: "State",
        action: "Action",
        inputs: Dict[str, Any],
        **future_kwargs: Any,
    ):
        super().pre_run_step(action=action, **future_kwargs)
        span = get_current_span()
        # set session/user on every span so Langfuse session/user aggregations cover all observations, not just the trace root:
        # https://langfuse.com/integrations/native/opentelemetry
        self._set_trace_attributes(span, app_id, partition_key)
        span.set_attribute(_LANGFUSE_OBSERVATION_METADATA_PREFIX + "burr.sequence_id", sequence_id)
        if self.capture_state:
            span.set_attribute(
                _LANGFUSE_OBSERVATION_INPUT,
                _serialize_for_langfuse(
                    {
                        "inputs": {
                            key: value for key, value in inputs.items() if not key.startswith("__")
                        },
                        "state": {key: state.get(key) for key in action.reads},
                    }
                ),
            )

    def post_run_step(
        self,
        *,
        state: "State",
        action: "Action",
        result: Optional[Dict[str, Any]],
        exception: Exception,
        **future_kwargs: Any,
    ):
        if self.capture_state and exception is None:
            span = get_current_span()
            span.set_attribute(
                _LANGFUSE_OBSERVATION_OUTPUT,
                _serialize_for_langfuse(
                    {
                        "result": result,
                        "state": {key: state.get(key) for key in action.writes},
                    }
                ),
            )
        super().post_run_step(exception=exception, **future_kwargs)

    def pre_start_span(
        self,
        *,
        span: "ActionSpan",
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        super().pre_start_span(span=span, **future_kwargs)
        self._set_trace_attributes(get_current_span(), app_id, partition_key)

    def do_log_attributes(
        self,
        *,
        attributes: Dict[str, Any],
        **future_kwargs: Any,
    ):
        otel_span = get_current_span()
        if otel_span is None:
            logger.warning(
                "Attempted to log attributes from the tracker outside of a span, ignoring"
            )
            return
        otel_span.set_attributes(
            {
                (
                    key
                    if key.startswith(_PASSTHROUGH_ATTRIBUTE_PREFIXES)
                    else _LANGFUSE_OBSERVATION_METADATA_PREFIX + key
                ): _convert_attribute(value)
                for key, value in attributes.items()
            }
        )
