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

"""Base tooling, internal-facing, for lifecycle hooks. This is stolen from the
hamilton implementation, but significantly simplified."""
import asyncio
import collections
import contextlib
import inspect
from typing import TYPE_CHECKING, Callable, ContextManager, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    # type-checking-only for a circular import
    from burr.lifecycle.base import LifecycleAdapter

SYNC_HOOK = "hooks"
ASYNC_HOOK = "async_hooks"

REGISTERED_SYNC_HOOKS: Set[str] = set()
REGISTERED_ASYNC_HOOKS: Set[str] = set()


class InvalidLifecycleHook(Exception):
    """Container exception to indicate that a lifecycle adapter is invalid."""

    pass


def validate_hook_fn(fn: Callable):
    """Validates that a function forms a valid hook. This means:
    1. Function returns nothing
    2. Function must consist of only kwarg-only arguments

    :param fn: The function to validate
    :raises InvalidLifecycleAdapter: If the function is not a valid hook
    """
    sig = inspect.signature(fn)
    if (
        "future_kwargs" not in sig.parameters
        or sig.parameters["future_kwargs"].kind != inspect.Parameter.VAR_KEYWORD
    ):
        raise InvalidLifecycleHook(
            f"Lifecycle hooks must have a `**future_kwargs` argument. Method/hook {fn} does not."
        )
    for param in sig.parameters.values():
        if param.name != "future_kwargs":
            if param.kind != inspect.Parameter.KEYWORD_ONLY and param.name != "self":
                raise InvalidLifecycleHook(
                    f"Lifecycle hooks can only have keyword-only arguments. "
                    f"Method/hook {fn} has argument {param} that is not keyword-only."
                )


class lifecycle:
    """Container class for decorators to register hooks.
    This is just a container so it looks clean (`@lifecycle.base_hook(...)`), but we could easily move it out.
    What do these decorators do?
      1. We decorate a class with a method/hook/validator call
      2. This implies that there exists a function by that name
      3. We validate that that function has an appropriate signature
      4. We store this in the appropriate registry (see the constants above)
    Then, when we want to perform a hook/method/validator, we can ask the AdapterLifecycleSet to do so.
    It crawls up the MRO, looking to see which classes are in the registry, then elects which functions to run.
    See LifecycleAdapterSet for more information.
    """

    @classmethod
    def base_hook(cls, fn_name: str):
        """Hooks get called at distinct stages of Hamilton's execution.
        These can be layered together, and potentially coupled to other hooks.

        :param fn_name: Name of the function that will reside in the class we're decorating
        """

        def decorator(clazz):
            fn = getattr(clazz, fn_name, None)
            if fn is None:
                raise ValueError(
                    f"Class {clazz} does not have a method {fn_name}, but is "
                    f'decorated with @lifecycle.base_hook("{fn_name}"). The parameter '
                    f"to @lifecycle.base_hook must be the name "
                    f"of a method on the class."
                )
            validate_hook_fn(fn)
            if inspect.iscoroutinefunction(fn):
                setattr(clazz, ASYNC_HOOK, fn_name)
                REGISTERED_ASYNC_HOOKS.add(fn_name)
            else:
                setattr(clazz, SYNC_HOOK, fn_name)
                REGISTERED_SYNC_HOOKS.add(fn_name)
            return clazz

        return decorator


class LifecycleAdapterSet:
    """An internal class that groups together all the lifecycle adapters.
    This allows us to call methods through a delegation pattern, enabling us to add
    whatever callbacks, logging, error-handling, etc... we need globally. While this
    does increase the stack trace in an error, it should be pretty easy to figure out what's going on.
    """

    def __init__(
        self,
        *adapters: "LifecycleAdapter",
        hook_context: Optional[Callable[[], ContextManager]] = None,
    ):
        """Initializes the adapter set.

        :param adapters: Adapters to group together
        :param hook_context: Optional factory for a context manager entered around every hook
            dispatch (e.g. to set the serialization context).
        """
        self._adapters = list(adapters)
        self._hook_context = hook_context
        self.sync_hooks, self.async_hooks = self._get_lifecycle_hooks()

    def with_new_adapters(self, *adapters: "LifecycleAdapter") -> "LifecycleAdapterSet":
        """Adds new adapters to the set.

        :param adapters: Adapters to add
        :return: A new adapter set with the new adapters
        """
        return LifecycleAdapterSet(*self.adapters, *adapters, hook_context=self._hook_context)

    def with_hook_context(
        self, hook_context: Optional[Callable[[], ContextManager]]
    ) -> "LifecycleAdapterSet":
        """Returns a new adapter set that enters ``hook_context()`` around every hook dispatch.

        :param hook_context: Factory for the context manager to enter.
        :return: A new adapter set with the same adapters
        """
        return LifecycleAdapterSet(*self.adapters, hook_context=hook_context)

    def _enter_hook_context(self) -> ContextManager:
        return self._hook_context() if self._hook_context is not None else contextlib.nullcontext()

    @contextlib.contextmanager
    def action_scope(self, **kwargs):
        """Enters every adapter's optional ``action_scope`` around the action body.

        This is the *integration boundary* that ``pre_run_step`` cannot be. Lifecycle hooks are
        dispatched into their own tasks when the asynchronous family is gathered, and a
        :py:class:`contextvars.Context` write made in one task is invisible to the task that runs
        the action. An adapter that needs its state to be visible *while the action runs* -- the
        OpenTelemetry tracker making the step span current is the motivating case -- therefore
        cannot express that from a hook. It exposes ``action_scope`` instead: ``Application``
        enters it in the action's own task, immediately after ``pre_run_step`` and immediately
        before the action, and exits it before ``post_run_step``.

        Scopes are entered in adapter registration order and exited in reverse order, so nesting
        behaves like nested ``with`` statements. Adapters without an ``action_scope`` attribute
        are skipped, which keeps this purely additive: an adapter that does not opt in sees no
        difference, and neither does a dispatch strategy that keeps hooks in the caller's task.

        :param kwargs: Passed through to each adapter's ``action_scope``; the same keyword
            arguments a step hook receives.
        """
        with contextlib.ExitStack() as stack:
            for adapter in self._adapters:
                enter_scope = getattr(adapter, "action_scope", None)
                if enter_scope is None:
                    continue
                scope = enter_scope(**kwargs)
                if scope is not None:
                    stack.enter_context(scope)
            yield

    def _get_lifecycle_hooks(
        self,
    ) -> Tuple[Dict[str, List["LifecycleAdapter"]], Dict[str, List["LifecycleAdapter"]]]:
        sync_hooks = collections.defaultdict(list)
        async_hooks = collections.defaultdict(list)
        for adapter in self.adapters:
            for cls in inspect.getmro(adapter.__class__):
                sync_hook = getattr(cls, SYNC_HOOK, None)
                if sync_hook is not None:
                    if adapter not in sync_hooks[sync_hook]:
                        sync_hooks[sync_hook].append(adapter)
                async_hook = getattr(cls, ASYNC_HOOK, None)
                if async_hook is not None:
                    if adapter not in async_hooks[async_hook]:
                        async_hooks[async_hook].append(adapter)
        return (
            {hook: adapters for hook, adapters in sync_hooks.items()},
            {hook: adapters for hook, adapters in async_hooks.items()},
        )

    def _does_hook(self, hook_name: str, is_async: bool) -> bool:
        """Whether or not a hook is implemented by any of the adapters in this group.
        If this hook is not registered, this will raise a ValueError.

        :param hook_name: Name of the hook
        :param is_async: Whether you want the async version or not
        :return: True if this adapter set does this hook, False otherwise
        """
        if is_async and hook_name not in REGISTERED_ASYNC_HOOKS:
            raise ValueError(
                f"Hook {hook_name} is not registered as an asynchronous lifecycle hook. "
                f"Registered hooks are {REGISTERED_ASYNC_HOOKS}"
            )
        if not is_async and hook_name not in REGISTERED_SYNC_HOOKS:
            raise ValueError(
                f"Hook {hook_name} is not registered as a synchronous lifecycle hook. "
                f"Registered hooks are {REGISTERED_SYNC_HOOKS}"
            )
        if not is_async:
            return hook_name in self.sync_hooks
        return hook_name in self.async_hooks

    def call_all_lifecycle_hooks_sync(self, hook_name: str, **kwargs):
        """Calls all the lifecycle hooks in this group, by hook name (stage)

        :param hook_name: Name of the hooks to call
        :param kwargs: Keyword arguments to pass into the hook
        """
        if not self._does_hook(hook_name, False):
            return
        first_error: Optional[BaseException] = None
        with self._enter_hook_context():
            for adapter in self.sync_hooks[hook_name]:
                try:
                    getattr(adapter, hook_name)(**kwargs)
                except Exception as e:  # noqa: BLE001 - re-raised once every hook has run
                    # Mirror the asynchronous path: one failing hook (e.g. a tracker that
                    # cannot write its log) must not starve the ones registered after it.
                    first_error = first_error or e
        if first_error is not None:
            raise first_error

    async def call_all_lifecycle_hooks_async(self, hook_name: str, **kwargs):
        """Calls all the lifecycle hooks in this group, by hook name (stage).

        :param hook_name: Name of the hook
        :param kwargs: Keyword arguments to pass into the hook
        """
        if not self._does_hook(hook_name, True):
            return
        with self._enter_hook_context():
            futures = []
            for adapter in self.async_hooks[hook_name]:
                futures.append(getattr(adapter, hook_name)(**kwargs))
            if len(futures) == 0:
                return  # No async hooks to call
            await asyncio.gather(*futures)

    async def call_all_lifecycle_hooks_sync_and_async(self, hook_name: str, **kwargs):
        """Calls both the synchronous and the asynchronous hooks, by hook name (stage).

        Asynchronous hooks are awaited **in the calling task**, not gathered into child tasks.
        ``asyncio.gather`` wraps each coroutine in a :py:class:`asyncio.Task`, and a Task starts
        with a *copy* of the current :py:class:`contextvars.Context`. Writes made by a ``pre``
        hook (for example attaching an OpenTelemetry span, or setting the serialization context)
        therefore never reach the task that runs the action or the matching ``post`` hook; worse,
        a ``contextvars.Token`` created in that short-lived task cannot be reset from anywhere
        else. Awaiting in the caller's context keeps the ``pre`` hook, the action, and the ``post``
        hook in one context, which is what makes trace parenting and context restoration correct.
        It also isolates concurrent applications for free, since each already runs in its own task.

        :param hook_name: Name of the hook
        """
        first_error: Optional[BaseException] = None
        # The two families live in separate tables and are always dispatched in this order
        # (synchronous first, then asynchronous), so the ordering cannot be fixed by changing
        # registration order. A failing synchronous hook -- a sync tracker whose post hook
        # cannot write its log, say -- must therefore not abort the asynchronous phase, or an
        # async persister registered alongside it would never save the step.
        try:
            self.call_all_lifecycle_hooks_sync(hook_name, **kwargs)
        except asyncio.CancelledError:
            # Cancellation always propagates immediately; it is not an ordinary failure.
            raise
        except Exception as e:  # noqa: BLE001 - re-raised once both phases have run
            first_error = e

        if not self._does_hook(hook_name, True):
            if first_error is not None:
                raise first_error
            return

        with self._enter_hook_context():
            futures = [
                getattr(adapter, hook_name)(**kwargs)
                for adapter in self.async_hooks.get(hook_name, ())
            ]
            if len(futures) == 0:
                if first_error is not None:
                    raise first_error
                return
            # ``return_exceptions=True`` keeps the failure isolation the serial dispatcher
            # provides: one hook raising must not stop the others from running, and the first
            # failure is re-raised once every hook has finished.
            results = await asyncio.gather(*futures, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                if isinstance(result, asyncio.CancelledError):
                    # Cancellation is not an ordinary failure: it propagates as cancellation.
                    raise result
                first_error = first_error or result
        if first_error is not None:
            raise first_error

    @property
    def adapters(self) -> List["LifecycleAdapter"]:
        """Gives the adapters in this group

        :return: A list of adapters
        """
        return self._adapters
