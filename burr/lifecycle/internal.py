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
import inspect
from typing import TYPE_CHECKING, Callable, Dict, List, Set, Tuple

if TYPE_CHECKING:
    # type-checking-only for a circular import
    from burr.lifecycle.base import LifecycleAdapter

SYNC_HOOK = "hooks"
ASYNC_HOOK = "async_hooks"
INTERCEPTOR_TYPE = "interceptor_type"

REGISTERED_SYNC_HOOKS: Set[str] = set()
REGISTERED_ASYNC_HOOKS: Set[str] = set()
REGISTERED_INTERCEPTORS: Set[str] = set()


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


def validate_interceptor_method(fn: Callable, method_name: str):
    """Validates that an interceptor method has the correct signature.
    Interceptor methods must have keyword-only arguments (including **future_kwargs).

    :param fn: The function to validate
    :param method_name: Name of the method being validated
    :raises InvalidLifecycleHook: If the function is not a valid interceptor method
    """
    if fn is None:
        raise InvalidLifecycleHook(f"Interceptor method {method_name} does not exist on the class.")
    sig = inspect.signature(fn)
    # Check for **future_kwargs
    if (
        "future_kwargs" not in sig.parameters
        or sig.parameters["future_kwargs"].kind != inspect.Parameter.VAR_KEYWORD
    ):
        raise InvalidLifecycleHook(
            f"Interceptor method {method_name} must have a `**future_kwargs` argument. "
            f"Method {fn} does not."
        )
    # All non-self, non-future_kwargs parameters must be keyword-only
    for param in sig.parameters.values():
        if param.name not in ("future_kwargs", "self"):
            if param.kind != inspect.Parameter.KEYWORD_ONLY:
                raise InvalidLifecycleHook(
                    f"Interceptor method {method_name} can only have keyword-only arguments. "
                    f"Method {fn} has argument {param} that is not keyword-only."
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

    @classmethod
    def interceptor_hook(
        cls,
        interceptor_type: str,
        should_intercept_method: str = "should_intercept",
        intercept_method: str = "intercept_run",
    ):
        """Decorator for interceptor hooks that can wrap/replace action execution.

        Interceptors have two methods:
        1. should_intercept() - determines if an action should be intercepted
        2. intercept_run() or intercept_stream_run_and_update() - replaces the execution

        :param interceptor_type: Type identifier for the interceptor (e.g., "intercept_action_execution", "intercept_streaming_action")
        :param should_intercept_method: Name of the should_intercept method (default: "should_intercept")
        :param intercept_method: Name of the intercept method (default: "intercept_run" or "intercept_stream_run_and_update")
        """

        def decorator(clazz):
            # Validate should_intercept method
            should_intercept_fn = getattr(clazz, should_intercept_method, None)
            validate_interceptor_method(should_intercept_fn, should_intercept_method)

            # Validate intercept method
            intercept_fn = getattr(clazz, intercept_method, None)
            validate_interceptor_method(intercept_fn, intercept_method)

            # Register the interceptor type
            setattr(clazz, INTERCEPTOR_TYPE, interceptor_type)
            REGISTERED_INTERCEPTORS.add(interceptor_type)

            return clazz

        return decorator


class LifecycleAdapterSet:
    """An internal class that groups together all the lifecycle adapters.
    This allows us to call methods through a delegation pattern, enabling us to add
    whatever callbacks, logging, error-handling, etc... we need globally. While this
    does increase the stack trace in an error, it should be pretty easy to figure out what's going on.
    """

    def __init__(self, *adapters: "LifecycleAdapter"):
        """Initializes the adapter set.

        :param adapters: Adapters to group together
        """
        self._adapters = list(adapters)
        self._sync_hooks, self._async_hooks = self._get_lifecycle_hooks()

    @property
    def sync_hooks(self):
        return self._sync_hooks

    @property
    def async_hooks(self):
        return self._async_hooks

    def with_new_adapters(self, *adapters: "LifecycleAdapter") -> "LifecycleAdapterSet":
        """Adds new adapters to the set.

        :param adapters: Adapters to add
        :return: A new adapter set with the new adapters
        """
        return LifecycleAdapterSet(*self.adapters, *adapters)

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
        for adapter in self.sync_hooks[hook_name]:
            getattr(adapter, hook_name)(**kwargs)

    async def call_all_lifecycle_hooks_async(self, hook_name: str, **kwargs):
        """Calls all the lifecycle hooks in this group, by hook name (stage).

        :param hook_name: Name of the hook
        :param kwargs: Keyword arguments to pass into the hook
        """
        if not self._does_hook(hook_name, True):
            return
        futures = []
        for adapter in self.async_hooks[hook_name]:
            futures.append(getattr(adapter, hook_name)(**kwargs))
        if len(futures) == 0:
            return  # No async hooks to call
        await asyncio.gather(*futures)

    async def call_all_lifecycle_hooks_sync_and_async(self, hook_name: str, **kwargs):
        """Calls all the lifecycle hooks in this group, by hook name (stage).

        :param hook_name: Name of the hook
        """
        self.call_all_lifecycle_hooks_sync(hook_name, **kwargs)
        await self.call_all_lifecycle_hooks_async(hook_name, **kwargs)

    @property
    def adapters(self) -> List["LifecycleAdapter"]:
        """Gives the adapters in this group

        :return: A list of adapters
        """
        return self._adapters

    def get_first_matching_hook(
        self, hook_name: str, predicate: Callable[["LifecycleAdapter"], bool]
    ):
        """Get first hook of given type that matches predicate.

        For interceptor hooks, this uses the registered interceptor types to find
        matching interceptors. For standard hooks, it uses the hook registry.

        :param hook_name: Name of the hook to search for (or interceptor type)
        :param predicate: Function that takes a hook and returns True if it matches
        :return: The first matching hook, or None if no match found
        """
        # Check if this is a registered interceptor type
        if hook_name in REGISTERED_INTERCEPTORS:
            # Search for adapters with this interceptor type
            for adapter in self.adapters:
                for cls in inspect.getmro(adapter.__class__):
                    interceptor_type = getattr(cls, INTERCEPTOR_TYPE, None)
                    if interceptor_type == hook_name:
                        if predicate(adapter):
                            return adapter
            return None

        # Standard hook lookup for registered hooks
        hooks = self.sync_hooks.get(hook_name, []) + self.async_hooks.get(hook_name, [])
        for hook in hooks:
            if predicate(hook):
                return hook
        return None

    def get_worker_adapter_set(self) -> "LifecycleAdapterSet":
        """Create a new LifecycleAdapterSet containing only worker hooks.
        Worker hooks are those with names ending in '_worker' and are designed
        to be called on remote execution environments (Ray/Temporal workers).

        :return: A new LifecycleAdapterSet with only worker hooks
        """
        worker_hooks = []
        for adapter in self.adapters:
            # Check if this adapter is a worker hook by looking at its registered hooks
            is_worker = False
            for cls in inspect.getmro(adapter.__class__):
                sync_hook = getattr(cls, SYNC_HOOK, None)
                async_hook = getattr(cls, ASYNC_HOOK, None)
                if (sync_hook and sync_hook.endswith("_worker")) or (
                    async_hook and async_hook.endswith("_worker")
                ):
                    is_worker = True
                    break
            if is_worker:
                worker_hooks.append(adapter)
        return LifecycleAdapterSet(*worker_hooks)
