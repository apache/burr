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

import abc
import asyncio
import contextlib
import dataclasses
import datetime
import importlib
import importlib.metadata
import json
import logging
import random
import sys
import weakref
from contextvars import ContextVar
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from burr.integrations.base import require_plugin

logger = logging.getLogger(__name__)

try:
    from opentelemetry import context
    from opentelemetry import context as context_api
    from opentelemetry import trace
    from opentelemetry.sdk.trace import Span, SpanProcessor, TracerProvider
    from opentelemetry.trace import get_current_span, use_span
except ImportError as e:
    require_plugin(
        e,
        "opentelemetry",
    )

from burr.common import types as burr_types
from burr.core import Action, ApplicationGraph, State, serde
from burr.lifecycle import (
    PostApplicationExecuteCallHook,
    PostRunStepHook,
    PreApplicationExecuteCallHook,
    PreRunStepHook,
)
from burr.lifecycle.base import (
    DoLogAttributeHook,
    ExecuteMethod,
    PostApplicationCreateHook,
    PostEndSpanHook,
    PostEndStreamHook,
    PostRunStepHookAsync,
    PostStreamItemHook,
    PreRunStepHookAsync,
    PreStartSpanHook,
    PreStartStreamHook,
)
from burr.tracking import LocalTrackingClient
from burr.tracking.base import AsyncTrackingClient, SyncTrackingClient, TrackingClient
from burr.visibility import ActionSpan

# We have to keep track of tokens for the span
# As OpenTel has some weird behavior around context managers, we have to account for the latest ones we started
# This way we can pop one off and know where to set the current one (as the parent, when the next one ends)
token_stack = ContextVar[Optional[List[Tuple[object, Span]]]]("token_stack", default=None)


@dataclasses.dataclass
class FullSpanContext:
    action_span: ActionSpan
    partition_key: str
    app_id: str
    # The tracker that owns this span. Spans can end on a thread where tracker_context is unset,
    # so we carry the tracker with the span instead of relying only on the context var.
    tracker: Optional[SyncTrackingClient] = None


span_map = {}


def cache_span(span: Span, context: FullSpanContext) -> Span:
    span_map[span.get_span_context().span_id] = context
    return span


def uncache_span(span: Span) -> Span:
    span_map.pop(span.get_span_context().span_id, None)
    return span


def get_cached_span(span_id: int) -> Optional[FullSpanContext]:
    return span_map.get(span_id)


tracker_context = ContextVar[Optional[SyncTrackingClient]]("tracker_context", default=None)


def _is_homogeneous_sequence(value: Sequence):
    if len(value) == 0:
        return True
    first_type = type(value[0])
    return all([isinstance(val, first_type) for val in value])


def convert_to_otel_attribute(attr: Any):
    if isinstance(attr, (str, bool, float, int)):
        return attr
    elif isinstance(attr, Sequence):
        if _is_homogeneous_sequence(attr):
            return list(attr)
    try:
        return json.dumps(serde.serialize(attr))
    except Exception as e:
        logger.error(f"Failed to serialize attribute: {attr}, got error: {e}")
        return str(attr)


def _exit_span(exc: Optional[Exception] = None):
    """Ditto with _enter_span, but for exiting the span. Pops the token off the stack and detaches the context."""
    stack = token_stack.get()[:]
    token, span = stack.pop()
    token_stack.set(stack)
    context.detach(token)
    if exc:
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
    else:
        span.set_status(trace.Status(trace.StatusCode.OK))
    span.end()
    return span


def _enter_span(name: str, tracer: trace.Tracer):
    """Utility function to enter a span. Starts, sets the current context, and adds it to the token stack.

    See this for some background on why start_span doesn't really work. We could use start_as_current_span,
    but this is a bit more explicit.
    """
    span, token = _enter_span_with_token(name, tracer)
    stack = (token_stack.get() or [])[:]
    stack.append((token, span))
    token_stack.set(stack)
    return span


def _enter_span_with_token(name: str, tracer: trace.Tracer) -> Tuple["Span", object]:
    """Like :py:func:`_enter_span`, but returns the raw context token without touching the stack.

    The asynchronous tracker keeps the token itself (see
    :py:meth:`AsyncOpenTelemetryTracker.pre_run_step`) and detaches it in
    :py:meth:`AsyncOpenTelemetryTracker.post_run_step`. Both hooks are awaited in the *same*
    task -- ``call_all_lifecycle_hooks_sync_and_async`` deliberately does not use
    ``asyncio.gather`` -- so the token stays valid for the whole step, the step span is current
    while the action runs, and ``detach`` really restores the context.

    Do **not** try to reset this token from a ``contextvars.copy_context()`` snapshot: a
    ``ContextVar.Token`` can only be reset in the Context that created it, and OpenTelemetry
    silently logs ``Failed to detach context`` when that rule is broken.
    """
    span = tracer.start_span(
        name=name,
        record_exception=False,  # we'll handle this ourselves
        set_status_on_exception=False,
    )
    token = context.attach(trace.set_span_in_context(span))
    return span, token


def _exit_span_direct(span: "Span", token: object, exc: Optional[Exception] = None) -> "Span":
    """Restores the context with the original token and ends ``span``, exactly once.

    ``context.detach`` is called directly, with no ``try/except``: a failed detach is a real bug
    (it means the token came from another Context) and must surface rather than be logged away.
    The ``finally`` still guarantees the span is ended even if detach did fail, so no span is
    left dangling and no error is hidden.
    """
    try:
        context.detach(token)
    finally:
        if exc:
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
        else:
            span.set_status(trace.Status(trace.StatusCode.OK))
        span.end()
    return span


class _StreamActionName:
    """Minimal stand-in so ``_start_step_span`` can be used from a stream hook.

    Stream hooks receive ``action`` as a *name* (str), while step hooks receive an ``Action``.
    ``_start_step_span`` only ever reads ``action.name``.
    """

    def __init__(self, name: str):
        self.name = name


_STREAM_KEY_PREFIX = "__stream_step__:"


def _end_span(span: "Span", exc: Optional[Exception] = None) -> "Span":
    """Sets the span's status and ends it, without touching the context.

    Used when the context token has already been detached -- by an ``action_scope`` that was
    entered and exited around the action -- so only the span's own lifecycle is left to close.
    """
    if exc:
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
    else:
        span.set_status(trace.Status(trace.StatusCode.OK))
    span.end()
    return span


class OpenTelemetryBridge(
    PreApplicationExecuteCallHook,
    PostApplicationExecuteCallHook,
    PreRunStepHook,
    PostRunStepHook,
    PreStartSpanHook,
    PostEndSpanHook,
    DoLogAttributeHook,
):
    """Adapter to log Burr events to OpenTelemetry. At a high level, this works as follows:

    1. On any of the start/pre hooks (pre_run_execute_call, pre_run_step, pre_start_span), we start a new span
    2. On any of the post ones we exit the span, accounting for the error (setting it if needed)
    3. On do_log_attributes, we log the attributes to the current span -- these are serialized using the serde module

    This works by logging to OpenTelemetry, and setting the span processor to be the right one (that knows about the tracker).

    You can use this as follows:

    .. code-block:: python

        # replace with instructions from your prefered vendor
        my_vendor_library_or_tracer_provider.init()

        app = (
            ApplicationBuilder()
            .with_entrypoint("prompt")
            .with_state(chat_history=[])
            .with_graph(graph)
            .with_hooks(OpenTelemetryBridge())
            .build()
        )

        app.run() # will log to OpenTelemetry
    """

    def __init__(self, tracer_name: str = None, tracer: trace.Tracer = None):
        """Initializes an OpenTel adapter. Passes in a tracer_name or a tracer object,
        should only pass one.

        :param tracer_name: Name of the tracer if you want it to initialize for you -- not including it will use a default
        :param tracer: Tracer object if you want to pass it in yourself
        """
        if tracer_name and tracer:
            raise ValueError(
                f"Only pass in one of tracer_name or tracer, not both, got: tracer_name={tracer_name} and tracer={tracer}"
            )
        if tracer:
            self.tracer = tracer
        else:
            self.tracer = trace.get_tracer(__name__ if tracer_name is None else tracer_name)

    def pre_run_execute_call(
        self,
        *,
        method: ExecuteMethod,
        **future_kwargs: Any,
    ):
        # TODO -- handle links -- we need to wire this through
        _enter_span(method.value, self.tracer)

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
            {key: convert_to_otel_attribute(value) for key, value in attributes.items()}
        )

    def pre_run_step(
        self,
        *,
        action: "Action",
        **future_kwargs: Any,
    ):
        _enter_span(action.name, self.tracer)

    def pre_start_span(
        self,
        *,
        span: "ActionSpan",
        **future_kwargs: Any,
    ):
        _enter_span(span.name, self.tracer)

    def post_end_span(
        self,
        *,
        span: "ActionSpan",
        **future_kwargs: Any,
    ):
        # TODO -- wire through exceptions
        _exit_span()

    def post_run_step(
        self,
        *,
        exception: Exception,
        **future_kwargs: Any,
    ):
        _exit_span(exception)

    def post_run_execute_call(
        self,
        *,
        exception: Optional[Exception],
        **future_kwargs,
    ):
        _exit_span(exception)


class _OpenTelemetryTrackerBase:
    """Shared implementation for the synchronous and asynchronous OpenTelemetry trackers.

    This class deliberately inherits **no** lifecycle hook. The two concrete subclasses below
    wrap the same ``burr_tracker`` and open/close the same OpenTelemetry span, but one registers
    the synchronous step hooks and the other the asynchronous ones -- registering both on a
    single class would run every step's hooks twice, since asynchronous applications dispatch
    both hook families.

    Everything here is shared: the span lifecycle, span caching, the tracker context, delegation
    of the non-step hooks, and the ``copy()`` contract.

    The synchronous, non-step hooks (``post_application_create``, the span hooks, attribute
    logging, the stream hooks) live on :py:class:`_OpenTelemetrySyncHooks` below, which inherits
    the matching ``Pre*/Post*Hook`` bases so that
    :py:class:`~burr.lifecycle.internal.LifecycleAdapterSet` -- which reads one ``SYNC_HOOK``
    attribute per class in the MRO -- registers each of them. Both concrete trackers inherit from
    it, since both have to dispatch those hooks exactly once, synchronously.
    """

    def __init__(self, burr_tracker: TrackingClient):
        initialize_tracer()
        self.tracer = trace.get_tracer("burr.integrations.opentelemetry")
        self.burr_tracker = burr_tracker

    def _start_step_span(
        self,
        *,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        action: "Action",
        register_in_stack: bool = False,
    ) -> Tuple[Span, object]:
        """Marks the wrapped tracker as the current tracker and opens the step's span.

        Called *after* the wrapped tracker's ``pre_run_step`` has completed, so the span starts
        once the step's data has been logged. Returns the span and the context token, which the
        caller must detach in the same task (see :py:func:`_exit_span_direct`).

        ``register_in_stack`` is for the synchronous wrapper, whose ``post_run_step`` closes the
        span through the historical :py:func:`_exit_span` context-local stack. The asynchronous
        wrapper keeps the token on the instance and detaches it directly instead, so it must not
        also push onto that stack.
        """
        tracker_context.set(self.burr_tracker)
        span, token = _enter_span_with_token(action.name, self.tracer)
        if register_in_stack:
            stack = (token_stack.get() or [])[:]
            stack.append((token, span))
            token_stack.set(stack)
        cache_span(
            span,
            FullSpanContext(
                action_span=ActionSpan.create_initial(
                    action=action.name,
                    name=action.name,
                    sequence_id=0,
                    action_sequence_id=sequence_id,
                ),
                partition_key=partition_key,
                app_id=app_id,
                tracker=self.burr_tracker,
            ),
        )
        return span, token

    def _end_step_span(
        self,
        exception: Optional[Exception],
        span: Optional[Span] = None,
        token: Optional[object] = None,
    ):
        """Closes the step's span and clears the tracker context -- see :py:meth:`_start_step_span`.

        With ``span``/``token`` (the hook-attached path) the original token is detached directly in
        the calling task. With ``span`` but no ``token`` the context has already been restored by
        the ``action_scope``, so only the span is ended. Without them (the synchronous path) the
        historical context-local stack is used. ``tracker_context`` is always cleared, even if the
        span could not be closed.
        """
        try:
            if span is None:
                _exit_span(exception)
            elif token is None:
                _end_span(span, exception)
            else:
                _exit_span_direct(span, token, exception)
        finally:
            tracker_context.set(None)

    @abc.abstractmethod
    def copy(self):
        """Returns a new tracker wrapping a copy of the underlying tracking client."""
        pass


class _OpenTelemetrySyncHooks(
    _OpenTelemetryTrackerBase,
    PostApplicationCreateHook,
    PreStartSpanHook,
    PostEndSpanHook,
    DoLogAttributeHook,
    PreStartStreamHook,
    PostStreamItemHook,
    PostEndStreamHook,
):
    """The synchronous, non-step hooks shared by both OpenTelemetry trackers.

    Burr dispatches ``post_application_create``, the span hooks, attribute logging and the stream
    hooks synchronously even for asynchronous applications (the span processor calls the span
    hooks from whichever thread ends the span). Both trackers therefore own exactly one copy of
    them: delegation to ``burr_tracker`` plus, for the span hooks, the OpenTelemetry span itself.

    Inheriting the ``Pre*/Post*Hook`` bases is what makes
    :py:class:`~burr.lifecycle.internal.LifecycleAdapterSet` dispatch these hooks --
    ``@lifecycle.base_hook`` sets one ``SYNC_HOOK`` attribute per base class, and the adapter set
    walks the MRO collecting them. Implementing a hook here without inheriting its base would
    leave it undispatched (the wrapped tracker would never see ``post_application_create``, and
    so would never open its log file).

    ``do_log_attributes`` deliberately does **not** delegate: attributes belong on the
    OpenTelemetry span. They are also outside the async-serde boundary -- attribute values are
    logged as plain values, so an async deserializer/serializer is not awaited here.
    """

    def post_application_create(
        self,
        *,
        app_id: str,
        partition_key: Optional[str],
        state: "State",
        application_graph: "ApplicationGraph",
        parent_pointer: Optional[burr_types.ParentPointer],
        spawning_parent_pointer: Optional[burr_types.ParentPointer],
        **future_kwargs: Any,
    ):
        self.burr_tracker.post_application_create(
            app_id=app_id,
            partition_key=partition_key,
            state=state,
            application_graph=application_graph,
            parent_pointer=parent_pointer,
            spawning_parent_pointer=spawning_parent_pointer,
        )

    def pre_start_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        return self.burr_tracker.pre_start_stream(
            action=action,
            sequence_id=sequence_id,
            app_id=app_id,
            partition_key=partition_key,
            **future_kwargs,
        )

    def post_stream_item(
        self,
        *,
        item: Any,
        item_index: int,
        stream_initialize_time: datetime.datetime,
        first_stream_item_start_time: datetime.datetime,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        return self.burr_tracker.post_stream_item(
            item=item,
            item_index=item_index,
            stream_initialize_time=stream_initialize_time,
            first_stream_item_start_time=first_stream_item_start_time,
            action=action,
            sequence_id=sequence_id,
            app_id=app_id,
            partition_key=partition_key,
            **future_kwargs,
        )

    def post_end_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        return self.burr_tracker.post_end_stream(
            action=action,
            sequence_id=sequence_id,
            app_id=app_id,
            partition_key=partition_key,
            **future_kwargs,
        )

    def do_log_attributes(
        self,
        *,
        attributes: Dict[str, Any],
        action: str,
        action_sequence_id: int,
        span: Optional["ActionSpan"],
        tags: dict,
        **future_kwargs: Any,
    ):
        # Note: this does not delegate to the wrapped tracker -- attributes go onto the
        # OpenTelemetry span instead of the Burr log, exactly as the synchronous tracker has
        # always done. Attribute logging therefore stays outside the async-serde boundary, and
        # remains synchronous even when the wrapped tracker is asynchronous.
        otel_span = get_current_span()
        if otel_span is None:
            # TODO -- see if this shows up then make it a les aggressive error
            raise ValueError("No current span")
        otel_span.set_attributes(
            {key: convert_to_otel_attribute(value) for key, value in attributes.items()}
        )

    def pre_start_span(
        self,
        *,
        action: str,
        action_sequence_id: int,
        span: "ActionSpan",
        span_dependencies: list[str],
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        otel_span = _enter_span(span.name, self.tracer)
        return otel_span

    def post_end_span(
        self,
        *,
        action: str,
        action_sequence_id: int,
        span: "ActionSpan",
        span_dependencies: list[str],
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        # TODO -- wire through exceptions
        _exit_span()


class OpenTelemetryTracker(
    _OpenTelemetrySyncHooks,
    SyncTrackingClient,
):
    """Tracker that includes logging of OpenTelemetry events. Note you will be unlikely to instantiate this directly,
    rather, you will instantiate it through with_tracker(use_oteL_tracing=True) on the ApplicationBuilder.

    At a high level, this:
    1. Logs all events to OpenTelemetry
    2. Adds a span processor to opentelemetry

    This wraps a synchronous tracking client -- for an asynchronous one use
    :py:class:`AsyncOpenTelemetryTracker`.

    Note that this globally sets a tracer provider -- it is possible that this will interfere with
    other tracers, and we are actively investigating it.
    TODO -- add stream start/end to opentel + TTFS, etc...
    """

    def __init__(self, burr_tracker: SyncTrackingClient):
        super().__init__(burr_tracker)

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
        self.burr_tracker.pre_run_step(
            app_id=app_id,
            partition_key=partition_key,
            sequence_id=sequence_id,
            state=state,
            action=action,
            inputs=inputs,
            **future_kwargs,
        )
        self._start_step_span(
            app_id=app_id,
            partition_key=partition_key,
            sequence_id=sequence_id,
            action=action,
            register_in_stack=True,
        )

    def post_run_step(
        self,
        *,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        state: "State",
        action: "Action",
        result: Optional[Dict[str, Any]],
        exception: Exception,
        **future_kwargs: Any,
    ):
        # The wrapped tracker can raise (log write failure, serializer error, ...). The span must
        # be closed either way, and its status must reflect the real failure rather than the
        # action's ``exception`` argument, which is None when the action itself succeeded.
        effective_exception: Optional[BaseException] = exception
        try:
            self.burr_tracker.post_run_step(
                app_id=app_id,
                partition_key=partition_key,
                sequence_id=sequence_id,
                state=state,
                action=action,
                result=result,
                exception=exception,
            )
        except BaseException as e:  # noqa: BLE001 - re-raised immediately, used for status only
            effective_exception = effective_exception or e
            raise
        finally:
            self._end_step_span(effective_exception)

    def copy(self):
        return OpenTelemetryTracker(burr_tracker=self.burr_tracker.copy())


class AsyncOpenTelemetryTracker(
    _OpenTelemetrySyncHooks,
    AsyncTrackingClient,
    PreRunStepHookAsync,
    PostRunStepHookAsync,
):
    """Asynchronous counterpart to :py:class:`OpenTelemetryTracker`, wrapping an
    :py:class:`~burr.tracking.base.AsyncTrackingClient`.

    Behavior is identical: the same step span, the same child spans/attributes from the span
    processor, the same delegation of the non-step hooks, the same ``copy()`` semantics. The one
    difference is that the wrapped tracker's ``pre_run_step``/``post_run_step`` are awaited.

    Only those two hooks are registered as asynchronous hooks; the remaining ones
    (``post_application_create``, ``pre_start_span``, ``post_end_span``, ``do_log_attributes``,
    the stream hooks) stay synchronous, matching how Burr dispatches them -- notably, the span
    processor calls ``pre_start_span``/``post_end_span`` synchronously from whichever thread ends
    the span.

    ``tracker_context`` and :py:class:`FullSpanContext` reference the *wrapped* async tracker, not
    this wrapper: the span processor only needs the synchronous span/attribute hooks, which the
    async tracker implements itself, so holding it directly keeps spans attached to the object
    that actually writes them.
    """

    def __init__(self, burr_tracker: AsyncTrackingClient):
        if isinstance(burr_tracker, SyncTrackingClient):
            raise ValueError(
                f"AsyncOpenTelemetryTracker wraps an asynchronous tracking client, but got"
                f" {type(burr_tracker).__name__}, which registers synchronous step hooks."
                f" Use OpenTelemetryTracker for synchronous trackers."
            )
        super().__init__(burr_tracker)
        # Open step spans, keyed by (app_id, partition_key, sequence_id, action name). The
        # ``pre``/``post`` hooks and the action all run in the same task now, but keeping the
        # open span on the instance (rather than in a ContextVar) still matters: it lets
        # ``post_run_step`` close the span in a ``finally`` even when the wrapped tracker raises
        # or the step is cancelled, and it makes concurrent applications that share one tracker
        # independent of each other.
        # Value is (span, token, task): the owning task lets a synchronous task-end callback
        # close spans whose ``post_run_step`` never ran because the step was cancelled.
        self._open_step_spans: Dict[
            Tuple[str, Optional[str], int, str], Tuple[Span, object, "asyncio.Task"]
        ] = {}
        self._tasks_with_cleanup: "weakref.WeakSet[asyncio.Task]" = weakref.WeakSet()

    def _ensure_task_end_cleanup(self) -> None:
        """Register a synchronous span-cleanup callback on the current task, once per task.

        A pending cancellation can surface before ``post_run_step`` starts (a cancel scope
        re-cancels the next await), so the step span would otherwise never be ended and the
        entry would stay in ``_open_step_spans``. Closing it from the task's done callback keeps
        the ASGI early-close contract intact -- the hook still does not run, nothing is
        persisted -- while releasing the span and the instance state. The callback is synchronous
        and only calls ``span.end()``; the task's context (and therefore any attached token) is
        already gone at that point, so there is nothing to detach.
        """
        try:
            task = asyncio.current_task()
        except RuntimeError:  # no running event loop
            return
        if task is None or task in self._tasks_with_cleanup:
            return
        self._tasks_with_cleanup.add(task)
        task.add_done_callback(self._close_spans_left_by_task)

    def _close_spans_left_by_task(self, task: "asyncio.Task") -> None:
        """Close spans opened by ``task`` that its post hook never closed (cancellation)."""
        if not self._open_step_spans:
            return
        leftover = [key for key, entry in self._open_step_spans.items() if entry[2] is task]
        for key in leftover:
            span, _token, _task = self._open_step_spans.pop(key)
            try:
                span.set_status(trace.Status(trace.StatusCode.ERROR, "step cancelled"))
            except Exception:  # noqa: BLE001 - best effort during teardown
                pass
            try:
                span.end()
            except Exception:  # noqa: BLE001 - best effort during teardown
                pass

    @staticmethod
    def _step_key(
        app_id: str, partition_key: Optional[str], sequence_id: int, action: "Action"
    ) -> Tuple[str, Optional[str], int, str]:
        return app_id, partition_key, sequence_id, action.name

    async def pre_run_step(
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
        # Deliberately does not open the step span. When asynchronous hooks are gathered, this
        # method runs in a throwaway task: a span opened here is closed by that task's done
        # callback before the action even starts, and the context token it returns can never be
        # detached. The span is opened by ``action_scope`` instead, in the task that runs the
        # action, which is the only context where "current span" means anything.
        await self.burr_tracker.pre_run_step(
            app_id=app_id,
            partition_key=partition_key,
            sequence_id=sequence_id,
            state=state,
            action=action,
            inputs=inputs,
            **future_kwargs,
        )

    @staticmethod
    def _stream_key(app_id, partition_key, sequence_id, action_name):
        # Distinct from _step_key so the asynchronous post_run_step (which is gathered into a
        # child Task) cannot pop and try to detach this span from the wrong Context.
        return (app_id, partition_key, sequence_id, _STREAM_KEY_PREFIX + action_name)

    def pre_start_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        """Open the streaming step span in the consuming task.

        Streaming actions never enter ``Application._astep`` and therefore never enter
        ``action_scope``; their body is consumed lazily by the caller. ``pre_start_stream`` and
        ``post_end_stream`` are synchronous hooks dispatched in that consuming task, so they are
        the correct integration boundary: the context token is created and detached in one task,
        and the span is current while the tokens are produced.
        """
        super().pre_start_stream(
            action=action,
            sequence_id=sequence_id,
            app_id=app_id,
            partition_key=partition_key,
            **future_kwargs,
        )
        named = _StreamActionName(action)
        span, token = self._start_step_span(
            app_id=app_id,
            partition_key=partition_key,
            sequence_id=sequence_id,
            action=named,
        )
        self._ensure_task_end_cleanup()
        self._open_step_spans[self._stream_key(app_id, partition_key, sequence_id, action)] = (
            span,
            token,
            asyncio.current_task(),
        )

    def post_end_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        """Close the streaming step span in the same task that opened it."""
        exc = future_kwargs.get("exception")
        clean_kwargs = {k: v for k, v in future_kwargs.items() if k != "exception"}
        try:
            super().post_end_stream(
                action=action,
                sequence_id=sequence_id,
                app_id=app_id,
                partition_key=partition_key,
                **clean_kwargs,
            )
        finally:
            key = self._stream_key(app_id, partition_key, sequence_id, action)
            entry = self._open_step_spans.pop(key, None)
            if entry is not None:
                span, token, _task = entry
                if token is not None:
                    self._end_step_span(exc, span=span, token=token)
                else:
                    self._end_step_span(exc, span=span)

    def action_scope(
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
        """Makes the step span current for the duration of the action.

        ``Application`` enters this in the task that runs the action, so the span is current
        while the action executes and the token is detached in the Context that created it.
        This is what decouples correct trace parenting from the hook dispatch strategy.
        """
        return self._step_scope(
            app_id=app_id,
            partition_key=partition_key,
            sequence_id=sequence_id,
            action=action,
        )

    @contextlib.contextmanager
    def _step_scope(
        self,
        *,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        action: "Action",
    ):
        span, token = self._start_step_span(
            app_id=app_id,
            partition_key=partition_key,
            sequence_id=sequence_id,
            action=action,
        )
        key = self._step_key(app_id, partition_key, sequence_id, action)
        # Registered on the task that owns the action, so a cancellation that skips
        # post_run_step still releases the span.
        self._ensure_task_end_cleanup()
        self._open_step_spans[key] = (span, token, asyncio.current_task())
        try:
            yield
        finally:
            entry = self._open_step_spans.get(key)
            if entry is not None:
                span, token, task = entry
                # Consume the token: post_run_step must only end the span, not detach again.
                self._open_step_spans[key] = (span, None, task)
                if token is not None:
                    context.detach(token)
            tracker_context.set(None)

    async def post_run_step(
        self,
        *,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        state: "State",
        action: "Action",
        result: Optional[Dict[str, Any]],
        exception: Exception,
        **future_kwargs: Any,
    ):
        # Strict exception-safety: the wrapped tracker's post hook performs the async
        # serialization/object-store I/O and can raise (serializer error, store I/O, log write
        # failure) or be cancelled. The span must be closed in *all* of those cases, so the
        # cleanup lives in a finally. ``_end_step_span`` detaches with the original token and
        # ends the span exactly once; no error is swallowed.
        key = self._step_key(app_id, partition_key, sequence_id, action)
        effective_exception: Optional[BaseException] = exception
        _stream_entry = self._open_step_spans.get(
            self._stream_key(app_id, partition_key, sequence_id, action.name)
        )
        if _stream_entry is not None and effective_exception is not None:
            try:
                _stream_entry[0].set_status(
                    trace.Status(trace.StatusCode.ERROR, str(effective_exception))
                )
            except Exception:  # noqa: BLE001 - best effort status update
                pass
        try:
            await self.burr_tracker.post_run_step(
                app_id=app_id,
                partition_key=partition_key,
                sequence_id=sequence_id,
                state=state,
                action=action,
                result=result,
                exception=exception,
            )
        except BaseException as e:  # noqa: BLE001 - re-raised immediately, used for status only
            # Covers the wrapped tracker raising *and* cancellation surfacing inside its body;
            # either way the span must not be reported as OK.
            effective_exception = effective_exception or e
            raise
        finally:
            entry = self._open_step_spans.pop(key, None)
            if entry is not None:
                span, token, _task = entry
                self._end_step_span(effective_exception, span=span, token=token)

    def copy(self):
        return AsyncOpenTelemetryTracker(burr_tracker=self.burr_tracker.copy())


class BurrTrackingSpanProcessor(SpanProcessor):
    @property
    def tracker(self):
        """Quick trick to get closer to the right tracker. This is suboptimal as we don't really
        have guarentees that we'll be *in* the right context when it gets logged, but the way OpenTel
        is implemented we will (with the immediate span processor). When the context is not set
        (e.g. a span ending on a worker thread), we fall back to the tracker cached with the span.
        """
        return tracker_context.get()

    def _tracker_for(self, cached_span: FullSpanContext) -> Optional[SyncTrackingClient]:
        tracker = self.tracker
        return tracker if tracker is not None else cached_span.tracker

    def on_start(
        self,
        span: "Span",
        parent_context: Optional[context_api.Context] = None,
    ) -> None:
        # First get the ID of the parent so we can retrieve from our cache
        parent_id = span.parent.span_id if span.parent is not None else None
        if parent_id is not None:
            parent_span = get_cached_span(span.parent.span_id)
            # If it exists, we can spawn a new span and cache that
            if parent_span is not None:
                tracker = self._tracker_for(parent_span)
                cache_span(
                    span,
                    context := FullSpanContext(
                        action_span=parent_span.action_span.spawn(span.name),
                        partition_key=parent_span.partition_key,
                        app_id=parent_span.app_id,
                        tracker=tracker,
                    ),
                )
                if tracker is not None:
                    tracker.pre_start_span(
                        action=context.action_span.action,
                        action_sequence_id=context.action_span.action_sequence_id,
                        span=context.action_span,
                        span_dependencies=[],  # TODO -- log
                        app_id=context.app_id,
                        partition_key=context.partition_key,
                    )

    def on_end(self, span: "Span") -> None:
        cached_span = get_cached_span(span.get_span_context().span_id)
        # If this is none it means we're outside of the burr context
        if cached_span is None:
            return
        # Always drop the entry first so it cannot leak, even if no tracker is found or logging fails
        uncache_span(span)
        tracker = self._tracker_for(cached_span)
        if tracker is not None:
            tracker.post_end_span(
                action=cached_span.action_span.action,
                action_sequence_id=cached_span.action_span.action_sequence_id,
                span=cached_span.action_span,
                span_dependencies=[],  # TODO -- log
                app_id=cached_span.app_id,
                partition_key=cached_span.partition_key,
            )
            if len(span.attributes) > 0:
                tracker.do_log_attributes(
                    attributes=dict(**span.attributes),
                    action=cached_span.action_span.action,
                    action_sequence_id=cached_span.action_span.action_sequence_id,
                    span=cached_span.action_span,
                    tags={},  # TODO -- log
                    app_id=cached_span.app_id,
                    partition_key=cached_span.partition_key,
                )


initialized = False


def initialize_tracer():
    """Initializes the tracer for OpenTel. Note this sets it globally.
    TODO -- ensure that it is initialized properly/do this in a cleaner manner.
    OpenTel does not make this easy as it's all global state.
    """
    global initialized
    if initialized:
        return
    initialized = True
    trace.set_tracer_provider(TracerProvider())
    trace.get_tracer_provider().add_span_processor(BurrTrackingSpanProcessor())


INSTRUMENTS_SPECS = {
    "openai": ("openai", "opentelemetry.instrumentation.openai", "OpenAIInstrumentor"),
    "anthropic": ("anthropic", "opentelemetry.instrumentation.anthropic", "AnthropicInstrumentor"),
    "cohere": ("cohere", "opentelemetry.instrumentation.cohere", "CohereInstrumentor"),
    "google_generativeai": (
        "google.generativeai",
        "opentelemetry.instrumentation.google_generativeai",
        "GoogleGenerativeAiInstrumentor",
    ),
    "mistral": ("mistralai", "opentelemetry.instrumentation.mistralai", "MistralAiInstrumentor"),
    "ollama": ("ollama", "opentelemetry.instrumentation.ollama", "OllamaInstrumentor"),
    "transformers": (
        "transformers",
        "opentelemetry.instrumentation.transformers",
        "TransformersInstrumentor",
    ),
    "together": ("together", "opentelemetry.instrumentation.together", "TogetherAiInstrumentor"),
    "bedrock": ("bedrock", "opentelemetry.instrumentation.bedrock", "BedrockInstrumentor"),
    "replicate": ("replicate", "opentelemetry.instrumentation.replicate", "ReplicateInstrumentor"),
    "vertexai": ("vertexai", "opentelemetry.instrumentation.vertexai", "VertexAIInstrumentor"),
    "groq": ("groq", "opentelemetry.instrumentation.groq", "GroqInstrumentor"),
    "watsonx": ("ibm-watsonx-ai", "opentelemetry.instrumentation.watsonx", "WatsonxInstrumentor"),
    "alephalpha": (
        "aleph_alpha_client",
        "opentelemetry.instrumentation.alephalpha",
        "AlephAlphaInstrumentor",
    ),
    "pinecone": ("pinecone", "opentelemetry.instrumentation.pinecone", "PineconeInstrumentor"),
    "qdrant": ("qdrant_client", "opentelemetry.instrumentation.qdrant", "QdrantInstrumentor"),
    "chroma": ("chromadb", "opentelemetry.instrumentation.chromadb", "ChromaInstrumentor"),
    "milvus": ("pymilvus", "opentelemetry.instrumentation.milvus", "MilvusInstrumentor"),
    "weaviate": ("weaviate", "opentelemetry.instrumentation.weaviate", "WeaviateInstrumentor"),
    "lancedb": ("lancedb", "opentelemetry.instrumentation.lancedb", "LanceInstrumentor"),
    "marqo": ("marqo", "opentelemetry.instrumentation.marqo", "MarqoInstrumentor"),
    "redis": ("redis", "opentelemetry.instrumentation.redis", "RedisInstrumentor"),
    "langchain": ("langchain", "opentelemetry.instrumentation.langchain", "LangchainInstrumentor"),
    "llama_index": (
        "llama_index",
        "opentelemetry.instrumentation.llamaindex",
        "LlamaIndexInstrumentor",
    ),
    "haystack": ("haystack", "opentelemetry.instrumentation.haystack", "HaystackInstrumentor"),
    "requests": ("requests", "opentelemetry.instrumentation.requests", "RequestsInstrumentor"),
    "httpx": ("httpx", "opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
    "urllib": ("urllib", "opentelemetry.instrumentation.urllib", "URLLibInstrumentor"),
    "urllib3": ("urllib3", "opentelemetry.instrumentation.urllib3", "URLLib3Instrumentor"),
}

INSTRUMENTS = Literal[
    "openai",
    "anthropic",
    "cohere",
    "google_generativeai",
    "mistral",
    "ollama",
    "transformers",
    "together",
    "bedrock",
    "replicate",
    "vertexai",
    "groq",
    "watsonx",
    "alephalpha",
    "pinecone",
    "qdrant",
    "chroma",
    "milvus",
    "weaviate",
    "lancedb",
    "marqo",
    "redis",
    "langchain",
    "llama_index",
    "haystack",
    "requests",
    "httpx",
    "urllib",
    "urllib3",
]


def available_dists() -> set[str]:
    """Get the name of all available libraries in the current environment.

    ref for importlib.metadata: https://docs.python.org/3.11/library/importlib.metadata.html#metadata
    """
    return set((dist.name for dist in importlib.metadata.distributions()))


def _init_instrument(
    module_name: str, instrumentation_module_name: str, instrumentor_name: str
) -> None:
    """Instrument a Python library.
    Instrumentation will be skipped if module is not imported nor found in `sys.modules`
    Exit early if the instrumentation module isn't installed in the current environment.

    :param module_name: Name of the top-level module to instrument (e.g., `requests`, `openai`)
    :param instrumentation_module_name: Name of the module containing the instrumentor (e.g., opentelemetry.instrumentation.requests)
    :param instrumentor_name: Name of the object that has the `.instrument()` method. (e.g., OpenAIInstrumentor)
    :return:
    """
    if module_name not in sys.modules:
        logger.debug(f"`{module_name}` wasn't imported. Skipping instrumentation.")
        return

    instrumentation_package_name = instrumentation_module_name.replace(".", "-")
    if instrumentation_package_name not in available_dists():
        logger.info(
            f"Couldn't instrument `{module_name}`. Package `{instrumentation_package_name}` is missing."
        )
        return

    try:
        instrumentation_module = importlib.import_module(instrumentation_module_name)
        instrumentor_cls = getattr(instrumentation_module, instrumentor_name)
        instrumentor = instrumentor_cls()
        if instrumentor.is_instrumented_by_opentelemetry:
            logger.debug(f"`{module_name}` is already instrumented.")
        else:
            instrumentor.instrument()
            logger.info(f"`{module_name}` is now instrumented.")

    except BaseException:
        logger.error(f"Failed to instrument `{module_name}` with `{instrumentation_package_name}`.")


def init_instruments(*instruments: INSTRUMENTS, init_all: bool = False) -> None:
    """Instruments the specified libraries, or all that are installed if it is enabled.

    This will check if any libraries are available in the current environment and
    initialize if they are. See the ``INSTRUMENTS_SPECS`` field for the list of
    available libraries.

    :param instruments: Name of libraries to instrument (e.g., `requests`, `openai`)
    :param init_all: If True, initialize all available instruments for imported packages.
    :return:
    """
    # if no instrument explicitly passed, default to trying to instrument all available packages
    if init_all:
        logger.debug("Instrumenting all libraries.")
        instruments = INSTRUMENTS_SPECS.keys()

    for instrument in instruments:
        specs = INSTRUMENTS_SPECS[instrument]
        module_name, instrumentation_module_name, instrumentor_name = specs

        _init_instrument(module_name, instrumentation_module_name, instrumentor_name)


if __name__ == "__main__":
    initialize_tracer()
    tracer = trace.get_tracer(__name__)
    tracker = LocalTrackingClient("otel_test")
    opentel_adapter = OpenTelemetryTracker(burr_tracker=tracker)

    import time

    from burr.core import ApplicationBuilder, Result, action, default, expr
    from burr.visibility import TracerFactory

    def slp():
        time.sleep(random.random())

    @action(reads=["count"], writes=["count"])
    def counter(state: State, __tracer: TracerFactory) -> State:
        with __tracer("foo"):
            slp()
            with __tracer("bar"):
                slp()
                with tracer.start_span("baz") as span:
                    with use_span(span, end_on_exit=True):
                        slp()
                    with tracer.start_as_current_span("qux"):
                        slp()
                    with tracer.start_as_current_span("quux"):
                        slp()
                    slp()

                slp()
        return state.update(count=state["count"] + 1)

    result_action = Result("count").with_name("result")
    app = (
        ApplicationBuilder()
        .with_actions(result_action, counter=counter)
        .with_transitions(("counter", "counter", expr("count<10")))
        .with_transitions(("counter", "result", default))
        .with_hooks(opentel_adapter)
        .with_entrypoint("counter")
        # .with_tracker(tracker)
        .with_state(count=0)
        .build()
    )
    app.run(halt_after=["result"])
