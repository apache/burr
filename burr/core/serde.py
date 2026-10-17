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

import contextlib
import contextvars
import dataclasses
import inspect
import types
from functools import singledispatch
from typing import TYPE_CHECKING, Any, Iterator, Optional, Union

if TYPE_CHECKING:
    from burr.core.artifacts import ArtifactStore, AsyncArtifactStore

KEY = "__burr_serde__"

SERIALIZATION_CONTEXT_KWARG = "serialization_context"


@dataclasses.dataclass(frozen=True)
class SerializationContext:
    """Application-scoped services made available to serializers and deserializers.

    Passed to every type-based and field-based (de)serializer as the ``serialization_context``
    kwarg when the application has an object store (see
    :py:meth:`~burr.core.application.ApplicationBuilder.with_object_store`) or one was set via
    :py:func:`serialization_context`. This lets a serializer externalize a large value:

    .. code-block:: python

        @serde.serialize.register(PDF)
        def serialize_pdf(value: PDF, serialization_context: SerializationContext = None, **kwargs) -> dict:
            store = serialization_context.require_object_store()
            ref = store.put_artifact(value.to_bytes(), media_type="application/pdf")
            return {serde.KEY: "pdf", "ref": serde.serialize(ref)}

    :param object_store: The application's configured artifact store, if any.
    """

    object_store: Optional[Union["ArtifactStore", "AsyncArtifactStore"]] = None

    def require_object_store(self) -> Union["ArtifactStore", "AsyncArtifactStore"]:
        """Returns the configured object store, raising a clear error if there is none.

        :raises ValueError: If no object store is configured.
        """
        if self.object_store is None:
            raise ValueError(
                "This serializer requires an object store, but none is configured. Configure one "
                "with ApplicationBuilder.with_object_store(...), or pass "
                "serialization_context=SerializationContext(object_store=...) when serializing "
                "outside of a running application."
            )
        return self.object_store


_current_serialization_context = contextvars.ContextVar[Optional[SerializationContext]](
    "burr_serialization_context", default=None
)


def get_serialization_context() -> Optional[SerializationContext]:
    """Returns the serialization context currently in effect, if any.

    :return: The current :py:class:`SerializationContext`, or ``None``.
    """
    return _current_serialization_context.get()


@contextlib.contextmanager
def serialization_context(context: Optional[SerializationContext]) -> Iterator[None]:
    """Makes ``context`` current within the ``with`` block -- for (de)serializing state outside
    of a running application:

    .. code-block:: python

        with serde.serialization_context(SerializationContext(object_store=store)):
            data = persister.load(partition_key, app_id)

    :param context: The context to make current, or ``None`` to clear it.
    """
    token = _current_serialization_context.set(context)
    try:
        yield
    finally:
        _current_serialization_context.reset(token)


def with_serialization_context(kwargs: dict) -> dict:
    """Adds the current serialization context to serde kwargs, unless one was passed explicitly.
    Only needed by custom persisters/trackers that call :py:func:`serialize` directly.

    :param kwargs: The serde kwargs to augment.
    :return: The (possibly new) kwargs dict.
    """
    if SERIALIZATION_CONTEXT_KWARG in kwargs:
        return kwargs
    context = get_serialization_context()
    if context is None:
        return kwargs
    return {**kwargs, SERIALIZATION_CONTEXT_KWARG: context}


def ensure_not_awaitable(result: Any, description: str) -> Any:
    """Raises a clear error if a (de)serializer returned an awaitable in synchronous serialization.

    :param result: The (de)serializer's return value.
    :param description: What produced it, for the error message.
    :return: ``result``, unchanged.
    """
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()  # avoid a "coroutine was never awaited" warning
        raise ValueError(
            f"The {description} is asynchronous, so it cannot be used from synchronous "
            f"serialization. Use `await state.aserialize()`/`await State.adeserialize()` -- which "
            f"async persisters (e.g. AsyncSQLitePersister) do -- or register a synchronous "
            f"(de)serializer instead. Note that synchronous trackers/persisters cannot use async "
            f"(de)serializers."
        )
    return result


class StringDispatch:
    """Class to capture how to deserialize something.

    We register a key with a deserializer function. It's like single dispatch
    but based on a string key value.

    Example usage:

    .. code-block:: python

        from burr.core import serde

        @serde.deserializer.register("pickle")
        def deserialize_pickle(value: dict, pickle_kwargs: dict = None, **kwargs) -> cls:
            if pickle_kwargs is None:
                pickle_kwargs = {}
            return pickle.loads(value["value"], **pickle_kwargs)

    What this does is register the function `deserialize_pickle` with the key "pickle".
    This should mirror the appropriate serialization function - which is what sets the key value
    to match the deserializer function against.

    Notice that this namespaces its kwargs. This is important because we don't want to have
    a collision with other kwargs that might be passed in.
    """

    def __init__(self):
        self.func_map = {}

    def register(self, key):
        def decorator(func):
            self.func_map[key] = func
            return func

        return decorator

    def call(self, key, *args, **kwargs):
        if key in self.func_map:
            return self.func_map[key](*args, **kwargs)
        else:
            raise ValueError(
                f"No deserializer registered for key: '{key}'. "
                f"Registered keys: {sorted(self.func_map)}. "
                f"Make sure the module registering the deserializer for '{key}' has been "
                f"imported (e.g. `import burr.integrations.serde.pandas` for 'pandas.DataFrame')."
            )


deserializer = StringDispatch()


def deserialize(value: Any, **kwargs) -> Any:
    """Main function to deserialize a value.

    Looks for a key in the value if it's a dictionary and calls the appropriate deserializer function.
    """
    if isinstance(value, dict):
        class_to_instantiate = value.get(KEY, None)
        if class_to_instantiate is not None:
            return ensure_not_awaitable(
                deserializer.call(class_to_instantiate, value, **kwargs),
                f"deserializer registered for '{class_to_instantiate}'",
            )
        else:
            return {k: deserialize(v, **kwargs) for k, v in value.items()}
    elif isinstance(value, list):
        return [deserialize(v, **kwargs) for v in value]
    else:
        return value


@singledispatch
def serialize(value, **kwargs) -> Any:
    """This is the default implementation for serializing a value.

    All other implementations should be registered with the `@serialize.register` decorator.

    Each function should output a dictionary, and include the `KEY` & value to use for deserialization.

    :param value: The value to serialize
    :param kwargs: Any additional keyword arguments. Each implementation should namespace their kwargs.
    :return: A dictionary representation of the value
    """
    if value is None:
        return None
    return str(value)


@serialize.register(str)
@serialize.register(int)
@serialize.register(float)
@serialize.register(bool)
def serialize_primitive(value, **kwargs) -> Union[str, int, float, bool]:
    return value


@serialize.register(types.CoroutineType)
def serialize_coroutine(value: types.CoroutineType, **kwargs) -> Any:
    value.close()  # avoid a "coroutine was never awaited" warning
    raise ValueError(
        "Cannot serialize a coroutine -- a serializer likely called an async API (e.g. "
        "AsyncArtifactStore.put_artifact) without awaiting it. Use an `async def` serializer "
        "(awaited by `State.aserialize`, as async persisters do), or a synchronous object store."
    )


@serialize.register(dict)
def serialize_dict(value: dict, **kwargs) -> dict[str, Any]:
    return {k: _serialize_sync(v, **kwargs) for k, v in value.items()}


@serialize.register(list)
def serialize_list(value: list, **kwargs) -> list[Any]:
    return [_serialize_sync(v, **kwargs) for v in value]


def _serialize_sync(value: Any, **kwargs) -> Any:
    return ensure_not_awaitable(
        serialize(value, **kwargs), f"serializer registered for {type(value).__name__}"
    )


async def aserialize(value: Any, **kwargs) -> Any:
    """Asynchronous counterpart to :py:func:`serialize` -- awaits serializers registered as
    ``async def`` functions, and calls synchronous ones as usual.

    :param value: The value to serialize
    :param kwargs: Additional keyword arguments, passed to each serializer.
    :return: A JSON-serializable representation of the value.
    """
    if isinstance(value, dict) and serialize.dispatch(type(value)) is serialize_dict:
        return {k: await aserialize(v, **kwargs) for k, v in value.items()}
    if isinstance(value, list) and serialize.dispatch(type(value)) is serialize_list:
        return [await aserialize(v, **kwargs) for v in value]
    result = serialize(value, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


async def adeserialize(value: Any, **kwargs) -> Any:
    """Asynchronous counterpart to :py:func:`deserialize` -- awaits deserializers registered as
    ``async def`` functions, and calls synchronous ones as usual.

    :param value: The value to deserialize
    :param kwargs: Additional keyword arguments, passed to each deserializer.
    :return: The deserialized value.
    """
    if isinstance(value, dict):
        class_to_instantiate = value.get(KEY, None)
        if class_to_instantiate is not None:
            result = deserializer.call(class_to_instantiate, value, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        return {k: await adeserialize(v, **kwargs) for k, v in value.items()}
    elif isinstance(value, list):
        return [await adeserialize(v, **kwargs) for v in value]
    return value
