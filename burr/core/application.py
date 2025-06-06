from __future__ import annotations

import contextvars
import dataclasses
import functools
import inspect
import logging
import pprint
import uuid
from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import AbstractContextManager
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    Generator,
    Generic,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
    cast,
)

from burr import system, telemetry, visibility
from burr.common import types as burr_types
from burr.core import persistence, validation
from burr.core.action import (
    DEFAULT_SCHEMA,
    Action,
    AsyncStreamingAction,
    AsyncStreamingResultContainer,
    Condition,
    Function,
    Reducer,
    SingleStepAction,
    SingleStepStreamingAction,
    StreamingAction,
    StreamingResultContainer,
)
from burr.core.graph import Graph, GraphBuilder
from burr.core.persistence import (
    AsyncBaseStateLoader,
    AsyncBaseStateSaver,
    BaseStateLoader,
    BaseStateSaver,
)
from burr.core.state import State
from burr.core.typing import ActionSchema, DictBasedTypingSystem, TypingSystem
from burr.core.validation import BASE_ERROR_MESSAGE
from burr.lifecycle.base import ExecuteMethod, LifecycleAdapter, PostRunStepHook, PreRunStepHook
from burr.lifecycle.internal import LifecycleAdapterSet
from burr.visibility import tracing
from burr.visibility.tracing import tracer_factory_context_var

if TYPE_CHECKING:
    # TODO --  figure out whether we want to just do if TYPE_CHECKING
    # for all first-class imports as Ruff suggests...
    from burr.tracking.base import TrackingClient

logger = logging.getLogger(__name__)

PRIOR_STEP = "__PRIOR_STEP"
SEQUENCE_ID = "__SEQUENCE_ID"

StateType = TypeVar("StateType")
StateTypeToSet = TypeVar("StateTypeToSet")


def _validate_result(result: Any, name: str, schema: ActionSchema = DEFAULT_SCHEMA) -> None:
    # TODO -- split out the action schema into input/output schema types
    # Currently they're tied together, but this doesn't make as much sense for single-step actions
    result_type = schema.intermediate_result_type()
    if not isinstance(result, result_type):
        raise ValueError(
            f"Action {name} returned a non-{result_type.__name__} result: {result}. "
            f"All results must be dictionaries."
        )


def _raise_fn_return_validation_error(output: Any, action_name: str):
    raise ValueError(
        BASE_ERROR_MESSAGE
        + f"Single step action: {action_name} must return either *just* the newly updated State or a tuple of (result: dict, state: State). "
        f"Got: {output} of type {type(output)} instead, which is not valid."
    )


def _adjust_single_step_output(
    output: Union[State, Tuple[dict, State]],
    action_name: str,
    action_schema: ActionSchema,
):
    """Adjusts the output of a single step action to be a tuple of (result, state) or just state"""

    if isinstance(output, tuple):
        if not len(output) == 2:
            _raise_fn_return_validation_error(output, action_name)
        _validate_result(output[0], action_name, action_schema)
        if not isinstance(output[1], State):
            _raise_fn_return_validation_error(output, action_name)
        return output
    if isinstance(output, State):
        return {}, output
    _raise_fn_return_validation_error(output, action_name)


def _remap_dunder_parameters(
    run_method: Callable, inputs: Dict[str, Any], vars_to_remap: List[str]
) -> dict:
    """This is a utility function to remap the __dunder parameters to the mangled version in the function signature.

    Python mangles __parameter names in the function signature, so we need to remap it to the correct parameter name.

    :param run_method: the run method to inspect.
    :param inputs: the inputs to inspect
    :param vars_to_remap: the variables to remap
    :return: potentially new dict with the remapped variable, else the original dict.
    """
    # Get the signature of the method being run. This should be Function.run() or similar.
    signature = inspect.signature(run_method)
    mangled_params: Dict[str, Optional[str]] = {v: None for v in vars_to_remap}
    # Find the name-mangled __context variable
    for dunder_param in mangled_params.keys():
        for param in signature.parameters.values():
            if param.name.endswith(dunder_param):
                mangled_params[dunder_param] = param.name
                break

    # If any mangled __parameter is found, remap the value in inputs
    if any(mangled_params.values()):
        inputs = inputs.copy()
        for dunder_param, mangled_name in mangled_params.items():
            if mangled_name and dunder_param in inputs:
                inputs[mangled_name] = inputs.pop(dunder_param)
    return inputs


def _run_function(function: Function, state: State, inputs: Dict[str, Any], name: str) -> dict:
    """Runs a function, returning the result of running the function.
    Note this restricts the keys in the state to only those that the
    function reads.

    :param function: Function to run
    :param state: State at time of execution
    :param inputs: Inputs to the function
    :return:
    """
    if function.is_async():
        raise ValueError(
            f"Cannot run async: {name} "
            "in non-async context. Use astep()/aiterate()/arun() "
            "instead...)"
        )
    state_to_use = state.subset(*function.reads)
    function.validate_inputs(inputs)
    if "__context" in inputs or "__tracer" in inputs:
        # potentially need to remap the __context & __tracer variables
        inputs = _remap_dunder_parameters(function.run, inputs, ["__context", "__tracer"])
    result = function.run(state_to_use, **inputs)
    _validate_result(result, name)
    return result


async def _arun_function(
    function: Function, state: State, inputs: Dict[str, Any], name: str
) -> dict:
    """Runs a function, returning the result of running the function.
    Async version of the above."""
    state_to_use = state.subset(*function.reads)
    function.validate_inputs(inputs)
    result = await function.run(state_to_use, **inputs)
    _validate_result(result, name)
    return result


def _state_update(state_to_modify: State, modified_state: State) -> State:
    """Performs a state update for an action -- allowing for deletes.

    This is suboptimal -- we should not be observing the state, we should be using the state commands and layering in deltas.
    That said, we currently eagerly evaluate the state at all operations, which means we have to do it this way. See
    https://github.com/DAGWorks-Inc/burr/issues/33 for a more detailed plan.

    This function was written to solve this issue: https://github.com/DAGWorks-Inc/burr/issues/28.


    :param state_subset_pre_update: The subset of state passed to the update() function
    :param modified_state: The subset of state realized after the update() function
    :param state_to_modify: The state to modify-- this is the original
    :return:
    """
    # We want to wipe these, as these should never be changed by the action
    # an action that modifies these is going to incur "undefined behavior" -- we can effectively
    # do anything we want -- in this case we're dropping it, but we may error out in the future
    # This is really an issue in the case of parallelism -- E.G. when an action reduces multiple states
    # a common failure mode is to modify.
    # TODO -- unify the logic of choosing whether a key is internal or not
    private_fields = [item for item in modified_state.keys() if item.startswith("__")]
    modified_state_without_private_fields = modified_state.wipe(delete=private_fields)
    # we filter here as we don't want to
    deleted_keys = [
        item
        for item in (
            set(state_to_modify.keys()) - set(modified_state_without_private_fields.keys())
        )
        if not item.startswith("__")
    ]
    return state_to_modify.merge(modified_state_without_private_fields).wipe(delete=deleted_keys)


def _validate_reducer_writes(reducer: Reducer, state: State, name: str) -> None:
    required_writes = reducer.writes
    missing_writes = set(reducer.writes) - state.keys()
    if len(missing_writes) > 0:
        raise ValueError(
            f"State is missing write keys after running: {name}. Missing keys are: {missing_writes}. "
            f"Has writes: {required_writes}"
        )


def _run_reducer(reducer: Reducer, state: State, result: dict, name: str) -> State:
    """Runs the reducer, returning the new state. Note this restricts the
    keys in the state to only those that the function writes.

    :param reducer:
    :param state:
    :param result:
    :return:
    """
    # TODO -- better guarding on state reads/writes
    new_state = reducer.update(result, state)
    keys_in_new_state = set(new_state.keys())
    new_keys = keys_in_new_state - set(state.keys())
    extra_keys = new_keys - set(reducer.writes)
    if len(extra_keys) > 0:
        raise ValueError(
            f"Action {name} attempted to write to keys {extra_keys} "
            f"that it did not declare. It declared: ({reducer.writes})!"
        )
    _validate_reducer_writes(reducer, new_state, name)
    return _state_update(state, new_state)


def _create_dict_string(kwargs: dict) -> str:
    """This is a utility function to create a string representation of a dict.
    This is the state that was passed into the function usually. This is useful for debugging,
    as it can be printed out to see what the state was.

    :param kwargs: The inputs to the function that errored.
    :return: The string representation of the inputs, truncated appropriately.
    """
    pp = pprint.PrettyPrinter(width=80)
    inputs = {}
    for k, v in kwargs.items():
        item_repr = repr(v)
        if len(item_repr) > 50:
            item_repr = item_repr[:50] + "..."
        else:
            item_repr = v
        inputs[k] = item_repr
    input_string = pp.pformat(inputs)
    if len(input_string) > 1000:
        input_string = input_string[:1000] + "..."
    return input_string


def _format_BASE_ERROR_MESSAGE(action: Action, input_state: State, inputs: dict) -> str:
    """Formats the error string, given that we're inside an action"""
    message = BASE_ERROR_MESSAGE
    message += f"> Action: `{action.name}` encountered an error!"
    padding = " " * (80 - len(message) - 1)
    message += padding + "<"
    message += "\n> State (at time of action):\n" + _create_dict_string(input_state.get_all())
    message += "\n> Inputs (at time of action):\n" + _create_dict_string(inputs)
    border = "*" * 80
    return "\n" + border + "\n" + message + "\n" + border


def _run_single_step_action(
    action: SingleStepAction, state: State, inputs: Optional[Dict[str, Any]]
) -> Tuple[Dict[str, Any], State]:
    """Runs a single step action. This API is internal-facing and a bit in flux, but
    it corresponds to the SingleStepAction class.

    :param action: Action to run
    :param state: State to run with
    :param inputs: Inputs to pass directly to the action
    :return: The result of running the action, and the new state
    """
    # TODO -- guard all reads/writes with a subset of the state
    action.validate_inputs(inputs)
    result, new_state = _adjust_single_step_output(
        action.run_and_update(state, **inputs), action.name, action.schema
    )
    _validate_result(result, action.name, action.schema)
    out = result, _state_update(state, new_state)
    _validate_reducer_writes(action, new_state, action.name)
    return out


def _run_single_step_streaming_action(
    action: SingleStepStreamingAction,
    state: State,
    inputs: Optional[Dict[str, Any]],
    sequence_id: int,
    app_id: str,
    partition_key: Optional[str],
    lifecycle_adapters: LifecycleAdapterSet = LifecycleAdapterSet(),
) -> Generator[Tuple[dict, Optional[State]], None, None]:
    """Runs a single step streaming action. This API is internal-facing.
    This normalizes + validates the output."""
    action.validate_inputs(inputs)
    stream_initialize_time = system.now()
    first_stream_start_time = None
    generator = action.stream_run_and_update(state, **inputs)
    result = None
    state_update = None
    count = 0
    for item in generator:
        if not isinstance(item, tuple):
            # TODO -- consider adding support for just returning a result.
            raise ValueError(
                f"Action {action.name} must yield a tuple of (result, state_update). "
                f"For all non-final results (intermediate),"
                f"the state update must be None"
            )
        result, state_update = item
        count += 1
        if state_update is None:
            if first_stream_start_time is None:
                first_stream_start_time = system.now()
            lifecycle_adapters.call_all_lifecycle_hooks_sync(
                "post_stream_item",
                item=result,
                item_index=count,
                stream_initialize_time=stream_initialize_time,
                first_stream_item_start_time=first_stream_start_time,
                action=action.name,
                app_id=app_id,
                partition_key=partition_key,
                sequence_id=sequence_id,
            )
            yield result, None

    if state_update is None:
        raise ValueError(
            f"Action {action.name} did not return a state update. For streaming actions, the last yield "
            f"statement must be a tuple of (result, state_update). For example, yield dict(foo='bar'), state.update(foo='bar')"
        )
    _validate_result(result, action.name, action.schema)
    _validate_reducer_writes(action, state_update, action.name)
    yield result, state_update


async def _arun_single_step_streaming_action(
    action: SingleStepStreamingAction,
    state: State,
    inputs: Optional[Dict[str, Any]],
    sequence_id: int,
    app_id: str,
    partition_key: Optional[str],
    lifecycle_adapters: LifecycleAdapterSet = LifecycleAdapterSet(),
) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
    """Runs a single step streaming action in async. See the synchronous version for more details."""
    action.validate_inputs(inputs)
    stream_initialize_time = system.now()
    first_stream_start_time = None
    generator = action.stream_run_and_update(state, **inputs)
    result = None
    state_update = None
    count = 0
    async for item in generator:
        if not isinstance(item, tuple):
            # TODO -- consider adding support for just returning a result.
            raise ValueError(
                f"Action {action.name} must yield a tuple of (result, state_update). "
                f"For all non-final results (intermediate),"
                f"the state update must be None"
            )
        result, state_update = item
        if state_update is None:
            if first_stream_start_time is None:
                first_stream_start_time = system.now()
            await lifecycle_adapters.call_all_lifecycle_hooks_sync_and_async(
                "post_stream_item",
                item=result,
                item_index=count,
                stream_initialize_time=stream_initialize_time,
                first_stream_item_start_time=first_stream_start_time,
                action=action.name,
                app_id=app_id,
                partition_key=partition_key,
                sequence_id=sequence_id,
            )
            count += 1
            yield result, None
    if state_update is None:
        raise ValueError(
            f"Action {action.name} did not return a state update. For async actions, the last yield "
            f"statement must be a tuple of (result, state_update). For example, yield dict(foo='bar'), state.update(foo='bar')"
        )
    # TODO -- add back in validation when we have a schema
    _validate_result(result, action.name, action.schema)
    _validate_reducer_writes(action, state_update, action.name)
    # TODO -- add guard against zero-length stream
    yield result, state_update


def _run_multi_step_streaming_action(
    action: StreamingAction,
    state: State,
    inputs: Optional[Dict[str, Any]],
    sequence_id: int,
    app_id: str,
    partition_key: Optional[str],
    lifecycle_adapters: LifecycleAdapterSet = LifecycleAdapterSet(),
) -> Generator[Tuple[dict, Optional[State]], None, None]:
    """Runs a multi-step streaming action. E.G. one with a run/reduce step.
    This API is internal-facing. Note that this converts the shape of a
    multi-step streaming action to yielding the results of the run step
    as well as the state update, which is None for all the finaly ones.

    This peeks ahead by one so we know when this is done (and when to validate).
    """
    action.validate_inputs(inputs)
    stream_initialize_time = system.now()
    generator = action.stream_run(state, **inputs)
    result = None
    first_stream_start_time = None
    count = 0
    for item in generator:
        # We want to peek ahead so we can return the last one
        # This is slightly eager, but only in the case in which we
        # are using a multi-step streaming action
        next_result = result
        result = item
        if next_result is not None:
            if first_stream_start_time is None:
                first_stream_start_time = system.now()
            lifecycle_adapters.call_all_lifecycle_hooks_sync(
                "post_stream_item",
                item=next_result,
                item_index=count,
                stream_initialize_time=stream_initialize_time,
                first_stream_item_start_time=first_stream_start_time,
                action=action.name,
                app_id=app_id,
                partition_key=partition_key,
                sequence_id=sequence_id,
            )
            count += 1
            yield next_result, None
    state_update = _run_reducer(action, state, result, action.name)
    _validate_result(result, action.name, action.schema)
    _validate_reducer_writes(action, state_update, action.name)
    yield result, state_update


async def _arun_multi_step_streaming_action(
    action: AsyncStreamingAction,
    state: State,
    inputs: Optional[Dict[str, Any]],
    sequence_id: int,
    app_id: str,
    partition_key: Optional[str],
    lifecycle_adapters: LifecycleAdapterSet = LifecycleAdapterSet(),
) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
    """Runs a multi-step streaming action in async. See the synchronous version for more details."""
    action.validate_inputs(inputs)
    stream_initialize_time = system.now()
    generator = action.stream_run(state, **inputs)
    result = None
    first_stream_start_time = None
    count = 0
    async for item in generator:
        # We want to peek ahead so we can return the last one
        # This is slightly eager, but only in the case in which we
        # are using a multi-step streaming action
        next_result = result
        result = item
        if next_result is not None:
            if first_stream_start_time is None:
                first_stream_start_time = system.now()
            await lifecycle_adapters.call_all_lifecycle_hooks_sync_and_async(
                "post_stream_item",
                item=next_result,
                stream_initialize_time=stream_initialize_time,
                item_index=count,
                first_stream_item_start_time=first_stream_start_time,
                action=action.name,
                app_id=app_id,
                partition_key=partition_key,
                sequence_id=sequence_id,
            )
            count += 1
            yield next_result, None
    state_update = _run_reducer(action, state, result, action.name)
    _validate_result(result, action.name, action.schema)
    _validate_reducer_writes(action, state_update, action.name)
    yield result, state_update


async def _arun_single_step_action(
    action: SingleStepAction, state: State, inputs: Optional[Dict[str, Any]]
) -> Tuple[dict, State]:
    """Runs a single step action in async. See the synchronous version for more details."""
    state_to_use = state
    action.validate_inputs(inputs)
    result, new_state = _adjust_single_step_output(
        await action.run_and_update(state_to_use, **inputs), action.name, action.schema
    )
    _validate_result(result, action.name, action.schema)
    _validate_reducer_writes(action, new_state, action.name)
    return result, _state_update(state, new_state)


@dataclasses.dataclass
class ApplicationGraph(Graph):
    """User-facing representation of the state machine. This has

    #. All the action objects
    #. All the transition objects
    #. The entrypoint action
    """

    entrypoint: Action


@dataclasses.dataclass
class ApplicationIdentifiers:
    app_id: str
    partition_key: Optional[str]
    sequence_id: Optional[int]


@dataclasses.dataclass
class ApplicationContext(AbstractContextManager, ApplicationIdentifiers):
    """Application context. This is anything your node might need to know about the application.
    Often used for recursive tracking.

    Note this is also a context manager (allowing you to pass context to sub-applications).

    To access this object in a running application, you can use the `__context` variable in the
    action signature:

    .. code-block:: python

        from burr.core import action, State, ApplicationContext

        @action(reads=[...], writes=[...])
        def my_action(state: State, __context: ApplicationContext) -> State:
            app_id = __context.app_id
            partition_key = __context.partition_key
            current_action_name = __context.action_name  # Access the current action name
            ...

    """

    tracker: Optional["TrackingClient"]
    parallel_executor_factory: Callable[[], Executor]
    state_initializer: Optional[BaseStateLoader]
    state_persister: Optional[BaseStateSaver]
    action_name: Optional[str]  # Store just the action name

    @staticmethod
    def get() -> Optional["ApplicationContext"]:
        """Provides the context-local application context.
        You can use this instead of declaring `__context` in an application.
        You really should only be using this if you're wiring through multiple layers of abstraction
        and want to connect two applications.

        :return: The ApplicationContext you'll want to use
        """
        return _application_context.get()

    def __enter__(self) -> "ApplicationContext":
        _application_context.set(self)
        return self

    def __exit__(self, __exc_type, __exc_value, __traceback):
        _application_context.set(None)


_application_context = contextvars.ContextVar[Optional[ApplicationContext]](
    "application_context", default=None
)
# The purpose of this is to ensure that we don't run the run call hooks multiple times
# We do this as some functions call out to others (but they do not call out to themselves, recursively)
# Thus we keep track of a sentinel, unique per execute method, which tells us if we have already logged
# If we want to call out recursively inside applications, we'll need to think this through
# That said, this is all context/thread safe -- multiple threads can call at the same time
# Furthermore, if one app delegates to another, their app ID will be different, so it will trace as well.
_run_call_var = contextvars.ContextVar[Optional[Dict[str, ExecuteMethod]]](
    "run_call_var", default=None
)

CallableT = TypeVar("CallableT")


class _call_execute_method_pre_post:
    """Wrapper class to ensure that the lifecycle hooks are called before/after application calls.
    This is not called for streaming as there is special logic involved "post-return" that we need to handle.
    We will likely add additional hooks for streaming as well, but for now these just decorate the function.
    This is not a publicly exposed API -- it is used internally to ensure that the lifecycle hooks are called.
    """

    def __init__(self, method: ExecuteMethod):
        self.method = method

    def call_pre(self, app) -> bool:
        if should_run_hooks := (app.uid not in _run_call_var.get({})):
            _run_call_var.set({**_run_call_var.get({}), **{app.uid: self.method}})
            app._adapter_set.call_all_lifecycle_hooks_sync(
                "pre_run_execute_call",
                app_id=app._uid,
                partition_key=app._partition_key,
                state=app.state,
                method=self.method,
            )
        return should_run_hooks

    def call_post(self, app, exc) -> bool:
        if should_run_hooks := (
            app.uid in _run_call_var.get(dict) and _run_call_var.get()[app.uid] == self.method
        ):
            _run_call_var.set({k: v for k, v in _run_call_var.get().items() if k != app.uid})
            app._adapter_set.call_all_lifecycle_hooks_sync(
                "post_run_execute_call",
                app_id=app.uid,
                partition_key=app._partition_key,
                state=app.state,
                method=self.method,
                exception=exc,
            )
        return should_run_hooks

    async def acall_pre(self, app) -> bool:
        if should_run_hooks := (app.uid not in _run_call_var.get({})):
            _run_call_var.set({**_run_call_var.get({}), **{app.uid: self.method}})
            await app._adapter_set.call_all_lifecycle_hooks_sync_and_async(
                "pre_run_execute_call",
                app_id=app._uid,
                partition_key=app._partition_key,
                state=app.state,
                method=self.method,
            )
        return should_run_hooks

    async def acall_post(self, app, exc) -> bool:
        if should_run_hooks := (
            app.uid in _run_call_var.get(dict) and _run_call_var.get()[app.uid] == self.method
        ):
            _run_call_var.set({k: v for k, v in _run_call_var.get().items() if k != app.uid})
            await app._adapter_set.call_all_lifecycle_hooks_sync_and_async(
                "post_run_execute_call",
                app_id=app._uid,
                partition_key=app._partition_key,
                state=app.state,
                method=self.method,
                exception=exc,
            )
        return should_run_hooks

    def __call__(self, fn: CallableT) -> CallableT:
        @functools.wraps(fn)
        async def wrapper_async(app_self, *args, **kwargs):
            # We only run at the top level, so we decorate it if we're there
            await self.acall_pre(app_self)
            exc = None
            try:
                return await fn(app_self, *args, **kwargs)
            finally:
                await self.acall_post(app_self, exc)

        @functools.wraps(fn)
        def wrapper_sync(app_self, *args, **kwargs):
            self.call_pre(app_self)
            exc = None
            try:
                return fn(app_self, *args, **kwargs)
            finally:
                self.call_post(app_self, exc)

        return wrapper_async if inspect.iscoroutinefunction(fn) else wrapper_sync


class TracerFactoryContextHook(PreRunStepHook, PostRunStepHook):
    """Passes the tracer factory into context. This allows us to do out-of-band visibility processing"""

    def __init__(self, adapter_set: LifecycleAdapterSet):
        self._adapter_set = adapter_set
        self.token_pointer_map = {}

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
        if "__tracer" in inputs:
            tracer_factory = inputs["__tracer"]
        else:
            tracer_factory = tracing.TracerFactory(
                action=action.name,
                app_id=app_id,
                lifecycle_adapters=self._adapter_set,
                partition_key=partition_key,
                sequence_id=sequence_id,
            )
        assert tracer_factory is not None
        # TODO -- store token/context manager by app_id, sequence_id
        self.token_pointer_map[(app_id, sequence_id)] = tracer_factory_context_var.set(
            tracer_factory
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
        try:
            tracer_factory_context_var.reset(self.token_pointer_map[(app_id, sequence_id)])
        except ValueError:  # Token var = ContextVar created in a different context
            # This occurs when we're at the finally block of an async streaming action
            logger.debug(
                "Token var = ContextVar created in a different context -- this happens with streaming APIs. "
                "See: https://github.com/open-telemetry/opentelemetry-python/issues/2606 for a similar issue"
            )
            tracer_factory_context_var.set(None)

        del self.token_pointer_map[(app_id, sequence_id)]


ApplicationStateType = TypeVar("ApplicationStateType")
StreamResultType = TypeVar("StreamResultType", bound=Union[dict, Any])


def _create_default_executor() -> Executor:
    return ThreadPoolExecutor()


class Application(Generic[ApplicationStateType]):
    def __init__(
        self,
        graph: Graph,
        state: State[ApplicationStateType],
        partition_key: Optional[str],
        uid: str,
        entrypoint: str,
        sequence_id: Optional[int] = None,
        adapter_set: Optional[LifecycleAdapterSet] = None,
        builder: Optional["ApplicationBuilder"] = None,
        fork_parent_pointer: Optional[burr_types.ParentPointer] = None,
        spawning_parent_pointer: Optional[burr_types.ParentPointer] = None,
        tracker: Optional["TrackingClient"] = None,
        parallel_executor_factory: Optional[Executor] = None,
        state_persister: Union[BaseStateSaver, LifecycleAdapter, None] = None,
        state_initializer: Union[BaseStateLoader, LifecycleAdapter, None] = None,
    ):
        """Instantiates an Application. This is an internal API -- use the builder!

        :param actions: Actions to run
        :param transitions: Transitions between actions
        :param state: State to run with
        :param initial_step: Step name to start at
        :param partition_key: Partition key for the application (optional)
        :param uid: Unique identifier for the application
        :param sequence_id: Sequence ID for the application. Note this will be incremented every run.
            So if this starts at 0, the first one you will see will be 1.
        :param adapter_set: Set of lifecycle adapters
        :param builder: Builder that created this application
        """
        self._partition_key = partition_key
        self._uid = uid
        self.entrypoint = entrypoint

        self._graph = graph
        self._public_facing_graph = ApplicationGraph(
            actions=graph.actions,
            transitions=graph.transitions,
            entrypoint=graph.get_action(entrypoint),
        )
        self._state = state
        adapter_set = adapter_set if adapter_set is not None else LifecycleAdapterSet()
        self._adapter_set = adapter_set.with_new_adapters(TracerFactoryContextHook(adapter_set))
        # TODO -- consider adding global inputs + global input factories to the builder
        self._tracker = tracker

        if sequence_id is not None:
            self._set_sequence_id(sequence_id)
        self._builder = builder
        self._parent_pointer = fork_parent_pointer
        self._parallel_executor_factory = (
            parallel_executor_factory
            if parallel_executor_factory is not None
            else _create_default_executor
        )
        self._dependency_factory = {
            "__tracer": functools.partial(
                visibility.tracing.TracerFactory,
                lifecycle_adapters=self._adapter_set,
                app_id=self._uid,
                partition_key=self._partition_key,
            ),
            "__context": self._context_factory,
        }
        self._spawning_parent_pointer = spawning_parent_pointer
        self._state_initializer = state_initializer
        self._state_persister = state_persister
        self._adapter_set.call_all_lifecycle_hooks_sync(
            "post_application_create",
            state=self._state,
            application_graph=self._public_facing_graph,
            app_id=self._uid,
            partition_key=self._partition_key,
            parent_pointer=fork_parent_pointer,
            spawning_parent_pointer=spawning_parent_pointer,
        )

    # @telemetry.capture_function_usage # todo -- capture usage when we break this up into one that isn't called internally
    # This will be doable when we move sequence ID to the beginning of the function https://github.com/DAGWorks-Inc/burr/pull/73
    @_call_execute_method_pre_post(ExecuteMethod.step)
    def step(self, inputs: Optional[Dict[str, Any]] = None) -> Optional[Tuple[Action, dict, State]]:
        """Performs a single step, advancing the state machine along.
        This returns a tuple of the action that was run, the result of running
        the action, and the new state.

        Use this if you just want to do something with the state and not rely on generators.
        E.G. press forward/backwards, human in the loop, etc... Odds are this is not
        the method you want -- you'll want iterate() (if you want to see the state/
        results along the way), or run() (if you just want the final state/results).

        :param inputs: Inputs to the action -- this is if this action requires an input that is passed in from the outside world
        :return: Tuple[Function, dict, State] -- the function that was just ran, the result of running it, and the new state
        """
        # we need to increment the sequence before we start computing
        # that way if we're replaying from state, we don't get stuck
        self.validate_correct_async_use()
        self._increment_sequence_id()
        out = self._step(inputs=inputs, _run_hooks=True)
        return out

    def _context_factory(self, action: Action, sequence_id: int) -> ApplicationContext:
        """Helper function to create an application context, in the form of the dependency factories we inject to nodes."""
        return ApplicationContext(
            app_id=self._uid,
            tracker=self._tracker,
            partition_key=self._partition_key,
            sequence_id=sequence_id,
            parallel_executor_factory=self._parallel_executor_factory,
            state_initializer=self._state_initializer,
            state_persister=self._state_persister,
            action_name=action.name if action else None,  # Pass just the action name
        )

    def _step(
        self, inputs: Optional[Dict[str, Any]], _run_hooks: bool = True
    ) -> Optional[Tuple[Action, dict, State]]:
        """Internal-facing version of step. This is the same as step, but with an additional
        parameter to hide hook execution so async can leverage it."""
        with self.context:
            next_action = self.get_next_action()
            if next_action is None:
                return None
            if inputs is None:
                inputs = {}
            action_inputs = self._process_inputs(inputs, next_action)
            if _run_hooks:
                self._adapter_set.call_all_lifecycle_hooks_sync(
                    "pre_run_step",
                    action=next_action,
                    state=self._state,
                    inputs=action_inputs,
                    sequence_id=self.sequence_id,
                    app_id=self._uid,
                    partition_key=self._partition_key,
                )
            exc = None
            result = None
            new_state = self._state
            try:
                if next_action.single_step:
                    result, new_state = _run_single_step_action(
                        next_action, self._state, action_inputs
                    )
                else:
                    result = _run_function(
                        next_action, self._state, action_inputs, name=next_action.name
                    )
                    new_state = _run_reducer(next_action, self._state, result, next_action.name)

                new_state = self._update_internal_state_value(new_state, next_action)
                self._set_state(new_state)
            except Exception as e:
                exc = e
                logger.exception(_format_BASE_ERROR_MESSAGE(next_action, self._state, inputs))
                raise e
            finally:
                if _run_hooks:
                    self._adapter_set.call_all_lifecycle_hooks_sync(
                        "post_run_step",
                        app_id=self._uid,
                        partition_key=self._partition_key,
                        action=next_action,
                        state=new_state,
                        result=result,
                        sequence_id=self.sequence_id,
                        exception=exc,
                    )
            return next_action, result, new_state

    def reset_to_entrypoint(self) -> None:
        """Resets the state machine to the entrypoint action -- you probably want to consider having a loop
        in your graph, but this will do the trick if you need it!"""
        self._set_state(self._state.wipe(delete=[PRIOR_STEP]))

    def _update_internal_state_value(
        self, new_state: State[ApplicationStateType], next_action: Action
    ) -> State[ApplicationStateType]:
        """Updates the internal state values of the new state."""
        new_state = new_state.update(
            **{
                PRIOR_STEP: next_action.name,
            }
        )
        return new_state

    def _process_inputs(self, inputs: Dict[str, Any], action: Action) -> Dict[str, Any]:
        """Processes inputs, injecting the common inputs and ensuring that all required inputs are present."""
        starting_with_double_underscore = {key for key in inputs.keys() if key.startswith("__")}
        if len(starting_with_double_underscore) > 0:
            raise ValueError(
                BASE_ERROR_MESSAGE
                + f"Inputs starting with a double underscore ({starting_with_double_underscore}) "
                f"are reserved for internal use/injected inputs."
                "Please do not directly pass keys starting with a double underscore."
            )
        inputs = inputs.copy()
        processed_inputs = {}
        required_inputs, optional_inputs = action.optional_and_required_inputs
        for key in list(inputs.keys()):
            if key in required_inputs or key in optional_inputs:
                processed_inputs[key] = inputs.pop(key)
        if len(inputs) > 0 and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Keys {inputs.keys()} were passed in as inputs to action "
                f"{action.name}, but not declared by the action as an input. "
                f"Action only needs: {required_inputs} (optionally: {optional_inputs}) "
                f"so we're just letting you know some inputs are being skipped."
            )
        missing_inputs = required_inputs - set(processed_inputs.keys())
        additional_inputs = optional_inputs - set(processed_inputs.keys())
        for input_ in missing_inputs | additional_inputs:
            # if we can find it in the dependency factory, we'll use that
            # TODO -- figure out what happens if people attempt to override default factory
            # inputs
            if input_ in self._dependency_factory:
                processed_inputs[input_] = self._dependency_factory[input_](
                    action, self.sequence_id
                )
                if input_ in missing_inputs:
                    missing_inputs.remove(input_)
        if len(missing_inputs) > 0:
            missing_inputs_dict = {key: "FILL ME IN" for key in missing_inputs}
            missing_inputs_dict.update({key: "..." for key in inputs.keys()})
            addendum = (
                "\nPlease double check the values passed to the keyword argument `inputs` to however you're running "
                "the burr application.\n"
                "e.g.\n"
                f"   app.run( # or app.step, app.iterate, app.astep, etc.\n"
                f"       halt_..., # your halt logic\n"
                f"       inputs={missing_inputs_dict}  # <-- this is what you need to adjust\n"
                f"   )"
            )
            raise ValueError(
                f"Action {action.name} is missing required inputs: {missing_inputs}. "
                f"Has inputs: {processed_inputs}. " + addendum
            )
        return processed_inputs

    # @telemetry.capture_function_usage
    # ditto with step()
    @_call_execute_method_pre_post(ExecuteMethod.astep)
    async def astep(
        self, inputs: Optional[Dict[str, Any]] = None
    ) -> Optional[Tuple[Action, dict, State[ApplicationStateType]]]:
        """Asynchronous version of step.

        :param inputs: Inputs to the action -- this is if this action
            requires an input that is passed in from the outside world

        :return: Tuple[Function, dict, State] -- the action that was just ran, the result of running it, and the new state
        """
        self._increment_sequence_id()
        out = await self._astep(inputs=inputs, _run_hooks=True)
        return out

    async def _astep(self, inputs: Optional[Dict[str, Any]], _run_hooks: bool = True):
        # we want to increment regardless of failure
        with self.context:
            next_action = self.get_next_action()
            if next_action is None:
                return None
            if inputs is None:
                inputs = {}
            action_inputs = self._process_inputs(inputs, next_action)
            if _run_hooks:
                await self._adapter_set.call_all_lifecycle_hooks_sync_and_async(
                    "pre_run_step",
                    action=next_action,
                    state=self._state,
                    inputs=action_inputs,
                    sequence_id=self.sequence_id,
                    app_id=self._uid,
                    partition_key=self._partition_key,
                )
            exc = None
            result = None
            new_state = self._state
            try:
                if not next_action.is_async():
                    # we can just delegate to the synchronous version, it will block the event loop,
                    # but that's safer than assuming its OK to launch a thread
                    # TODO -- add an option/configuration to launch a thread (yikes, not super safe, but for a pure function
                    # which this is supposed to be its OK).
                    # this delegates hooks to the synchronous version, so we'll call all of them as well
                    next_action, result, new_state = self._step(
                        inputs=action_inputs, _run_hooks=False
                    )  # Skip hooks as we already ran all of them/will run all of them in this function's finally
                    return next_action, result, new_state
                if next_action.single_step:
                    result, new_state = await _arun_single_step_action(
                        next_action, self._state, inputs=action_inputs
                    )
                else:
                    result = await _arun_function(
                        next_action,
                        self._state,
                        inputs=action_inputs,
                        name=next_action.name,
                    )
                    new_state = _run_reducer(next_action, self._state, result, next_action.name)
                new_state = self._update_internal_state_value(new_state, next_action)
                self._set_state(new_state)
            except Exception as e:
                exc = e
                logger.exception(_format_BASE_ERROR_MESSAGE(next_action, self._state, inputs))
                raise e
            finally:
                if _run_hooks:
                    await self._adapter_set.call_all_lifecycle_hooks_sync_and_async(
                        "post_run_step",
                        action=next_action,
                        state=new_state,
                        result=result,
                        sequence_id=self.sequence_id,
                        exception=exc,
                        app_id=self._uid,
                        partition_key=self._partition_key,
                    )

            return next_action, result, new_state

    def _parse_action_list(self, action_list: list[str]) -> Tuple[List[str], List[str]]:
        """Utility function to parse a list of actions/tags into a list of actions and a list of tags."""
        actions = []
        tags = []
        for action in action_list:
            if action.startswith("@tag"):
                tags.append(action[len("@tag:") :])
            else:
                actions.append(action)
        return actions, tags

    def _process_control_flow_params(
        self,
        halt_before: list[str] = None,
        halt_after: list[str] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Tuple[list[str], list[str], Dict[str, Any]]:
        """Utility function to clean out iterate params so we have less duplication between iterate/aiterate
        and the logic is cleaner later.
        """
        if halt_before is None and halt_after is None:
            logger.warning(
                "No halt termination specified -- this has the possibility of running forever!"
            )
        halt_before = halt_before or []
        halt_after = halt_after or []
        inputs = inputs or {}
        halt_before_actions, halt_before_tags = self._parse_action_list(halt_before)
        halt_after_actions, halt_after_tags = self._parse_action_list(halt_after)
        halt_before_expanded = set(halt_before_actions)
        for tag in halt_before_tags:
            halt_before_expanded.update([item.name for item in self.graph.get_actions_by_tag(tag)])
        halt_after_expanded = set(halt_after_actions)
        for tag in halt_after_tags:
            halt_after_expanded.update([item.name for item in self.graph.get_actions_by_tag(tag)])
        return list(halt_before_expanded), list(halt_after_expanded), inputs

    def _validate_halt_conditions(self, halt_before: list[str], halt_after: list[str]) -> None:
        """Utility function to validate halt conditions"""
        missing_actions = set(halt_before + halt_after) - set(
            action.name for action in self.graph.actions
        )
        if len(missing_actions) > 0:
            raise ValueError(
                BASE_ERROR_MESSAGE
                + f"Halt conditions {missing_actions} are not registered actions. Please ensure that they have been "
                f"registered as actions in the application and that you've spelled them correctly!"
                f"Valid actions are: {[action.name for action in self.graph.actions]}"
            )

    def has_next_action(self) -> bool:
        """Returns whether or not there is a next action to run.

        :return: True if there is a next action, False otherwise
        """
        return self.get_next_action() is not None

    def _should_halt_iterate(
        self, halt_before: list[str], halt_after: list[str], prior_action: Action
    ) -> bool:
        """Internal utility function to determine whether or not to halt during iteration"""
        if self.has_next_action() and self.get_next_action().name in halt_before:
            logger.debug(f"Halting before executing {self.get_next_action().name}")
            return True
        elif prior_action.name in halt_after:
            logger.debug(f"Halting after executing {prior_action.name}")
            return True
        return False

    def _return_value_iterate(
        self,
        halt_before: list[str],
        halt_after: list[str],
        prior_action: Optional[Action],
        result: Optional[dict],
    ) -> Tuple[Optional[Action], Optional[dict], State[ApplicationStateType]]:
        """Utility function to decide what to return for iterate/arun. Note that run() will delegate to the return value of
        iterate, whereas arun cannot delegate to the return value of aiterate (as async generators cannot return a value).
        We put the code centrally to clean up the logic.
        """
        if self.has_next_action() and self.get_next_action().name in halt_before:
            logger.debug(
                f"We have hit halt_before condition with next action: {self.get_next_action().name}. "
                f"Returning: next_action={self.get_next_action()}, None, and state"
            )
            return self.get_next_action(), None, self._state
        if prior_action is not None and prior_action.name in halt_after:
            prior_action_name = prior_action.name if prior_action is not None else None
            logger.debug(
                f"We have hit halt_after condition with prior action: {prior_action_name}. "
                f"Returning: prior_action={prior_action}, result, and state"
            )
            return prior_action, result, self._state
        logger.warning(
            "This is trying to return without having computed a single action -- "
            "we'll end up just returning some Nones. This means that nothing was executed "
            "(E.G. that the state machine had nowhere to go). Either fix the state machine or"
            f"the halt conditions, or both... Halt conditions are: halt_before={halt_before}, halt_after={halt_after}."
            f"Note that this is considered undefined behavior -- if you get here, you should fix!"
        )
        return prior_action, result, self._state

    @telemetry.capture_function_usage
    @_call_execute_method_pre_post(ExecuteMethod.iterate)
    def iterate(
        self,
        *,
        halt_before: list[str] = None,
        halt_after: list[str] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Generator[
        Tuple[Action, dict, State[ApplicationStateType]],
        None,
        Tuple[Action, Optional[dict], State[ApplicationStateType]],
    ]:
        """Returns a generator that calls step() in a row, enabling you to see the state
        of the system as it updates. Note this returns a generator, and also the final result
        (for convenience).

        Note that tags must be specified by the form "@tag:<tag_name>" to differentiate them from actions.

        Note the nuance with halt_before and halt_after. halt_before conditions will take precedence to halt_after. Furthermore,
        a single iteration will always be executed prior to testing for any halting conditions.

        :param halt_before: The list of actions/tags to halt before execution of. It will halt prior to the execution of the first one it sees.
        :param halt_after: The list of actions/tags to halt after execution of. It will halt after the execution of the first one it sees.
        :param inputs: Inputs to the action -- this is if this action requires an input that is passed in from the outside world.
            Note that this is only used for the first iteration -- subsequent iterations will not use this.
        :return: Each iteration returns the result of running `step`. This generator also returns a tuple of
            [action, result, current state]
        """
        self.validate_correct_async_use()
        halt_before, halt_after, inputs = self._process_control_flow_params(
            halt_before,
            halt_after,
            inputs,
        )
        self._validate_halt_conditions(halt_before, halt_after)

        result = None
        prior_action: Optional[Action] = None
        while self.has_next_action():
            # self.step will only return None if there is no next action, so we can rely on tuple unpacking
            prior_action, result, state = self.step(inputs=inputs)
            yield prior_action, result, state
            if self._should_halt_iterate(halt_before, halt_after, prior_action):
                break
        return self._return_value_iterate(halt_before, halt_after, prior_action, result)

    @telemetry.capture_function_usage
    @_call_execute_method_pre_post(ExecuteMethod.aiterate)
    async def aiterate(
        self,
        *,
        halt_before: list[str] = None,
        halt_after: list[str] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Tuple[Action, dict, State[ApplicationStateType]], None]:
        """Returns a generator that calls step() in a row, enabling you to see the state
        of the system as it updates. This is the asynchronous version so it has no capability of t

        Note that tags must be specified by the form "@tag:<tag_name>" to differentiate them from actions.

        :param halt_before: The list of actions/tags to halt before execution of. It will halt on the first one.
        :param halt_after: The list of actions/tags to halt after execution of. It will halt on the first one.
        :param inputs: Inputs to the action -- this is if this action requires an input that is passed in from the outside world.
            Note that this is only used for the first iteration -- subsequent iterations will not use this.
        :return: Each iteration returns the result of running `step`. This returns nothing -- it's an async generator which is not
            allowed to have a return value.
        """
        halt_before, halt_after, inputs = self._process_control_flow_params(
            halt_before, halt_after, inputs
        )
        self._validate_halt_conditions(halt_before, halt_after)
        while self.has_next_action():
            # self.step will only return None if there is no next action, so we can rely on tuple unpacking
            prior_action, result, state = await self.astep(inputs=inputs)
            yield prior_action, result, state
            if self._should_halt_iterate(halt_before, halt_after, prior_action):
                break

    @telemetry.capture_function_usage
    @_call_execute_method_pre_post(ExecuteMethod.run)
    def run(
        self,
        *,
        halt_before: list[str] = None,
        halt_after: list[str] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Action, Optional[dict], State[ApplicationStateType]]:
        """Runs your application through until completion. Does
        not give access to the state along the way -- if you want that, use iterate().

        Note that tags must be specified by the form "@tag:<tag_name>" to differentiate them from actions.

        :param halt_before: The list of actions/tags to halt before execution of. It will halt on the first one.
        :param halt_after: The list of actions/tags to halt after execution of. It will halt on the first one.
        :param inputs: Inputs to the action -- this is if this action requires an input that is passed in from the outside world.
            Note that this is only used for the first iteration -- subsequent iterations will not use this.
        :return: The final state, and the results of running the actions in the order that they were specified.
        """
        self.validate_correct_async_use()
        gen = self.iterate(halt_before=halt_before, halt_after=halt_after, inputs=inputs)
        while True:
            try:
                next(gen)
            except StopIteration as e:
                result = e.value
                return result

    @telemetry.capture_function_usage
    @_call_execute_method_pre_post(ExecuteMethod.arun)
    async def arun(
        self,
        *,
        halt_before: list[str] = None,
        halt_after: list[str] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Action, Optional[dict], State]:
        """Runs your application through until completion, using async. Does
        not give access to the state along the way -- if you want that, use iterate().

        Note that tags must be specified by the form "@tag:<tag_name>" to differentiate them from actions.

        :param halt_before: The list of actions/tags to halt before execution of. It will halt on the first one.
        :param halt_after: The list of actions/tags to halt after execution of. It will halt on the first one.
        :param inputs: Inputs to the action -- this is if this action requires an input that is passed in from the outside world
        :return: The final state, and the results of running the actions in the order that they were specified.
        """

        prior_action = None
        result = None
        halt_before, halt_after, inputs = self._process_control_flow_params(
            halt_before, halt_after, inputs
        )
        self._validate_halt_conditions(halt_before, halt_after)
        async for prior_action, result, state in self.aiterate(
            halt_before=halt_before, halt_after=halt_after, inputs=inputs
        ):
            pass
        return self._return_value_iterate(halt_before, halt_after, prior_action, result)

    @telemetry.capture_function_usage
    def stream_result(
        self,
        halt_after: list[str],
        halt_before: Optional[list[str]] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Action, StreamingResultContainer[ApplicationStateType, Union[dict, Any]]]:
        """Streams a result out.

        :param halt_after: The list of actions/tags to halt after execution of. It will halt on the first one.
        :param halt_before: The list of actions/tags to halt before execution of. It will halt on the first one. Note that
            if this is met, the streaming result container will be empty (and return None) for the result, having an empty generator.
        :param inputs: Inputs to the action -- this is if this action requires an input that is passed in from the outside world
        :return: A streaming result container, which is a generator that will yield results as they come in, as well as cache/give you the final result,
            and update state accordingly.

        This is meant to be used with streaming actions -- :py:meth:`streaming_action <burr.core.action.streaming_action>`
        or :py:class:`StreamingAction <burr.core.action.StreamingAction>` It returns a
        :py:class:`StreamingResultContainer <burr.core.action.StreamingResultContainer>`, which has two capabilities:

        1. It is a generator that streams out the intermediate results of the action
        2. It has a ``.get()`` method that returns the final result of the action, and the final state.

        If ``.get()`` is called before the generator is exhausted, it will block until the generator is exhausted.

        While this container is meant to work with streaming actions, it can also be used with non-streaming actions. In this case,
        the generator will be empty, and the ``.get()`` method will return the final result and state.

        The rules for halt_before and halt_after are the same as for :py:meth:`iterate <burr.core.application.Application.iterate>`,
        and :py:meth:`run <burr.core.application.Application.run>`. In this case, `halt_before` will indicate a *non* streaming action,
        which will be empty. Thus ``halt_after`` takes precedence -- if it is met, the streaming result container will contain the result of the
        halt_after condition.

        The :py:class:`StreamingResultContainer <burr.core.action.StreamingResultContainer>` is meant as a convenience -- specifically this allows for
        hooks, callbacks, etc... so you can take the control flow and still have state updated afterwards. Hooks/state update will be called after an exception
        is thrown during streaming, or the stream is completed. Note that it is undefined behavior to attempt to execute another action while a stream is in progress.


        To see how this works, let's take the following action (simplified as a single-node workflow) as an example:

        .. code-block:: python

            @streaming_action(reads=[], writes=['response'])
            def streaming_response(state: State, prompt: str) -> Generator[dict, None, Tuple[dict, State]]:
                response = client.chat.completions.create(
                    model='gpt-3.5-turbo',
                    messages=[{
                        'role': 'user',
                        'content': prompt
                        }],
                    temperature=0,
                )
                buffer = []
                for chunk in response:
                    delta = chunk.choices[0].delta.content
                    buffer.append(delta)
                    # yield partial results
                    yield {'response': delta}, None # indicate that we are not done by returning a `None` state!
                full_response = ''.join(buffer)
                # return the final result
                yield {'response': full_response}, state.update(response=full_response)

        To use streaming_result, you pass in names of streaming actions (such as the one above) to the halt_after
        parameter:

        .. code-block:: python

            application = ApplicationBuilder().with_actions(streaming_response=streaming_response)...build()
            prompt = "Count to 100, with a comma between each number and no newlines. E.g., 1, 2, 3, ..."
            action, streaming_result = application.stream_result(halt_after='streaming_response', inputs={"prompt": prompt})
            for result in streaming_result:
                print(result['response']) # one by one

            result, state = streaming_result.get()
            print(result) #  all at once

        Note that if you have multiple halt_after conditions, you can use the ``.action`` attribute to get the action that
        was run.

        .. code-block:: python

            application = ApplicationBuilder().with_actions(
                streaming_response=streaming_response,
                error=error # another function that outputs an error, streaming
            )...build()
            prompt = "Count to 100, with a comma between each number and no newlines. E.g., 1, 2, 3, ..."
            action, streaming_result = application.stream_result(halt_after='streaming_response', inputs={"prompt": prompt})
            color = "red" if action.name == "error" else "green"
            for result in streaming_result:
                print(format(result['response'], color)) # assumes that error and streaming_response both have the same output shape

        .. code-block:: python

            application = ApplicationBuilder().with_actions(
                streaming_response=streaming_response,
                error=non_streaming_error # a non-streaming function that outputs an error
            )...build()
            prompt = "Count to 100, with a comma between each number and no newlines. E.g., 1, 2, 3, ..."
            action, streaming_result = application.stream_result(halt_after='streaming_response', inputs={"prompt": prompt})
            color = "red" if action.name == "error" else "green"
            if action.name == "streaming_response": # can also use the ``.streaming`` attribute of action
                for result in output:
                     print(format(result['response'], color)) # assumes that error and streaming_response both have the same output shape
            else:
                result, state = output.get()
                print(format(result['response'], color))
        """
        self.validate_correct_async_use()
        call_execute_method_wrapper = _call_execute_method_pre_post(ExecuteMethod.stream_result)
        call_execute_method_wrapper.call_pre(self)
        halt_before, halt_after, inputs = self._process_control_flow_params(
            halt_before, halt_after, inputs
        )
        self._validate_halt_conditions(halt_before, halt_after)
        next_action = self.get_next_action()
        if next_action is None:
            raise ValueError(
                f"Cannot stream result -- no next action found! Prior action was: {self._state[PRIOR_STEP]}"
            )
        if next_action.name not in halt_after:
            # fast forward until we get to the action
            # run already handles incrementing sequence IDs, nothing to worry about here
            next_action, results, state = self.run(
                halt_before=halt_after + halt_before, inputs=inputs
            )
            # In this case, we are ready to halt and return an empty generator
            # The results will be None, and the state will be the final state
            # For context, this is specifically for the case in which you want to have
            # multiple terminal points with a unified API, where some are streaming, and some are not.
            if next_action.name in halt_before and next_action.name not in halt_after:
                call_execute_method_wrapper.call_post(self, None)
                return next_action, StreamingResultContainer.pass_through(
                    results=results, final_state=state
                )
        self._increment_sequence_id()
        self._adapter_set.call_all_lifecycle_hooks_sync(
            "pre_run_step",
            action=next_action,
            state=self._state,
            inputs=inputs,
            sequence_id=self.sequence_id,
            app_id=self._uid,
            partition_key=self._partition_key,
        )

        # we need to track if there's any exceptions that occur during this
        try:

            def process_result(result: dict, state: State) -> Tuple[Dict[str, Any], State]:
                new_state = self._update_internal_state_value(state, next_action)
                self._set_state(new_state)
                return result, new_state

            def callback(
                result: Optional[dict],
                state: State,
                exc: Optional[Exception] = None,
            ):
                self._adapter_set.call_all_lifecycle_hooks_sync(
                    "post_run_step",
                    app_id=self._uid,
                    partition_key=self._partition_key,
                    action=next_action,
                    state=state,
                    result=result,
                    sequence_id=self.sequence_id,
                    exception=exc,
                )
                call_execute_method_wrapper.call_post(self, exc)
                self._adapter_set.call_all_lifecycle_hooks_sync(
                    "post_end_stream",
                    action=next_action.name,
                    sequence_id=self.sequence_id,
                    app_id=self._uid,
                    partition_key=self._partition_key,
                )

            action_inputs = self._process_inputs(inputs, next_action)
            if not next_action.streaming:
                # In this case we are halting at a non-streaming condition
                # This is allowed as we want to maintain a more consistent API
                action, result, state = self._step(inputs=inputs, _run_hooks=False)
                self._adapter_set.call_all_lifecycle_hooks_sync(
                    "post_run_step",
                    app_id=self._uid,
                    partition_key=self._partition_key,
                    action=next_action,
                    state=self._state,
                    result=result,
                    sequence_id=self.sequence_id,
                    exception=None,
                )
                out = action, StreamingResultContainer.pass_through(
                    results=result, final_state=state
                )
                call_execute_method_wrapper.call_post(self, None)
                return out
            # Both the next cases start with this
            self._adapter_set.call_all_lifecycle_hooks_sync(
                "pre_start_stream",
                action=next_action.name,
                sequence_id=self.sequence_id,
                app_id=self._uid,
                partition_key=self._partition_key,
            )
            if next_action.single_step:
                next_action = cast(SingleStepStreamingAction, next_action)
                generator = _run_single_step_streaming_action(
                    action=next_action,
                    state=self._state,
                    inputs=action_inputs,
                    sequence_id=self.sequence_id,
                    app_id=self._uid,
                    partition_key=self._partition_key,
                    lifecycle_adapters=self._adapter_set,
                )
                return next_action, StreamingResultContainer(
                    generator, self._state, process_result, callback
                )
            else:
                next_action = cast(StreamingAction, next_action)
                generator = _run_multi_step_streaming_action(
                    action=next_action,
                    state=self._state,
                    inputs=action_inputs,
                    sequence_id=self.sequence_id,
                    app_id=self._uid,
                    partition_key=self._partition_key,
                    lifecycle_adapters=self._adapter_set,
                )
        except Exception as e:
            # We only want to raise this in the case of an exception
            # otherwise, this will get delegated to the finally
            # block of the streaming result container
            self._adapter_set.call_all_lifecycle_hooks_sync(
                "post_run_step",
                app_id=self._uid,
                partition_key=self._partition_key,
                action=next_action,
                state=self._state,
                result=None,
                sequence_id=self.sequence_id,
                exception=e,
            )
            call_execute_method_wrapper.call_post(self, e)
            raise
        return next_action, StreamingResultContainer(
            generator, self._state, process_result, callback
        )

    @telemetry.capture_function_usage
    async def astream_result(
        self,
        halt_after: list[str],
        halt_before: Optional[list[str]] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Action, AsyncStreamingResultContainer[ApplicationStateType, Union[dict, Any]]]:
        """Streams a result out in an asynchronous manner.

        :param halt_after: The list of actions/tags to halt after execution of. It will halt on the first one.
        :param halt_before: The list of actions/tags to halt before execution of. It will halt on the first one. Note that
            if this is met, the streaming result container will be empty (and return None) for the result, having an empty generator.
        :param inputs: Inputs to the action -- this is if this action requires an input that is passed in from the outside world
        :return: An asynchronous :py:class:`AsyncStreamingResultContainer <burr.core.action.AsyncStreamingResultContainer>`, which is a generator that will yield results as they come in, as well as cache/give you the final result,
            and update state accordingly.

        This is meant to be used with streaming actions -- :py:meth:`streaming_action <burr.core.action.streaming_action>`
        or :py:class:`StreamingAction <burr.core.action.StreamingAction>` It returns a
        :py:class:`StreamingResultContainer <burr.core.action.StreamingResultContainer>`, which has two capabilities:

        1. It is a generator that streams out the intermediate results of the action
        2. It has an async ``.get()`` method that returns the final result of the action, and the final state.

        If ``.get()`` is called before the generator is exhausted, it will block until the generator is exhausted.

        While this container is meant to work with streaming actions, it can also be used with non-streaming actions. In this case,
        the generator will be empty, and the ``.get()`` method will return the final result and state.

        The rules for halt_before and halt_after are the same as for :py:meth:`iterate <burr.core.application.Application.iterate>`,
        and :py:meth:`run <burr.core.application.Application.run>`. In this case, `halt_before` will indicate a *non* streaming action,
        which will be empty. Thus ``halt_after`` takes precedence -- if it is met, the streaming result container will contain the result of the
        halt_after condition.

        The :py:class:`AsyncStreamingResultContainer <burr.core.action.AsyncStreamingResultContainer>` is meant as a convenience -- specifically this allows for
        hooks, callbacks, etc... so you can take the control flow and still have state updated afterwards. Hooks/state update will be called after an exception
        is thrown during streaming, or the stream is completed. Note that it is undefined behavior to attempt to execute another action while a stream is in progress.


        To see how this works, let's take the following action (simplified as a single-node workflow) as an example:

        .. code-block:: python

            client = openai.AsyncClient()

            @streaming_action(reads=[], writes=['response'])
            async def streaming_response(state: State, prompt: str) -> Generator[dict, None, Tuple[dict, State]]:
                response = client.chat.completions.create(
                    model='gpt-3.5-turbo',
                    messages=[{
                        'role': 'user',
                        'content': prompt
                        }],
                    temperature=0,
                )
                buffer = []
                async for chunk in response: # use an async for loop
                    delta = chunk.choices[0].delta.content
                    buffer.append(delta)
                    # yield partial results
                    yield {'response': delta}, None # indicate that we are not done by returning a `None` state!
                # make sure to join with the buffer!
                full_response = ''.join(buffer)
                # yield the final result at the end + the state update
                yield {'response': full_response}, state.update(response=full_response)

        To use streaming_result, you pass in names of streaming actions (such as the one above) to the halt_after
        parameter:

        .. code-block:: python

            application = ApplicationBuilder().with_actions(streaming_response=streaming_response)...build()
            prompt = "Count to 100, with a comma between each number and no newlines. E.g., 1, 2, 3, ..."
            action, streaming_result = application.astream_result(halt_after='streaming_response', inputs={"prompt": prompt})
            async for result in streaming_result:
                print(result['response']) # one by one

            result, state = await streaming_result.get()
            print(result['response']) #  all at once

        Note that if you have multiple halt_after conditions, you can use the ``.action`` attribute to get the action that
        was run.

        .. code-block:: python

            application = ApplicationBuilder().with_actions(
                streaming_response=streaming_response,
                error=error # another function that outputs an error, streaming
            )...build()
            prompt = "Count to 100, with a comma between each number and no newlines. E.g., 1, 2, 3, ..."
            action, streaming_result = await application.astream_result(halt_after='streaming_response', inputs={"prompt": prompt})
            color = "red" if action.name == "error" else "green"
            for result in streaming_result:
                print(format(result['response'], color)) # assumes that error and streaming_response both have the same output shape

        .. code-block:: python

            application = ApplicationBuilder().with_actions(
                streaming_response=streaming_response,
                error=non_streaming_error # a non-streaming function that outputs an error
            )...build()
            prompt = "Count to 100, with a comma between each number and no newlines. E.g., 1, 2, 3, ..."
            action, streaming_result = await application.astream_result(halt_after='streaming_response', inputs={"prompt": prompt})
            color = "red" if action.name == "error" else "green"
            if action.name == "streaming_response": # can also use the ``.streaming`` attribute of action
                async for result in streaming_result:
                     print(format(result['response'], color)) # assumes that error and streaming_response both have the same output shape
            else:
                result, state = await output.get()
                print(format(result['response'], color))
        """
        call_execute_method_wrapper = _call_execute_method_pre_post(ExecuteMethod.stream_result)
        await call_execute_method_wrapper.acall_pre(self)
        halt_before, halt_after, inputs = self._process_control_flow_params(
            halt_before, halt_after, inputs
        )
        self._validate_halt_conditions(halt_before, halt_after)
        next_action = self.get_next_action()
        if next_action is None:
            raise ValueError(
                f"Cannot stream result -- no next action found! Prior action was: {self._state[PRIOR_STEP]}"
            )
        if next_action.name not in halt_after:
            # fast forward until we get to the action
            # run already handles incrementing sequence IDs, nothing to worry about here
            next_action, results, state = await self.arun(
                halt_before=halt_after + halt_before, inputs=inputs
            )
            # In this case, we are ready to halt and return an empty generator
            # The results will be None, and the state will be the final state
            # For context, this is specifically for the case in which you want to have
            # multiple terminal points with a unified API, where some are streaming, and some are not.
            if next_action.name in halt_before and next_action.name not in halt_after:
                await call_execute_method_wrapper.acall_post(self, None)
                return next_action, AsyncStreamingResultContainer.pass_through(
                    results=results, final_state=state
                )
        self._increment_sequence_id()
        await self._adapter_set.call_all_lifecycle_hooks_sync_and_async(
            "pre_run_step",
            action=next_action,
            state=self._state,
            inputs=inputs,
            sequence_id=self.sequence_id,
            app_id=self._uid,
            partition_key=self._partition_key,
        )
        try:

            def process_result(result: dict, state: State) -> Tuple[Dict[str, Any], State]:
                new_state = self._update_internal_state_value(state, next_action)
                self._set_state(new_state)
                return result, new_state

            async def callback(
                result: Optional[dict],
                state: State,
                exc: Optional[Exception] = None,
            ):
                await self._adapter_set.call_all_lifecycle_hooks_sync_and_async(
                    "post_run_step",
                    app_id=self._uid,
                    partition_key=self._partition_key,
                    action=next_action,
                    state=state,
                    result=result,
                    sequence_id=self.sequence_id,
                    exception=exc,
                )
                await self._adapter_set.call_all_lifecycle_hooks_sync_and_async(
                    "post_end_stream",
                    action=next_action.name,
                    sequence_id=self.sequence_id,
                    app_id=self._uid,
                    partition_key=self._partition_key,
                )
                await call_execute_method_wrapper.acall_post(self, exc)

            action_inputs = self._process_inputs(inputs, next_action)
            if not next_action.streaming:
                # In this case we are halting at a non-streaming condition
                # This is allowed as we want to maintain a more consistent API
                action, result, state = await self._astep(inputs=inputs, _run_hooks=False)
                await self._adapter_set.call_all_lifecycle_hooks_sync_and_async(
                    "post_run_step",
                    app_id=self._uid,
                    partition_key=self._partition_key,
                    action=next_action,
                    state=self._state,
                    result=result,
                    sequence_id=self.sequence_id,
                    exception=None,
                )
                await call_execute_method_wrapper.acall_post(self, None)
                return action, AsyncStreamingResultContainer.pass_through(
                    results=result, final_state=state
                )
            await self._adapter_set.call_all_lifecycle_hooks_sync_and_async(
                "pre_start_stream",
                action=next_action.name,
                sequence_id=self.sequence_id,
                app_id=self._uid,
                partition_key=self._partition_key,
            )
            if next_action.single_step:
                next_action = cast(SingleStepStreamingAction, next_action)
                if not next_action.is_async():
                    raise ValueError(
                        f"Action: {next_action.name} is not"
                        "an async action, but is marked as streaming. "
                        "Currently we do not support running synchronous "
                        "streaming actions with astream_result, although we plan to in the future. "
                        "For now, convert the action to async. Please open up an issue if you hit this. "
                    )
                generator = _arun_single_step_streaming_action(
                    action=next_action,
                    state=self._state,
                    inputs=action_inputs,
                    sequence_id=self.sequence_id,
                    app_id=self._uid,
                    partition_key=self._partition_key,
                    lifecycle_adapters=self._adapter_set,
                )
                return next_action, AsyncStreamingResultContainer(
                    generator, self._state, process_result, callback
                )
            else:
                if not next_action.is_async():
                    raise ValueError(
                        f"Action: {next_action.name} is not"
                        "an async action, but is marked as streaming. "
                        "Currently we do not support running synchronous "
                        "streaming actions with astream_result, although we plan to in the future. "
                        "For now, convert the action to async. Please open up an issue if you hit this. "
                    )
                next_action = cast(AsyncStreamingAction, next_action)
                generator = _arun_multi_step_streaming_action(
                    action=next_action,
                    state=self._state,
                    inputs=action_inputs,
                    sequence_id=self.sequence_id,
                    app_id=self._uid,
                    partition_key=self._partition_key,
                    lifecycle_adapters=self._adapter_set,
                )
        except Exception as e:
            # We only want to raise this in the case of an exception
            # otherwise, this will get delegated to the finally
            # block of the streaming result container
            await self._adapter_set.call_all_lifecycle_hooks_sync_and_async(
                "post_run_step",
                app_id=self._uid,
                partition_key=self._partition_key,
                action=next_action,
                state=self._state,
                result=None,
                sequence_id=self.sequence_id,
                exception=e,
            )
            await call_execute_method_wrapper.acall_post(self, e)
            await self._adapter_set.call_all_lifecycle_hooks_sync_and_async(
                "post_end_stream",
                action=next_action.name,
                sequence_id=self.sequence_id,
                app_id=self._uid,
                partition_key=self._partition_key,
            )
            raise
        return next_action, AsyncStreamingResultContainer(
            generator, self._state, process_result, callback
        )

    @telemetry.capture_function_usage
    @_call_execute_method_pre_post(ExecuteMethod.stream_iterate)
    def stream_iterate(
        self,
        halt_after: Optional[Union[str, List[str]]] = None,
        halt_before: Optional[Union[str, List[str]]] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Generator[
        Tuple[Action, StreamingResultContainer[ApplicationStateType, Union[dict, Any]]], None, None
    ]:
        """Produces an iterator that iterates through intermediate streams. You may want
        to use this in something like deep research mode in which:

        1. The user queries for a result
        2. The application runs through a workflow
        3. For each step of the workflow, the application
            a. Streams out an intermediate result
            b. Selects the next action/transition when the intermediate results is complete

        Note that there are control-flow complexities involved here -- we need to ensure that the iterator
        is properly pushed along and the prior streaming results containers are all finished before going to the next one.

        :param halt_after: Action names/tags to halt before
        :param halt_before: _description_, defaults to None
        :param inputs: _description_, defaults to None
        :return: _description_
        :yield: _description_
        """
        self.validate_correct_async_use()
        halt_before, halt_after, inputs = self._process_control_flow_params(
            halt_before, halt_after, inputs
        )
        self._validate_halt_conditions(halt_before, halt_after)
        while self.has_next_action():
            next_action = self.get_next_action()
            _, streaming_result = self.stream_result(
                halt_after=[next_action.name], halt_before=None, inputs=inputs
            )
            yield next_action, streaming_result
            # We need to ensure it's fully exhausted before going to the next action
            streaming_result.get()
            if self._should_halt_iterate(halt_before, halt_after, next_action):
                break

    @telemetry.capture_function_usage
    @_call_execute_method_pre_post(ExecuteMethod.astream_iterate)
    async def astream_iterate(
        self,
        halt_after: Optional[Union[str, List[str]]] = None,
        halt_before: Optional[Union[str, List[str]]] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[
        Tuple[Action, AsyncStreamingResultContainer[ApplicationStateType, Union[dict, Any]]], None
    ]:
        """Async version of stream_iterate. Produces an async generator that iterates
        through intermediate streams. See stream_iterate for more details.

        :param halt_after: Action names/tags to halt after the action completes
        :param halt_before: Action names/tags to halt after
        :param inputs: Inputs to the first action run
        :return: Async generator yielding tuples of (action, streaming_result_container)
        :yield: Tuples of (action, streaming_result_container)
        """
        halt_before, halt_after, inputs = self._process_control_flow_params(
            halt_before, halt_after, inputs
        )
        self._validate_halt_conditions(halt_before, halt_after)
        while self.has_next_action():
            next_action = self.get_next_action()
            _, streaming_result = await self.astream_result(  # Use astream_result
                halt_after=[next_action.name], halt_before=None, inputs=inputs
            )
            yield next_action, streaming_result
            # We need to ensure it's fully exhausted before going to the next action
            await streaming_result.get()  # await the get call
            if self._should_halt_iterate(halt_before, halt_after, next_action):
                break

    @telemetry.capture_function_usage
    def visualize(
        self,
        output_file_path: Optional[str] = None,
        include_conditions: bool = False,
        include_state: bool = False,
        view: bool = False,
        engine: Literal["graphviz"] = "graphviz",
        write_dot: bool = False,
        **engine_kwargs: Any,
    ) -> Optional["graphviz.Digraph"]:  # noqa: F821
        """Visualizes the application graph using graphviz. This will render the graph.

        :param output_file_path: The path to save this to, None if you don't want to save. Do not pass an extension
            for graphviz, instead pass `format` in `engine_kwargs` (e.g. `format="png"`)
        :param include_conditions: Whether to include condition strings on the edges (this can get noisy)
        :param include_state: Whether to indicate the action "signature" (reads/writes) on the nodes
        :param view: Whether to bring up a view
        :param engine: The engine to use -- only graphviz is supported for now
        :param write_dot: If True, produce a graphviz dot file
        :param engine_kwargs: Additional kwargs to pass to the engine
        :return: The graphviz object
        """
        return self.graph.visualize(
            output_file_path=output_file_path,
            include_conditions=include_conditions,
            include_state=include_state,
            view=view,
            engine=engine,
            write_dot=write_dot,
            **engine_kwargs,
        )

    def _set_state(self, new_state: State[ApplicationStateType]):
        self._state = new_state

    def get_next_action(self) -> Optional[Action]:
        return self._graph.get_next_node(self._state.get(PRIOR_STEP), self._state, self.entrypoint)

    def update_state(self, new_state: State[ApplicationStateType]):
        """Updates state -- this is meant to be called if you need to do
        anything with the state. For example:
        1. Reset it (after going through a loop)
        2. Store to some external source/log out

        :param new_state:
        :return:
        """
        self._state = new_state

    @property
    def state(self) -> State[ApplicationStateType]:
        """Gives the state. Recall that state is purely immutable
        -- anything you do with this state will not be persisted unless you
        subsequently call update_state.

        :return: The current state object.
        """
        return self._state

    @property
    def parent_pointer(self) -> Optional[burr_types.ParentPointer]:
        """Gives the parent pointer of an application (from where it was forked).
        This is None if it was not forked.

        Forking is the process of starting an application off of another.

        :return: The parent pointer object.
        """
        return self._parent_pointer

    @property
    def spawning_parent_pointer(self) -> Optional[burr_types.ParentPointer]:
        """Gives the parent pointer of an application (from where it was spawned).
        This is None if it was not spawned.

        Spawning is the process of launching an application from within
        a step of another. This is used for recursive tracking.

        :return: The parent pointer object.
        """
        return self._spawning_parent_pointer

    @property
    def graph(self) -> ApplicationGraph:
        """Application graph object -- if you want to inspect, visualize, etc..
        this is what you want.

        :return: The application graph object
        """
        return self._public_facing_graph

    @property
    def sequence_id(self) -> Optional[int]:
        """gives the sequence ID of the current (next) action.
        This is incremented prior to every step. Any logging, etc... will use the current
        step's sequence ID

        :return: The sequence ID of the current (next) action
        """
        return self._state.get(SEQUENCE_ID)

    @property
    def context(self) -> ApplicationContext:
        """Gives the application context.
        This has information you need for the tracker, sequence ID, application, etc...

        :return: Application context
        """
        return self._context_factory(self.get_next_action(), self.sequence_id)

    def _increment_sequence_id(self):
        if SEQUENCE_ID not in self._state:
            self._state = self._state.update(**{SEQUENCE_ID: 0})
        else:
            self._state = self._state.update(**{SEQUENCE_ID: self.sequence_id + 1})

    def _set_sequence_id(self, sequence_id: int):
        self._state = self._state.update(**{SEQUENCE_ID: sequence_id})

    @property
    def uid(self) -> str:
        """Unique ID for the application. This must be unique across *all* applications in a search space.
        This is used by persistence/tracking to ensure that applications have meanings.

        Every application has this -- if not assigned, it will be randomly generated.

        :return: The unique ID for the application
        """
        return self._uid

    @property
    def partition_key(self) -> Optional[str]:
        """Partition key for the application. This is designed to add semantic meaning to
        the application, and be leveraged by persistence systems to select/find applications.

        Note this is optional -- if it is not included, you will need to use a persister that
        supports a null partition key.

        :return: The partition key, None if not set
        """
        return self._partition_key

    @property
    def builder(self) -> Optional["ApplicationBuilder[ApplicationStateType]"]:
        """Returns the application builder that was used to build this application.
        Note that this asusmes the application was built using the builder. Otherwise,

        :return: The application builder
        """
        return self._builder

    def _repr_mimebundle_(self, include=None, exclude=None, **kwargs):
        """Attribute read by notebook renderers
        This returns the attribute of the `graphviz.Digraph` returned by `self.display_all_functions()`

        The parameters `include`, `exclude`, and `**kwargs` are required, but not explicitly used
        ref: https://ipython.readthedocs.io/en/stable/config/integrating.html
        """
        dot = self.visualize(include_conditions=True, include_state=False)
        return dot._repr_mimebundle_(include=include, exclude=exclude, **kwargs)

    def validate_correct_async_use(self):
        """Validates that the application is meant to run async.
        This validation is performed in synchronous application methods."""

        # This is a gentle warning for existing users to use the async application
        if self._adapter_set.async_hooks:
            logger.warning(
                "There are asynchronous hooks present in the application that will be ignored. "
                "Please use async methods to run the application and have them executed. "
                f"The application has following asynchronous hooks: {self._adapter_set.async_hooks} "
            )

        # We check that if:
        # - we have build the application using .abuild()
        # - we have async hooks present
        # this application is meant to be run in async mode.
        if self._builder and self._builder.is_async:
            raise ValueError(
                "The application was build with .abuild() "
                "which needs to be executed in an asynchronous run. "
                "Please use the async run methods to run the application."
            )


def _validate_app_id(app_id: Optional[str]):
    if app_id is None:
        raise ValueError(
            "App ID was None. Please ensure that you set an app ID using with_identifiers(app_id=...), or default"
            "not setting it and letting the system generate one for you."
        )


def _validate_start(start: Optional[str], actions: Set[str]):
    validation.assert_set(start, "_start", "with_entrypoint")
    if start not in actions:
        raise ValueError(
            f"Entrypoint: {start} not found in actions. Please add "
            f"using with_actions({start}=...)"
        )


class ApplicationBuilder(Generic[StateType]):
    def __init__(self):
        self.start = None
        self.state: Optional[State[StateType]] = None
        self.lifecycle_adapters: List[LifecycleAdapter] = list()
        self.app_id: str = str(uuid.uuid4())
        self.partition_key: Optional[str] = None
        self.sequence_id: Optional[int] = None
        self.state_initializer = None
        self.use_entrypoint_from_save_state: Optional[bool] = None
        self.default_state: Optional[dict] = None
        self.fork_from_app_id: Optional[str] = None
        self.fork_from_partition_key: Optional[str] = None
        self.fork_from_sequence_id: Optional[int] = None
        self.spawn_from_app_id: Optional[str] = None
        self.spawn_from_partition_key: Optional[str] = None
        self.spawn_from_sequence_id: Optional[int] = None
        self.loaded_from_fork: bool = False
        self.tracker = None
        self.graph_builder = None
        self.typing_system = None
        self.parallel_executor_factory = None
        self.state_persister = None
        self._is_async: bool = False

    def with_identifiers(
        self, app_id: str = None, partition_key: str = None, sequence_id: int = None
    ) -> "ApplicationBuilder[StateType]":
        """Assigns various identifiers to the application. This is used for tracking, persistence, etc...

        :param app_id: Application ID -- this will be assigned to a uuid if not set.
        :param partition_key: Partition key -- this is used for disambiguating groups of applications. For instance, a unique user ID, etc...
            This is coupled to persistence, and is used to query for/select application runs.
        :param sequence_id: Sequence ID that we want this to start at. If you're using ``.initialize``, this will be set. Otherwise this is
            solely for resetting/starting at a specified position.
        :return: The application builder for future chaining.
        """
        if app_id is not None:
            self.app_id = app_id
        if partition_key is not None:
            self.partition_key = partition_key
        if sequence_id is not None:
            self.sequence_id = sequence_id
        return self

    def with_typing(
        self, typing_system: TypingSystem[StateTypeToSet]
    ) -> "ApplicationBuilder[StateTypeToSet]":
        """Sets the typing system for the application. This is used to enforce typing on the state.

        :param typing_system: Typing system to use
        :return: The application builder for future chaining.
        """
        if typing_system is not None:
            self.typing_system = typing_system
        return self  # type: ignore

    def with_state(
        self, state: Optional[Union[State, StateTypeToSet]] = None, **kwargs
    ) -> "ApplicationBuilder[StateType]":
        """Sets initial values in the state. If you want to load from a prior state,
        you can do so here and pass the values in.

        TODO -- enable passing in a `state` object instead of `**kwargs`

        :param kwargs: Key-value pairs to set in the state
        :return: The application builder for future chaining.
        """
        if self.state_initializer is not None:
            raise ValueError(
                BASE_ERROR_MESSAGE + "You cannot set state if you are loading state"
                "the .initialize_from() API. Either allow the persister to set the "
                "state, or set the state manually."
            )
        if state is not None:
            if self.state is not None:
                raise ValueError(
                    BASE_ERROR_MESSAGE
                    + "State items have already been set -- you cannot use the type-based API as well."
                    " Either set state with with_state(**kwargs) or pass in a state/typed object."
                )
            if isinstance(state, State):
                self.state = state
            elif self.typing_system is not None:
                self.state = self.typing_system.construct_state(state)
            else:
                raise ValueError(
                    BASE_ERROR_MESSAGE
                    + "You have not set a typing system, and you are passing in a typed state object."
                    " Please set a typing system using with_typing before doing so."
                )
        elif self.state is not None:
            self.state = self.state.update(**kwargs)
        else:
            self.state = State(kwargs)
        return self

    def with_graphs(self, *graphs) -> "ApplicationBuilder[StateType]":
        """Adds multiple prebuilt graphs -- this just calls :py:meth:`with_graph <burr.core.application.ApplicationBuilder.with_graph>`
        in a loop! See caveats in :py:meth:`with_graph <burr.core.application.ApplicationBuilder.with_graph>`.

        :param graphs: Graphs to add to the application
        :return: The application builder for future chaining.
        """
        for graph in graphs:
            self.with_graph(graph)
        return self

    def with_graph(self, graph: Graph) -> "ApplicationBuilder[StateType]":
        """Adds a prebuilt graph -- this can work in addition to using with_actions and with_transitions methods.
        This will add all nodes + edges from a prebuilt graph to the current graph. Note that if you add two
        graphs (or a combination of graphs/nodes/edges), you will need to ensure that there are no node name conflicts.

        1. You want to reuse the same graph object for different applications
        2. You want the logic that constructs the graph to be separate from that which constructs the application
        3. You want to serialize/deserialize a graph object and run it in an application

        :param graph: Graph object built with the :py:class:`GraphBuilder <burr.core.graph.GraphBuilder>`
        :return: The application builder for future chaining.
        """
        self._initialize_graph_builder()
        self.graph_builder = self.graph_builder.with_graph(graph)
        return self

    def with_parallel_executor(self, executor_factory: lambda: Executor):
        """Assigns a default executor to be used for recursive/parallel sub-actions. This effectively allows
        for executing multiple Burr apps in parallel. See https://burr.dagworks.io/concepts/parallelism/
        for more details.

        This will default to a simple threadpool executor, meaning that you will be bound by the number of threads
        your computer can handle. If you want to use a more advanced executor, you can pass it in here -- any subclass
        of concurrent.futures.Executor will work.

        If you specify executors for specific tasks, this will default to that.

        Note that, if you are using asyncio, you cannot specify an executor. It will default to using
        asyncio.gather with asyncio's event loop.

        :param executor:
        :return:
        """
        if self.parallel_executor_factory is not None:
            raise ValueError(
                BASE_ERROR_MESSAGE
                + "You have already set an executor. You cannot set multiple executors. Current executor is:"
                f"{self.parallel_executor_factory}"
            )

        self.parallel_executor_factory = executor_factory
        return self

    def _initialize_graph_builder(self):
        if self.graph_builder is None:
            self.graph_builder = GraphBuilder()

    def with_entrypoint(self, action: str) -> "ApplicationBuilder[StateType]":
        """Adds an entrypoint to the application. This is the action that will be run first.
        This can only be called once.

        :param action: The name of the action to set as the entrypoint
        :return: The application builder for future chaining.
        """
        if self.start is not None:
            raise ValueError(
                BASE_ERROR_MESSAGE
                + "You cannot set the entrypoint if you are loading a persister using "
                "the .initialize_from() API. Either allow the persister to set the "
                "entrypoint/provide a default, or set the entrypoint + state manually."
            )
        self.start = action
        return self

    def with_actions(
        self,
        *action_list: Union[Action, Callable],
        **action_dict: Union[Action, Callable],
    ) -> "ApplicationBuilder[StateType]":
        """Adds an action to the application. The actions are granted names (using the with_name)
        method post-adding, using the kw argument. If it already has a name (or you wish to use the function name, raw, and
        it is a function-based-action), then you can use the *args* parameter. This is the only supported way to add actions.

        :param action_list: Actions to add -- these must have a name or be function-based (in which case we will use the function-name)
        :param action_dict: Actions to add, keyed by name
        :return: The application builder for future chaining.
        """
        self._initialize_graph_builder()
        self.graph_builder = self.graph_builder.with_actions(*action_list, **action_dict)
        return self

    def with_transitions(
        self,
        *transitions: Union[
            Tuple[Union[str, list[str]], str],
            Tuple[Union[str, list[str]], str, Condition],
        ],
    ) -> "ApplicationBuilder[StateType]":
        """Adds transitions to the application. Transitions are specified as tuples of either:
            1. (from, to, condition)
            2. (from, to)  -- condition is set to DEFAULT (which is a fallback)

        Transitions will be evaluated in order of specification -- if one is met, the others will not be evaluated.
        Note that one transition can be terminal -- the system doesn't have


        :param transitions: Transitions to add
        :return: The application builder for future chaining.
        """
        self._initialize_graph_builder()
        self.graph_builder = self.graph_builder.with_transitions(*transitions)
        return self

    def with_hooks(self, *adapters: LifecycleAdapter) -> "ApplicationBuilder[StateType]":
        """Adds a lifecycle adapter to the application. This is a way to add hooks to the application so that
        they are run at the appropriate times. You can use this to synchronize state out, log results, etc...

        :param adapters: Adapter to add
        :return: The application builder for future chaining.
        """
        self.lifecycle_adapters.extend(adapters)
        return self

    def with_tracker(
        self,
        tracker: Union[Literal["local"], "TrackingClient"] = "local",
        project: str = "default",
        params: Dict[str, Any] = None,
        use_otel_tracing: bool = False,
    ):
        """Adds a "tracker" to the application. The tracker specifies
        a project name (used for disambiguating groups of tracers), and plugs into the
        Burr UI. This can either be:

        1. A string (the only supported one right now is "local"), and a set of parameters for a set of supported trackers.
        2. A lifecycle adapter object that does tracking (up to you how to implement it).

        (1) internally creates a :py:class:`LocalTrackingClient <burr.tracking.client.LocalTrackingClient>` object, and adds it to the lifecycle adapters.
        (2) adds the lifecycle adapter to the lifecycle adapters.

        :param tracker: Tracker to use. ``local`` creates one, else pass one in.
        :param project: Project name -- used if the tracker is string-specified (local).
        :param params: Parameters to pass to the tracker if it's string-specified (local).
        :param use_otel_tracing: Whether to log opentelemetry traces to the Burr UI. This is experimental but we will be adding
            full support shortly. This requires burr[opentelemetry] installed. Note you can also log burr to OpenTelemetry using the OpenTelemetry adapter
        :return: The application builder for future chaining.
        """
        # if it's a lifecycle adapter, just add it
        instantiated_tracker = tracker
        if isinstance(tracker, str):
            if params is None:
                params = {}
            if tracker == "local":
                from burr.tracking.client import LocalTrackingClient

                kwargs = {"project": project}
                kwargs.update(params)
                instantiated_tracker = LocalTrackingClient(**kwargs)
            else:
                raise ValueError(f"Tracker {tracker}:{project} not supported")
        else:
            if params is not None:
                raise ValueError(
                    "Params are not supported for object-specified trackers, these are already initialized!"
                )
        if use_otel_tracing:
            from burr.integrations.opentelemetry import OpenTelemetryTracker

            instantiated_tracker = OpenTelemetryTracker(burr_tracker=instantiated_tracker)
        self.lifecycle_adapters.append(instantiated_tracker)
        self.tracker = instantiated_tracker
        return self

    def initialize_from(
        self,
        initializer: Union[BaseStateLoader, AsyncBaseStateLoader],
        resume_at_next_action: bool,
        default_state: dict,
        default_entrypoint: str,
        fork_from_app_id: str = None,
        fork_from_partition_key: str = None,
        fork_from_sequence_id: int = None,
    ) -> "ApplicationBuilder[StateType]":
        """Initializes the application we will build from some prior state object.

        Note (1) that you can *either* call this or use `with_state` and `with_entrypoint`.

        Note (2) if you want to continue a prior application and don't want to fork it into a new application ID,
        the values in `.with_identifiers()` will be used to query for prior state.

        :param initializer: The persister object to use for initialization. Likely the same one called with ``with_state_persister``.
        :param resume_at_next_action: Whether to resume at the next action, or default to the ``default_entrypoint``
        :param default_state: The default state to use if it does not exist. This is a dictionary.
        :param default_entrypoint: The default entry point to use if it does not exist or you elect not to resume_at_next_action.
        :param fork_from_app_id: The app ID to fork from, not to be confused with the current app_id that is set with `.with_identifiers()`. This is used to fork from a prior application run.
        :param fork_from_partition_key: The partition key to fork from a prior application. Optional. `fork_from_app_id` required.
        :param fork_from_sequence_id: The sequence ID to fork from a prior application run. Optional, defaults to latest. `fork_from_app_id` required.
        :return: The application builder for future chaining.
        """
        if self.start is not None or self.state is not None:
            raise ValueError(
                BASE_ERROR_MESSAGE
                + "Cannot call initialize_from if you have already set state or an entrypoint! "
                "You can either use the initializer *or* set the state and entrypoint manually."
            )
        if not fork_from_app_id and (fork_from_partition_key or fork_from_sequence_id):
            raise ValueError(
                BASE_ERROR_MESSAGE
                + "If you set fork_from_partition_key or fork_from_sequence_id, you must also set fork_from_app_id. "
                "See .initialize_from() documentation."
            )
        self.state_initializer = initializer
        self.resume_at_next_action = resume_at_next_action
        self.default_state = default_state
        self.start = default_entrypoint
        self.fork_from_app_id = fork_from_app_id
        self.fork_from_partition_key = fork_from_partition_key
        self.fork_from_sequence_id = fork_from_sequence_id
        return self

    def with_state_persister(
        self,
        persister: Union[BaseStateSaver, AsyncBaseStateSaver, LifecycleAdapter],
        on_every: str = "step",
    ) -> "ApplicationBuilder[StateType]":
        """Adds a state persister to the application. This is a way to persist state out to a database, file, etc...
        at the specified interval. This is one of two options:

        1. [normal mode] A BaseStateSaver object -- this is a utility class that makes it easy to save/load
        2. [power-user-mode] A lifecycle adapter -- this is a custom class that you use to save state.

        The framework will wrap the BaseStateSaver object in a PersisterHook, which is a post-run.

        :param persister: The persister to add
        :param on_every: The interval to persist state. Currently only "step" is supported.
        :return: The application builder for future chaining.
        """
        if on_every != "step":
            raise ValueError(f"on_every {on_every} not supported")

        self.state_persister = persister  # tracks for later; validates in build / abuild
        return self

    def with_spawning_parent(
        self, app_id: str, sequence_id: int, partition_key: Optional[str] = None
    ) -> "ApplicationBuilder[StateType]":
        """Sets the 'spawning' parent application that created this app.
        This is used for tracking purposes. Doing this creates a parent/child relationship.
        There can be many spawned children from a single sequence ID (just as there can be many forks of an app).

        Note the difference between this and forking. Forking allows you to create a new app
        where the old one left off. This suggests that this application is wholly contained
        within the parent application.

        :param app_id: ID of application that spawned this app
        :param sequence_id: Sequence ID of the parent app that spawned this app
        :param partition_key: Partition key of the parent app that spawned this app
        :return: The application builder for future chaining.
        """
        self.spawn_from_app_id = app_id
        self.spawn_from_sequence_id = sequence_id
        self.spawn_from_partition_key = partition_key
        return self

    def _set_sync_state_persister(self):
        """Inits the synchronous with_state_persister to save the state (local/DB/custom implementations).
        Moved here to mimic the async case.
        """
        if self.state_persister.is_async():
            raise ValueError(
                "You are building the sync application, but have used an "
                "async persister. Please use a sync persister or use the "
                ".abuild() method to build an async application."
            )

        if not isinstance(self.state_persister, persistence.BaseStateSaver):
            self.lifecycle_adapters.append(self.state_persister)
        else:
            # Check if 'is_initialized' exists and is False; raise RuntimeError, else continue if not implemented
            try:
                if not self.state_persister.is_initialized():
                    raise RuntimeError(
                        "RuntimeError: Uninitialized persister. Make sure to call .initialize() before passing it to "
                        "the ApplicationBuilder."
                    )
            except NotImplementedError:
                pass
            self.lifecycle_adapters.append(persistence.PersisterHook(self.state_persister))

    async def _set_async_state_persister(self):
        """Inits the asynchronous with_state_persister to save the state (local/DB/custom implementations).
        Moved here to be able to chain methods and delay the execution until we can chain coroutines in abuild().
        """
        if not self.state_persister.is_async():
            raise ValueError(
                "You are building the async application, but have used an "
                "sync persister. Please use an async persister or use the "
                ".build() method to build an sync application."
            )

        if not isinstance(self.state_persister, persistence.AsyncBaseStateSaver):
            self.lifecycle_adapters.append(self.state_persister)
        else:
            # Check if 'is_initialized' exists and is False; raise RuntimeError, else continue if not implemented
            try:
                if not await self.state_persister.is_initialized():
                    raise RuntimeError(
                        "RuntimeError: Uninitialized persister. Make sure to call .initialize() before passing it to "
                        "the ApplicationBuilder."
                    )
            except NotImplementedError:
                pass
            self.lifecycle_adapters.append(persistence.PersisterHookAsync(self.state_persister))

    def _identify_state_to_load(self):
        """Helper to determine which state to load."""
        if self.fork_from_app_id is not None:
            if self.app_id == self.fork_from_app_id:
                raise ValueError(
                    BASE_ERROR_MESSAGE + "Cannot fork and save to the same app_id. "
                    "Please update the app_id passed in via with_identifiers(), "
                    "or don't pass in a fork_from_app_id value to `initialize_from()`."
                )
            _partition_key = self.fork_from_partition_key
            _app_id = self.fork_from_app_id
            _sequence_id = self.fork_from_sequence_id
        else:
            # only use the with_identifier values if we're not forking from a previous app
            _partition_key = self.partition_key
            _app_id = self.app_id
            _sequence_id = self.sequence_id

        return _partition_key, _app_id, _sequence_id

    def _init_state_from_persister(
        self,
        load_result: Optional[persistence.PersistedStateData],
        partition_key: str,
        app_id: Optional[str],
        sequence_id: Optional[int],
    ):
        """Initializes the state of the application.

        Either there is a loaded configuration provided or we use the default state to initialize.
        """
        if load_result is None:
            if self.fork_from_app_id is not None:
                logger.warning(
                    f"{self.state_initializer.__class__.__name__} returned None while trying to fork from: "
                    f"partition_key:{partition_key}, app_id:{app_id}, "
                    f"sequence_id:{sequence_id}. "
                    "You explicitly requested to fork from a prior application run, but it does not exist. "
                    "Defaulting to state defaults instead."
                )
            # there was nothing to load -- use default state
            self.state = self.state.update(**self.default_state)
            self.sequence_id = None  # has to start at None
        else:
            self.loaded_from_fork = True
            if load_result["state"] is None:
                raise ValueError(
                    BASE_ERROR_MESSAGE
                    + f"Error: {self.state_initializer.__class__.__name__} returned {load_result} for "
                    f"partition_key:{partition_key}, app_id:{app_id}, "
                    f"sequence_id:{sequence_id}, "
                    "but value for state was None! This is not allowed. Please return just None in this case, "
                    "or double check that persisted state can never be a None value."
                )
            # TODO: capture parent app ID relationship & wire it through
            # there was something
            last_position = load_result["position"]
            self.state = load_result["state"]
            self.sequence_id = load_result["sequence_id"]
            status = load_result["status"]
            if self.resume_at_next_action:
                # if we're supposed to resume where we saved from
                if status == "completed":
                    # completed means we set prior step to current to go to next action
                    self.state = self.state.update(**{PRIOR_STEP: last_position})
                else:
                    # else we failed we just start at that node
                    self.start = last_position
                    self.reset_to_entrypoint()
            else:
                # self.start is already set to the default. We don't need to do anything.
                pass

    def _load_from_sync_persister(self):
        """Loads from the set sync persister and into this current object.

        Mutates:
         - self.state
         - self.sequence_id
         - maybe self.start

        """
        if self.state_initializer.is_async():
            raise ValueError(
                "You are building the sync application, but have used an "
                "async initializer. Please use a sync initializer or use the "
                ".abuild() method to build an async application."
            )

        _partition_key, _app_id, _sequence_id = self._identify_state_to_load()

        # load state from persister
        load_result = self.state_initializer.load(_partition_key, _app_id, _sequence_id)
        self._init_state_from_persister(load_result, _partition_key, _app_id, _sequence_id)

    async def _load_from_async_persister(self):
        """Loads from the set async persister and into this current object.

        Mutates:
         - self.state
         - self.sequence_id
         - maybe self.start

        """
        if not self.state_initializer.is_async():
            raise ValueError(
                "You are building the async application, but have used an "
                "sync initializer. Please use an async initializer or use the "
                ".build() method to build an sync application."
            )

        _partition_key, _app_id, _sequence_id = self._identify_state_to_load()

        # load state from persister
        load_result = await self.state_initializer.load(_partition_key, _app_id, _sequence_id)
        self._init_state_from_persister(load_result, _partition_key, _app_id, _sequence_id)

    def reset_to_entrypoint(self):
        self.state = self.state.wipe(delete=[PRIOR_STEP])

    def _get_built_graph(self) -> Graph:
        if self.graph_builder is None:
            raise ValueError(
                BASE_ERROR_MESSAGE
                + "No graph constructs exist. You must call some combination of with_graph, with_entrypoint, "
                "with_actions, and with_transitions"
            )
        return self.graph_builder.build()

    def _build_common(self) -> Application:
        graph = self._get_built_graph()
        _validate_start(self.start, {action.name for action in graph.actions})
        typing_system: TypingSystem[StateType] = (
            self.typing_system if self.typing_system is not None else DictBasedTypingSystem()
        )  # type: ignore
        self.state = self.state.with_typing_system(typing_system=typing_system)
        return Application(
            graph=graph,
            state=self.state,
            uid=self.app_id,
            partition_key=self.partition_key,
            sequence_id=self.sequence_id,
            entrypoint=self.start,
            adapter_set=LifecycleAdapterSet(*self.lifecycle_adapters),
            builder=self,
            fork_parent_pointer=(
                burr_types.ParentPointer(
                    app_id=self.fork_from_app_id,
                    partition_key=self.fork_from_partition_key,
                    sequence_id=self.fork_from_sequence_id,
                )
                if self.loaded_from_fork
                else None
            ),
            tracker=self.tracker,
            spawning_parent_pointer=(
                burr_types.ParentPointer(
                    app_id=self.spawn_from_app_id,
                    partition_key=self.spawn_from_partition_key,
                    sequence_id=self.spawn_from_sequence_id,
                )
                if self.spawn_from_app_id is not None
                else None
            ),
            parallel_executor_factory=self.parallel_executor_factory,
            state_persister=self.state_persister,
            state_initializer=self.state_initializer,
        )

    @telemetry.capture_function_usage
    def build(self) -> Application[StateType]:
        """Builds the application for synchronous runs.

        We support both synchronous and asynchronous applications. In case you are using state initializers
        and persisters, the synchronous application should be used in the following cases:

        .. table:: When to use .build()
            :widths: auto

            +-----------------------------------------+----------+------------------------+
            | Cases (persister and app methods)       | Status   | Remarks                |
            +=========================================+==========+========================+
            | Sync and Sync                           |  ✅      |                        |
            +-----------------------------------------+----------+------------------------+
            | Sync and Async                          |  ✅ ⚠️   | Will be deprecated     |
            +-----------------------------------------+----------+------------------------+
            | Async and Sync                          |  ❌      |                        |
            +-----------------------------------------+----------+------------------------+
            | Async and Async                         |  ❌      |                        |
            +-----------------------------------------+----------+------------------------+

        We originally only had sync persistence and as such this still can be used when running the
        app async. However, we strongly encourage to switch to async persisters if you are running
        an async application.

        :return: The application object.
        """
        _validate_app_id(self.app_id)
        if self.state is None:
            self.state = State()

        if self.state_persister:
            self._set_sync_state_persister()  # this is used to save the state during application run
        if self.state_initializer:
            # sets state, sequence_id, and maybe start
            self._load_from_sync_persister()  # this is used to load application from a previously saved state

        return self._build_common()

    @telemetry.capture_function_usage
    async def abuild(self) -> Application[StateType]:
        """Builds the application for asynchronous runs.

        We support both synchronous and asynchronous applications. To save/load in an asynchronous
        manner add the async persister versions and use this method to initialize them. This will
        also enforce the application to be run with async methods as an additional safety check that
        you are not introducing unnecessary bottlenecks.

        Note: When you run an async application you can still use the normal sync functionalities, i.e.
        sync hooks of other adapters, but they will block the async event loop until finished.

        In case you are using state initializers and persisters, the asynchronous application should
        be used in the following cases:

        .. table:: When to use .abuild()
            :widths: auto

            +-----------------------------------------+----------+
            | Cases (persister and app methods)       | Status   |
            +=========================================+==========+
            | Sync and Sync                           |  ❌      |
            +-----------------------------------------+----------+
            | Sync and Async                          |  ❌      |
            +-----------------------------------------+----------+
            | Async and Sync                          |  ❌      |
            +-----------------------------------------+----------+
            | Async and Async                         |  ✅      |
            +-----------------------------------------+----------+

        :return: The application object.
        """
        self._is_async = True

        _validate_app_id(self.app_id)
        if self.state is None:
            self.state = State()

        if self.state_persister:
            await self._set_async_state_persister()  # this is used to save the state during application run

        if self.state_initializer:
            # sets state, sequence_id, and maybe start
            await self._load_from_async_persister()  # this is used to load application from a previously saved state

        return self._build_common()

    @property
    def is_async(self) -> bool:
        return self._is_async
