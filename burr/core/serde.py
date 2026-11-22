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
from typing import TYPE_CHECKING, Any, Dict, Iterator, Optional, Union

if TYPE_CHECKING:
    from burr.core.artifacts import ArtifactStore, AsyncArtifactStore

KEY = "__burr_serde__"
# Marker used to wrap an ordinary dictionary that itself contains KEY. Without
# it, such a dictionary is indistinguishable from a serde envelope and
# `deserialize` fails -- or dispatches to an unrelated deserializer -- when the
# value is read back.
ESCAPED_DICT = "burr.dict"
# Key an escaped dictionary stores its contents under.
PAYLOAD_KEY = "value"

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

    One context belongs to one :py:class:`~burr.core.application.Application` and is shared by
    every step of that application, by its persister and tracker, and by the load that resumes it.
    Two applications never share one.

    :param object_store: The application's configured artifact store, if any.
    :param memo: Per-application scratch space for serializers to cache by content hash, so an
        unchanged value costs one in-memory hash and no store I/O. Burr does not interpret it.
        Use it as a cache key, not as an identity key: if a serialized payload carries anything
        besides the artifact reference (a filename, a media type, a row count), either recompute
        that part on every call or include it in the key -- two values with identical content and
        different metadata otherwise resume with each other's metadata. The deserializer of the
        matching key should re-seed it on resume so the first persist after a resume is free.
    """

    object_store: Optional[Union["ArtifactStore", "AsyncArtifactStore"]] = None
    # ``compare``/``hash`` are off so the context keeps the identity and hashability it had before
    # the memo existed: it is equal to another context wrapping the same store, and a memo (a mutable
    # dict) does not participate in comparisons or hashing.
    memo: Dict[str, Any] = dataclasses.field(default_factory=dict, compare=False, hash=False)

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


def _ensure_not_still_awaitable(result: Any, description: str) -> Any:
    """Raises if an async (de)serializer's already-awaited result is itself awaitable.

    ``await`` resolves exactly one level, so an ``async def`` (de)serializer that returns another
    coroutine -- a missing inner ``await``, typically an un-awaited store call -- would otherwise
    hand a coroutine to the caller, which then either fails to ``json.dumps`` much later or is
    collected with a "coroutine was never awaited" warning.
    """
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()  # avoid a "coroutine was never awaited" warning
        raise ValueError(
            f"The {description} returned an awaitable from asynchronous (de)serialization, so its "
            f"result was never resolved. An `async def` (de)serializer must return the final value; "
            f"an inner `await` is probably missing."
        )
    return result


# --- serialization-context injection -------------------------------------------------------------
#
# ``SerializationContext`` reaches (de)serializers as the ``serialization_context`` kwarg. Type-based
# and field-based registries predate that kwarg, and nothing has ever required the functions
# registered for a type to accept ``**kwargs`` -- ``def serialize_x(value): ...`` is legal and is what
# the docs showed for years. Injecting the kwarg unconditionally therefore breaks every pre-existing
# serializer as soon as an application configures an object store, which is exactly the case the
# feature is meant to serve.
#
# So the kwarg is dropped for targets that cannot accept it. The decision is a property of the
# function, not of the call, so it is computed once per function and cached; the cache is keyed by
# the callable itself, so re-registering a type with a different function picks up that function's
# own signature.
_CONTEXT_CACHE: Dict[Any, bool] = {}
# Serializer registries are small and process-global, so the cache is naturally bounded. The cap
# only guards against callables created per call (e.g. a callable object instantiated inside a loop).
_CONTEXT_CACHE_MAXSIZE = 4096


def _inspect_accepts_context(func: Any) -> bool:
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        # Not introspectable (C callables, exotic proxies). Assume it is a legacy serializer: passing
        # an unexpected kwarg would raise, whereas omitting it only costs a context the function
        # could not have declared.
        return False
    for parameter in parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if (
            parameter.name == SERIALIZATION_CONTEXT_KWARG
            # positional-only parameters cannot be filled by keyword
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        ):
            return True
    return False


def _accepts_serialization_context(func: Any) -> bool:
    """Whether ``func`` can be called with the ``serialization_context`` kwarg.

    :param func: A (de)serializer.
    :return: ``True`` if it declares ``**kwargs`` or a ``serialization_context`` parameter.
    """
    try:
        return _CONTEXT_CACHE[func]
    except KeyError:
        pass
    except TypeError:
        # unhashable callable -- compute it every time rather than fail
        return _inspect_accepts_context(func)
    accepted = _inspect_accepts_context(func)
    if len(_CONTEXT_CACHE) >= _CONTEXT_CACHE_MAXSIZE:
        _CONTEXT_CACHE.clear()
    _CONTEXT_CACHE[func] = accepted
    return accepted


def _drop_unsupported_context(func: Any, kwargs: dict) -> dict:
    """Removes ``serialization_context`` from ``kwargs`` unless ``func`` can accept it.

    Only that one key is removed: any other kwargs the caller passed are the serializer's own and
    are forwarded unchanged. Nothing is retried, so a serializer that raises ``TypeError`` itself
    still propagates it, and no side effect is ever executed twice.

    :param func: The (de)serializer about to be called.
    :param kwargs: The kwargs it would be called with.
    :return: ``kwargs``, or a copy without ``serialization_context``.
    """
    if _accepts_serialization_context(func) or SERIALIZATION_CONTEXT_KWARG not in kwargs:
        # nothing to do -- either the target takes the context, or there is none to drop
        return kwargs
    if len(kwargs) == 1:
        # the context is the only kwarg -- the common case, so skip building a filtered copy
        return {}
    return {k: v for k, v in kwargs.items() if k != SERIALIZATION_CONTEXT_KWARG}


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
            func = self.func_map[key]
            if SERIALIZATION_CONTEXT_KWARG in kwargs:
                kwargs = _drop_unsupported_context(func, kwargs)
            return func(*args, **kwargs)
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
def _serialize_impl(value, **kwargs) -> Any:
    """Default implementation for serializing a value -- see :py:func:`serialize`."""
    if value is None:
        return None
    return str(value)


def serialize(value, *args, **kwargs) -> Any:
    """This is the default implementation for serializing a value.

    All other implementations should be registered with the `@serialize.register` decorator.

    Each function should output a dictionary, and include the `KEY` & value to use for deserialization.

    Implementations receive the current
    :py:class:`~burr.core.serde.SerializationContext` as ``serialization_context`` if they can accept
    it -- i.e. if they declare ``**kwargs`` or a ``serialization_context`` parameter. A serializer
    registered without either keeps working unchanged when an application configures an object
    store; it simply does not see the context.

    :param value: The value to serialize
    :param kwargs: Any additional keyword arguments. Each implementation should namespace their kwargs.
    :return: A dictionary representation of the value
    """
    func = _serialize_impl.dispatch(value.__class__)
    if SERIALIZATION_CONTEXT_KWARG in kwargs:
        kwargs = _drop_unsupported_context(func, kwargs)
    return func(value, *args, **kwargs)


def _clear_serialize_cache() -> None:
    """Drops the dispatch cache and the cached ``serialization_context`` decisions."""
    clear = getattr(_serialize_impl, "_clear_cache", None)
    if clear is not None:
        clear()
    _CONTEXT_CACHE.clear()


# Mirror ``functools.singledispatch``'s public surface so that ``@serialize.register(...)``,
# ``serialize.dispatch(...)`` and ``serialize.registry`` behave exactly as they did when
# ``serialize`` *was* the dispatcher. The registry holds the user's functions themselves, not
# wrappers, so identity checks (``serialize.dispatch(t) is serialize_dict``) and introspection of
# registered implementations are unaffected.
serialize.register = _serialize_impl.register
serialize.dispatch = _serialize_impl.dispatch
serialize.registry = _serialize_impl.registry
serialize._clear_cache = _clear_serialize_cache


@serialize.register(str)
@serialize.register(int)
@serialize.register(float)
@serialize.register(bool)
def serialize_primitive(value, **kwargs) -> Union[str, int, float, bool]:
    return value


@serialize.register(types.CoroutineType)
def serialize_coroutine(value: types.CoroutineType, **kwargs) -> Any:
    """Rejects a coroutine that reached serialization as a value.

    A coroutine is never a valid payload: the previous fallback (``str(value)``) persisted
    ``"<coroutine object ...>"``, silently losing the value and leaving the coroutine un-awaited.
    The two ways to get here are a serializer that called an async API without awaiting it, and a
    coroutine placed in state by an action. Both are errors, so this raises for both -- the
    behavior change is called out in the release notes.
    """
    value.close()  # avoid a "coroutine was never awaited" warning
    raise ValueError(
        "Cannot serialize a coroutine. Either a serializer called an async API (e.g. "
        "AsyncArtifactStore.put_artifact) without awaiting it, or a coroutine was put in state. Use "
        "an `async def` serializer (awaited by `State.aserialize`, as async persisters do), or a "
        "synchronous object store, and store the value the coroutine produces rather than the "
        "coroutine itself."
    )


@serialize.register(dict)
def serialize_dict(value: dict, **kwargs) -> dict[str, Any]:
    serialized = {k: _serialize_sync(v, **kwargs) for k, v in value.items()}
    if KEY in value:
        return {KEY: ESCAPED_DICT, PAYLOAD_KEY: serialized}
    return serialized


@deserializer.register(ESCAPED_DICT)
def deserialize_escaped_dict(value: dict, **kwargs) -> dict[str, Any]:
    """Deserializes an ordinary dictionary that carries the serde marker key."""
    return {k: deserialize(v, **kwargs) for k, v in value[PAYLOAD_KEY].items()}


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
        serialized = {k: await aserialize(v, **kwargs) for k, v in value.items()}
        if KEY in value:
            return {KEY: ESCAPED_DICT, PAYLOAD_KEY: serialized}
        return serialized
    if isinstance(value, list) and serialize.dispatch(type(value)) is serialize_list:
        return [await aserialize(v, **kwargs) for v in value]
    result = serialize(value, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return _ensure_not_still_awaitable(result, f"serializer registered for {type(value).__name__}")


async def adeserialize(value: Any, **kwargs) -> Any:
    """Asynchronous counterpart to :py:func:`deserialize` -- awaits deserializers registered as
    ``async def`` functions, and calls synchronous ones as usual.

    :param value: The value to deserialize
    :param kwargs: Additional keyword arguments, passed to each deserializer.
    :return: The deserialized value.
    """
    if isinstance(value, dict):
        class_to_instantiate = value.get(KEY, None)
        if class_to_instantiate == ESCAPED_DICT:
            return {k: await adeserialize(v, **kwargs) for k, v in value[PAYLOAD_KEY].items()}
        if class_to_instantiate is not None:
            result = deserializer.call(class_to_instantiate, value, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return _ensure_not_still_awaitable(
                result, f"deserializer registered for '{class_to_instantiate}'"
            )
        return {k: await adeserialize(v, **kwargs) for k, v in value.items()}
    elif isinstance(value, list):
        return [await adeserialize(v, **kwargs) for v in value]
    return value
