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

from __future__ import annotations

import copy
import inspect
import types
import typing
from typing import (
    AsyncGenerator,
    Awaitable,
    Callable,
    Generator,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)

import pydantic
from pydantic_core import PydanticUndefined

from burr.core import Action, Graph, State
from burr.core.action import (
    FunctionBasedAction,
    FunctionBasedStreamingAction,
    bind,
    derive_inputs_from_fn,
)
from burr.core.typing import ActionSchema, TypingSystem

PydanticActionFunction = Callable[..., Union[pydantic.BaseModel, Awaitable[pydantic.BaseModel]]]


def model_to_dict(model: pydantic.BaseModel, include: Optional[List[str]] = None) -> dict:
    """Utility function to convert a pydantic model to a dictionary."""
    keys = model.model_fields.keys()
    keys = keys if include is None else [item for item in include if item in model.model_fields]
    return {key: getattr(model, key) for key in keys}


ModelType = TypeVar("ModelType", bound=pydantic.BaseModel)


def subset_model(
    model: Type[ModelType],
    fields: List[str],
    force_optional_fields: List[str],
    model_name_suffix: str,
) -> Type[ModelType]:
    """Creates a new pydantic model that is a subset of the original model.
    This is just to make it more efficient, as we can dynamically alter pydantic models

    :param fields: Fields that we want to include in the new model.
    :param force_optional_fields: Fields that we want to include in the new model, but that will always be optional.
    :param model: The model type to subset.
    :param model_name_suffix: The suffix to add to the model name.
    :return: The new model type.
    """
    new_fields = {}

    for name, field_info in model.model_fields.items():
        if name in fields:
            # copy directly
            # TODO -- handle cross-field validation
            new_fields[name] = (field_info.annotation, field_info)
        elif name in force_optional_fields:
            new_field_info = copy.deepcopy(field_info)
            if new_field_info.default_factory is None and (
                new_field_info.default is PydanticUndefined
            ):
                # in this case we can set to None
                new_field_info.default = None
                annotation = field_info.annotation
                if annotation is not None:
                    new_field_info.annotation = Optional[annotation]  # type: ignore
            new_fields[name] = (new_field_info.annotation, new_field_info)
    return pydantic.create_model(
        model.__name__ + model_name_suffix, __config__=model.model_config, **new_fields
    )  # type: ignore


def merge_to_state(model: pydantic.BaseModel, write_keys: List[str], state: State) -> State:
    """Merges a pydantic model that is a subset of the new state back into the state
    TODO -- implement
    TODO -- consider validating that the entire state is correct
    TODO -- consider validating just the deltas (if that's possible)
    """
    write_dict = model_to_dict(model=model, include=write_keys)
    return state.update(**write_dict)


def model_from_state(model: Type[ModelType], state: State) -> ModelType:
    """Creates a model from the state object -- capturing just the fields that are relevant to the model itself.

    :param model: model type to create
    :param state: state object to create from
    :return: model object
    """
    keys = [item for item in model.model_fields.keys() if item in state]
    return model(**{key: state[key] for key in keys})


def _validate_and_extract_signature_types(
    fn: PydanticActionFunction,
) -> Tuple[Type[pydantic.BaseModel], Type[pydantic.BaseModel]]:
    sig = inspect.signature(fn)
    if "state" not in sig.parameters:
        raise ValueError(
            f"Function fn: {fn.__qualname__} is not a valid pydantic action. "
            "The first argument of a pydantic "
            "action must be the state object. Got signature: {sig}."
        )
    type_hints = typing.get_type_hints(fn)
    state_model = type_hints.get("state")

    if (
        state_model is None
        or state_model is inspect.Parameter.empty
        or not issubclass(state_model, pydantic.BaseModel)
    ):
        raise ValueError(
            f"Function fn: {fn.__qualname__} is not a valid pydantic action. "
            "The 'state' parameter must be annotated with a type extending pydantic.BaseModel. "
            f"Got: {state_model}."
        )
    if (ret_hint := type_hints.get("return")) is None or not issubclass(
        ret_hint, pydantic.BaseModel
    ):
        raise ValueError(
            f"Function fn: {fn.__qualname__} is not a valid pydantic action. "
            "The return type must be a subclass of pydantic"
            ".BaseModel. Got return type: {sig.return_annotation}."
        )
    return state_model, ret_hint


def _validate_keys(model: Type[pydantic.BaseModel], keys: List[str], fn: Callable) -> None:
    missing_keys = [key for key in keys if key not in model.model_fields]
    if missing_keys:
        raise ValueError(
            f"Function fn: {fn.__qualname__} is not a valid pydantic action. "
            f"The keys: {missing_keys} are not present in the model: {model.__qualname__}."
        )


StateInputType = TypeVar("StateInputType", bound=pydantic.BaseModel)
StateOutputType = TypeVar("StateOutputType", bound=pydantic.BaseModel)
IntermediateResultType = TypeVar("IntermediateResultType", bound=Union[pydantic.BaseModel, dict])


class PydanticActionSchema(ActionSchema[StateInputType, StateOutputType, IntermediateResultType]):
    def __init__(
        self,
        input_type: Type[StateInputType],
        output_type: Type[StateOutputType],
        intermediate_result_type: Type[IntermediateResultType],
    ):
        self._input_type = input_type
        self._output_type = output_type
        self._intermediate_result_type = intermediate_result_type

    def state_input_type(self) -> Type[StateInputType]:
        return self._input_type

    def state_output_type(self) -> Type[StateOutputType]:
        return self._output_type

    def intermediate_result_type(self) -> type[IntermediateResultType]:
        return self._intermediate_result_type


def pydantic_action(
    reads: List[str],
    writes: List[str],
    state_input_type: Optional[Type[pydantic.BaseModel]] = None,
    state_output_type: Optional[Type[pydantic.BaseModel]] = None,
    tags: Optional[List[str]] = None,
) -> Callable[[PydanticActionFunction], PydanticActionFunction]:
    """See docstring for @action.pydantic"""

    def decorator(fn: PydanticActionFunction) -> PydanticActionFunction:
        if state_input_type is None and state_output_type is None:
            itype, otype = _validate_and_extract_signature_types(fn)

        elif state_input_type is not None and state_output_type is not None:
            itype, otype = state_input_type, state_output_type
        else:
            raise ValueError(
                "If you specify state_input_type or state_output_type, you must specify both."
            )
        _validate_keys(model=itype, keys=reads, fn=fn)
        _validate_keys(model=otype, keys=writes, fn=fn)
        SubsetInputType = subset_model(
            model=itype,
            fields=reads,
            force_optional_fields=[item for item in writes if item not in reads],
            model_name_suffix=f"{fn.__name__}_input",
        )
        SubsetOutputType = subset_model(
            model=otype,
            fields=writes,
            force_optional_fields=[],
            model_name_suffix=f"{fn.__name__}_input",
        )
        # TODO -- figure out

        def action_function(state: State, **kwargs) -> State:
            model_to_use = model_from_state(model=SubsetInputType, state=state)
            result = fn(state=model_to_use, **kwargs)
            # TODO -- validate that we can always construct this from the dict...
            # We really want a copy-type function
            output = SubsetOutputType(**model_to_dict(result, include=writes))
            return merge_to_state(model=output, write_keys=writes, state=state)

        async def async_action_function(state: State, **kwargs) -> State:
            model_to_use = model_from_state(model=SubsetInputType, state=state)
            result = await fn(state=model_to_use, **kwargs)
            output = SubsetOutputType(**model_to_dict(result, include=writes))
            return merge_to_state(model=output, write_keys=writes, state=state)

        is_async = inspect.iscoroutinefunction(fn)
        # This recreates the @action decorator
        # TODO -- use the @action decorator directly
        # TODO -- ensure that the function is the right one -- specifically it probably won't show code in the UI
        # now
        setattr(
            fn,
            FunctionBasedAction.ACTION_FUNCTION,
            FunctionBasedAction(
                async_action_function if is_async else action_function,
                reads,
                writes,
                input_spec=derive_inputs_from_fn({}, fn),
                originating_fn=fn,
                schema=PydanticActionSchema(
                    input_type=SubsetInputType,
                    output_type=SubsetOutputType,
                    intermediate_result_type=dict,
                ),
                tags=tags,
            ),
        )
        setattr(fn, "bind", types.MethodType(bind, fn))
        # TODO -- figure out typing
        # It's not smart enough to know that we have satisfied the type signature,
        # as we dynamically apply it using setattr
        return fn

    return decorator


PartialType = Union[Type[pydantic.BaseModel], Type[dict]]

PydanticStreamingActionFunctionSync = Callable[
    ..., Generator[Tuple[Union[pydantic.BaseModel, dict], Optional[pydantic.BaseModel]], None, None]
]

PydanticStreamingActionFunctionAsync = Callable[
    ..., AsyncGenerator[Tuple[Union[pydantic.BaseModel, dict], Optional[pydantic.BaseModel]], None]
]

PydanticStreamingActionFunction = Union[
    PydanticStreamingActionFunctionSync, PydanticStreamingActionFunctionAsync
]

PydanticStreamingActionFunctionVar = TypeVar(
    "PydanticStreamingActionFunctionVar", bound=PydanticStreamingActionFunction
)


def _validate_and_extract_signature_types_streaming(
    fn: PydanticStreamingActionFunction,
    stream_type: Optional[Union[Type[pydantic.BaseModel], Type[dict]]],
    state_input_type: Optional[Type[pydantic.BaseModel]] = None,
    state_output_type: Optional[Type[pydantic.BaseModel]] = None,
) -> Tuple[
    Type[pydantic.BaseModel], Type[pydantic.BaseModel], Union[Type[dict], Type[pydantic.BaseModel]]
]:
    if stream_type is None:
        # TODO -- derive from the signature
        raise ValueError(f"stream_type is required for function: {fn.__qualname__}")
    if state_input_type is None:
        # TODO -- derive from the signature
        raise ValueError(f"state_input_type is required for function: {fn.__qualname__}")
    if state_output_type is None:
        # TODO -- derive from the signature
        raise ValueError(f"state_output_type is required for function: {fn.__qualname__}")
    return state_input_type, state_output_type, stream_type


def pydantic_streaming_action(
    reads: List[str],
    writes: List[str],
    state_input_type: Type[pydantic.BaseModel],
    state_output_type: Type[pydantic.BaseModel],
    stream_type: PartialType,
    tags: Optional[List[str]] = None,
) -> Callable[[PydanticStreamingActionFunction], PydanticStreamingActionFunction]:
    """See docstring for @streaming_action.pydantic"""

    def decorator(fn: PydanticStreamingActionFunctionVar) -> PydanticStreamingActionFunctionVar:
        itype, otype, stream_type_processed = _validate_and_extract_signature_types_streaming(
            fn, stream_type, state_input_type=state_input_type, state_output_type=state_output_type
        )
        _validate_keys(model=itype, keys=reads, fn=fn)
        _validate_keys(model=otype, keys=writes, fn=fn)
        SubsetInputType = subset_model(
            model=itype,
            fields=reads,
            force_optional_fields=[item for item in writes if item not in reads],
            model_name_suffix=f"{fn.__name__}_input",
        )
        SubsetOutputType = subset_model(
            model=otype,
            fields=writes,
            force_optional_fields=[],
            model_name_suffix=f"{fn.__name__}_input",
        )
        # PartialModelType = stream_type_processed  # TODO -- attach to action
        # We don't currently use this, but we will be passing to the action to validate

        def action_generator(
            state: State, **kwargs
        ) -> Generator[tuple[PartialType, Optional[State]], None, None]:
            model_to_use = model_from_state(model=SubsetInputType, state=state)
            for partial, state_update in fn(state=model_to_use, **kwargs):
                if state_update is None:
                    yield partial, None
                else:
                    output = SubsetOutputType(**model_to_dict(state_update, include=writes))
                    yield partial, merge_to_state(model=output, write_keys=writes, state=state)

        async def async_action_generator(
            state: State, **kwargs
        ) -> AsyncGenerator[tuple[dict, Optional[State]], None]:
            model_to_use = model_from_state(model=SubsetInputType, state=state)
            async for partial, state_update in fn(state=model_to_use, **kwargs):
                if state_update is None:
                    yield partial, None
                else:
                    output = SubsetOutputType(**model_to_dict(state_update, include=writes))
                    yield partial, merge_to_state(model=output, write_keys=writes, state=state)

        is_async = inspect.isasyncgenfunction(fn)
        # This recreates the @streaming_action decorator
        # TODO -- use the @streaming_action decorator directly
        setattr(
            fn,
            FunctionBasedAction.ACTION_FUNCTION,
            FunctionBasedStreamingAction(
                async_action_generator if is_async else action_generator,
                reads,
                writes,
                input_spec=derive_inputs_from_fn({}, fn),
                originating_fn=fn,
                schema=PydanticActionSchema(
                    input_type=SubsetInputType,
                    output_type=SubsetOutputType,
                    intermediate_result_type=stream_type_processed,
                ),
                tags=tags,
            ),
        )
        setattr(fn, "bind", types.MethodType(bind, fn))
        return fn

    return decorator


StateModel = TypeVar("StateModel", bound=pydantic.BaseModel)


class PydanticTypingSystem(TypingSystem[StateModel]):
    """Typing system for pydantic models.

    :param TypingSystem: Parameterized on the state model type.
    """

    def __init__(self, model_type: Type[StateModel]):
        self.model_type = model_type

    def state_type(self) -> Type[StateModel]:
        return self.model_type

    def state_pre_action_run_type(self, action: Action, graph: Graph) -> Type[pydantic.BaseModel]:
        raise NotImplementedError(
            "TODO -- crawl through"
            "the graph to figure out what can possibly be optional and what can't..."
            "First get all "
        )

    def state_post_action_run_type(self, action: Action, graph: Graph) -> Type[pydantic.BaseModel]:
        raise NotImplementedError(
            "TODO -- crawl through"
            "the graph to figure out what can possibly be optional and what can't..."
            "First get all "
        )

    def construct_data(self, state: State) -> StateModel:
        return model_from_state(model=self.model_type, state=state)

    def construct_state(self, data: StateModel) -> State:
        return State(model_to_dict(data))
