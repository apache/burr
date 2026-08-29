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
import datetime
import enum
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

import burr.common.types as burr_types

if TYPE_CHECKING:
    # type-checking-only for a circular import
    from burr.core import State, Action, ApplicationGraph
    from burr.visibility import ActionSpan

from burr.lifecycle.internal import lifecycle


@lifecycle.base_hook("pre_run_step")
class PreRunStepHook(abc.ABC):
    """Hook that runs before a step is executed"""

    @abc.abstractmethod
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
        """Run before a step is executed.

        :param state: State prior to step execution
        :param action: Action to be executed
        :param inputs: Inputs to the action
        :param sequence_id: Sequence ID of the action
        :param future_kwargs: Future keyword arguments
        """
        pass


@lifecycle.base_hook("pre_run_step")
class PreRunStepHookAsync(abc.ABC):
    """Async hook that runs before a step is executed"""

    @abc.abstractmethod
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
        """Async run before a step is executed.

        :param state: State prior to step execution
        :param action: Action to be executed
        :param inputs: Inputs to the action
        :param sequence_id: Sequence ID of the action
        :param future_kwargs: Future keyword arguments
        """
        pass


@lifecycle.base_hook("post_run_step")
class PostRunStepHook(abc.ABC):
    """Hook that runs after a step is executed"""

    @abc.abstractmethod
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
        """Run after a step is executed.

        :param state: State after step execution
        :param action: Action that was executed
        :param result: Result of the action
        :param sequence_id: Sequence ID of the action
        :param exception: Exception that was raised
        :param future_kwargs: Future keyword arguments
        """
        pass


@lifecycle.base_hook("post_run_step")
class PostRunStepHookAsync(abc.ABC):
    """Async hook that runs after a step is executed"""

    @abc.abstractmethod
    async def post_run_step(
        self,
        *,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        state: "State",
        action: "Action",
        result: Optional[dict],
        exception: Exception,
        **future_kwargs: Any,
    ):
        """Async run after a step is executed

        :param state: State after step execution
        :param action: Action that was executed
        :param result: Result of the action
        :param sequence_id: Sequence ID of the action
        :param exception: Exception that was raised
        :param future_kwargs: Future keyword arguments
        """
        pass


@lifecycle.base_hook("post_application_create")
class PostApplicationCreateHook(abc.ABC):
    """Synchronous hook that runs post instantiation of an ``Application``
    object (after ``.build()`` is called on the ``ApplicationBuilder`` object.)"""

    @abc.abstractmethod
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
        """Runs after an "application" object is instantiated. This is run by the Application, in its constructor,
        as the last step.

        :param app_id: Application ID
        :param partition_key: Partition key of application
        :param state: Current state of the application
        :param application_graph: Application graph of the application, representing the state machine
        :param parent_pointer: Forking parent pointer of the application (application that it copied from)
        :param spawning_parent_pointer: Spawning parent pointer of the application (application that it was launched from)
        :param future_kwargs: Future keyword arguments for backwards compatibility
        """
        pass


@lifecycle.base_hook("pre_start_span")
class PreStartSpanHook(abc.ABC):
    """Hook that runs before a span is started in the tracing API.
    This can be either a context manager or a logger of sorts."""

    @abc.abstractmethod
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
        pass


@lifecycle.base_hook("pre_start_span")
class PreStartSpanHookAsync(abc.ABC):
    @abc.abstractmethod
    async def pre_start_span(
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
        pass


@lifecycle.base_hook("do_log_attributes")
class DoLogAttributeHook(abc.ABC):
    """Hook that is responsible for logging attributes,
    called by the tracer."""

    @abc.abstractmethod
    def do_log_attributes(
        self,
        *,
        attributes: Dict[str, Any],
        action: str,
        action_sequence_id: int,
        span: Optional["ActionSpan"],
        tags: dict,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass


@lifecycle.base_hook("do_log_attributes")
class DoLogAttributeHookAsync(abc.ABC):
    """Hook that runs after a span is ended in the tracing API.
    This can be either a context manager or a logger."""

    @abc.abstractmethod
    async def do_log_attributes(
        self,
        *,
        attributes: Dict[str, Any],
        action: str,
        action_sequence_id: int,
        span: "ActionSpan",
        tags: dict,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass


@lifecycle.base_hook("post_end_span")
class PostEndSpanHook(abc.ABC):
    """Hook that runs after a span is ended in the tracing API.
    This can be either a context manager or a logger."""

    @abc.abstractmethod
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
        pass


@lifecycle.base_hook("post_end_span")
class PostEndSpanHookAsync(abc.ABC):
    """Hook that runs at the end of an async span"""

    @abc.abstractmethod
    async def post_end_span(
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
        pass


class ExecuteMethod(enum.Enum):
    """A set of the application methods the user can call.
    These correspond to interface methods in application.py, and
    allow us to say *which* method is being called for the following hooks."""

    step = "step"
    astep = "astep"
    iterate = "iterate"
    aiterate = "aiterate"
    run = "run"
    arun = "arun"
    stream_result = "stream_result"
    astream_result = "astream_result"
    stream_iterate = "stream_iterate"
    astream_iterate = "astream_iterate"


@lifecycle.base_hook("pre_run_execute_call")
class PreApplicationExecuteCallHook(abc.ABC):
    """Hook that runs before an application method (step/iterate/run/stream...) is called."""

    @abc.abstractmethod
    def pre_run_execute_call(
        self,
        *,
        app_id: str,
        partition_key: str,
        state: "State",
        method: ExecuteMethod,
        **future_kwargs: Any,
    ):
        pass


@lifecycle.base_hook("pre_run_execute_call")
class PreApplicationExecuteCallHookAsync(abc.ABC):
    """Hook that runs before an async application method (step/iterate/run/stream...) is called."""

    @abc.abstractmethod
    async def pre_run_execute_call(
        self,
        *,
        app_id: str,
        partition_key: str,
        state: "State",
        method: ExecuteMethod,
        **future_kwargs,
    ):
        pass


@lifecycle.base_hook("post_run_execute_call")
class PostApplicationExecuteCallHook(abc.ABC):
    """Hook that runs after an application method (step/iterate/run/stream...) is called."""

    @abc.abstractmethod
    def post_run_execute_call(
        self,
        *,
        app_id: str,
        partition_key: str,
        state: "State",
        method: ExecuteMethod,
        exception: Optional[BaseException],
        **future_kwargs,
    ):
        pass


@lifecycle.base_hook("post_run_execute_call")
class PostApplicationExecuteCallHookAsync(abc.ABC):
    """Hook that runs after an async application method (step/iterate/run/stream...) is called."""

    @abc.abstractmethod
    async def post_run_execute_call(
        self,
        *,
        app_id: str,
        partition_key: str,
        state: "State",
        method: ExecuteMethod,
        exception: Optional[BaseException],
        **future_kwargs,
    ):
        pass


@lifecycle.base_hook("pre_start_stream")
class PreStartStreamHook(abc.ABC):
    """Hook that runs after a stream is started.
    If you have a generator, this gets run directly when the generator is called.
    """

    @abc.abstractmethod
    def pre_start_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass


@lifecycle.base_hook("pre_start_stream")
class PreStartStreamHookAsync(abc.ABC):
    """Hook that runs after a stream is started.
    If you have a generator, this gets run directly when the generator is called.
    """

    @abc.abstractmethod
    async def pre_start_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass


@lifecycle.base_hook("post_stream_item")
class PostStreamItemHook(abc.ABC):
    """Hook that runs after a stream item is yielded"""

    @abc.abstractmethod
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
        pass


@lifecycle.base_hook("post_stream_item")
class PostStreamItemHookAsync(abc.ABC):
    """Hook that runs after a stream item is yielded"""

    @abc.abstractmethod
    async def post_stream_item(
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
        pass


@lifecycle.base_hook("post_end_stream")
class PostEndStreamHook(abc.ABC):
    """Hook that runs after a stream is ended"""

    @abc.abstractmethod
    def post_end_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass


@lifecycle.base_hook("post_end_stream")
class PostEndStreamHookAsync(abc.ABC):
    """Hook that runs after a stream is ended"""

    @abc.abstractmethod
    async def post_end_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        pass


# strictly for typing -- this conflicts a bit with the lifecycle decorator above, but its fine for now
# This makes IDE completion/type-hinting easier
LifecycleAdapter = Union[
    DoLogAttributeHook,
    PreRunStepHook,
    PreRunStepHookAsync,
    PostRunStepHook,
    PostRunStepHookAsync,
    PreApplicationExecuteCallHook,
    PreApplicationExecuteCallHookAsync,
    PostApplicationExecuteCallHook,
    PostApplicationExecuteCallHookAsync,
    PostApplicationCreateHook,
    PreStartSpanHook,
    PreStartSpanHookAsync,
    PostEndSpanHook,
    PostEndSpanHookAsync,
    PreStartStreamHook,
    PostStreamItemHook,
    PostEndStreamHook,
    PreStartStreamHookAsync,
    PostStreamItemHookAsync,
    PostEndStreamHookAsync,
]
