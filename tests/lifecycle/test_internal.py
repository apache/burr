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

"""Unit tests for lifecycle internal functions and decorators."""
import abc
import inspect
from typing import Any, Dict

import pytest

from burr.lifecycle.internal import (
    INTERCEPTOR_TYPE,
    REGISTERED_INTERCEPTORS,
    InvalidLifecycleHook,
    LifecycleAdapterSet,
    lifecycle,
    validate_interceptor_method,
)


class TestValidateInterceptorMethod:
    """Tests for validate_interceptor_method function."""

    def test_valid_interceptor_method_with_future_kwargs(self):
        """Test that a valid interceptor method with **future_kwargs passes validation."""

        def valid_method(self, *, action: Any, **future_kwargs: Any) -> bool:
            return True

        # Should not raise
        validate_interceptor_method(valid_method, "valid_method")

    def test_valid_interceptor_method_with_multiple_keyword_args(self):
        """Test that a valid interceptor method with multiple keyword-only args passes."""

        def valid_method(
            self, *, action: Any, state: Any, inputs: Dict[str, Any], **future_kwargs: Any
        ) -> dict:
            return {}

        # Should not raise
        validate_interceptor_method(valid_method, "valid_method")

    def test_valid_async_interceptor_method(self):
        """Test that async interceptor methods are validated correctly."""

        async def valid_async_method(self, *, action: Any, **future_kwargs: Any) -> bool:
            return True

        # Should not raise
        validate_interceptor_method(valid_async_method, "valid_async_method")

    def test_missing_future_kwargs_raises_error(self):
        """Test that missing **future_kwargs raises InvalidLifecycleHook."""

        def invalid_method(self, *, action: Any) -> bool:
            return True

        with pytest.raises(InvalidLifecycleHook) as exc_info:
            validate_interceptor_method(invalid_method, "invalid_method")

        assert "must have a `**future_kwargs` argument" in str(exc_info.value)

    def test_positional_args_raises_error(self):
        """Test that positional arguments (non-keyword-only) raise error."""

        def invalid_method(self, action: Any, **future_kwargs: Any) -> bool:
            return True

        with pytest.raises(InvalidLifecycleHook) as exc_info:
            validate_interceptor_method(invalid_method, "invalid_method")

        assert "can only have keyword-only arguments" in str(exc_info.value)

    def test_none_method_raises_error(self):
        """Test that None method raises InvalidLifecycleHook."""

        with pytest.raises(InvalidLifecycleHook) as exc_info:
            validate_interceptor_method(None, "missing_method")

        assert "does not exist on the class" in str(exc_info.value)

    def test_var_keyword_not_named_future_kwargs_raises_error(self):
        """Test that **kwargs (not **future_kwargs) raises error."""

        def invalid_method(self, *, action: Any, **kwargs: Any) -> bool:
            return True

        with pytest.raises(InvalidLifecycleHook) as exc_info:
            validate_interceptor_method(invalid_method, "invalid_method")

        assert "must have a `**future_kwargs` argument" in str(exc_info.value)


class TestInterceptorHookDecorator:
    """Tests for @lifecycle.interceptor_hook decorator."""

    def test_interceptor_hook_registers_type(self):
        """Test that @lifecycle.interceptor_hook registers the interceptor type."""

        @lifecycle.interceptor_hook("test_interceptor_type")
        class TestInterceptor(abc.ABC):
            @abc.abstractmethod
            def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                pass

            @abc.abstractmethod
            def intercept_run(self, *, action: Any, state: Any, **future_kwargs: Any) -> dict:
                pass

        # Check that interceptor type is registered
        assert "test_interceptor_type" in REGISTERED_INTERCEPTORS

        # Check that class has interceptor_type attribute
        assert hasattr(TestInterceptor, INTERCEPTOR_TYPE)
        assert getattr(TestInterceptor, INTERCEPTOR_TYPE) == "test_interceptor_type"

    def test_interceptor_hook_with_custom_method_names(self):
        """Test that @lifecycle.interceptor_hook works with custom method names."""

        @lifecycle.interceptor_hook(
            "custom_interceptor", should_intercept_method="should_handle", intercept_method="handle"
        )
        class CustomInterceptor(abc.ABC):
            @abc.abstractmethod
            def should_handle(self, *, action: Any, **future_kwargs: Any) -> bool:
                pass

            @abc.abstractmethod
            def handle(self, *, action: Any, state: Any, **future_kwargs: Any) -> dict:
                pass

        # Check that interceptor type is registered
        assert "custom_interceptor" in REGISTERED_INTERCEPTORS
        assert getattr(CustomInterceptor, INTERCEPTOR_TYPE) == "custom_interceptor"

    def test_interceptor_hook_validates_should_intercept_method(self):
        """Test that decorator validates should_intercept method signature."""

        with pytest.raises(InvalidLifecycleHook):

            @lifecycle.interceptor_hook("invalid_interceptor")
            class InvalidInterceptor(abc.ABC):
                # Missing **future_kwargs
                @abc.abstractmethod
                def should_intercept(self, *, action: Any) -> bool:
                    pass

                @abc.abstractmethod
                def intercept_run(self, *, action: Any, **future_kwargs: Any) -> dict:
                    pass

    def test_interceptor_hook_validates_intercept_method(self):
        """Test that decorator validates intercept method signature."""

        with pytest.raises(InvalidLifecycleHook):

            @lifecycle.interceptor_hook("invalid_interceptor")
            class InvalidInterceptor(abc.ABC):
                @abc.abstractmethod
                def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                    pass

                # Missing **future_kwargs
                @abc.abstractmethod
                def intercept_run(self, *, action: Any) -> dict:
                    pass

    def test_interceptor_hook_validates_missing_method(self):
        """Test that decorator raises error if method doesn't exist."""

        with pytest.raises(InvalidLifecycleHook):

            @lifecycle.interceptor_hook("missing_method_interceptor")
            class MissingMethodInterceptor(abc.ABC):
                @abc.abstractmethod
                def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                    pass

                # intercept_run is missing

    def test_interceptor_hook_with_streaming_method(self):
        """Test that decorator works with intercept_stream_run_and_update method."""

        @lifecycle.interceptor_hook(
            "streaming_interceptor", intercept_method="intercept_stream_run_and_update"
        )
        class StreamingInterceptor(abc.ABC):
            @abc.abstractmethod
            def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                pass

            @abc.abstractmethod
            def intercept_stream_run_and_update(
                self, *, action: Any, state: Any, **future_kwargs: Any
            ):
                pass

        assert "streaming_interceptor" in REGISTERED_INTERCEPTORS
        assert getattr(StreamingInterceptor, INTERCEPTOR_TYPE) == "streaming_interceptor"

    def test_interceptor_hook_preserves_class(self):
        """Test that decorator returns the class unchanged (for chaining)."""

        @lifecycle.interceptor_hook("preserved_interceptor")
        class PreservedInterceptor(abc.ABC):
            @abc.abstractmethod
            def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                pass

            @abc.abstractmethod
            def intercept_run(self, *, action: Any, **future_kwargs: Any) -> dict:
                pass

        # Class should still be usable
        assert PreservedInterceptor.__name__ == "PreservedInterceptor"
        assert inspect.isabstract(PreservedInterceptor)


class TestGetFirstMatchingHookWithInterceptors:
    """Tests for get_first_matching_hook with registered interceptors."""

    def test_get_first_matching_interceptor_by_type(self):
        """Test that get_first_matching_hook finds interceptors by registered type."""

        @lifecycle.interceptor_hook("test_find_interceptor")
        class FindableInterceptor:
            def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                return True

            def intercept_run(self, *, action: Any, state: Any, **future_kwargs: Any) -> dict:
                return {}

        interceptor = FindableInterceptor()
        adapter_set = LifecycleAdapterSet(interceptor)

        # Should find the interceptor
        found = adapter_set.get_first_matching_hook(
            "test_find_interceptor", lambda hook: hook.should_intercept(action=None)
        )

        assert found is interceptor

    def test_get_first_matching_interceptor_with_predicate(self):
        """Test that predicate filters interceptors correctly."""

        @lifecycle.interceptor_hook("test_predicate_interceptor")
        class MatchingInterceptor:
            def __init__(self, tag: str):
                self.tag = tag

            def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                return getattr(action, "tag", None) == self.tag

            def intercept_run(self, *, action: Any, state: Any, **future_kwargs: Any) -> dict:
                return {}

        class MockAction:
            def __init__(self, tag: str):
                self.tag = tag

        interceptor1 = MatchingInterceptor("tag1")
        interceptor2 = MatchingInterceptor("tag2")
        adapter_set = LifecycleAdapterSet(interceptor1, interceptor2)

        # Should find first matching interceptor
        found = adapter_set.get_first_matching_hook(
            "test_predicate_interceptor",
            lambda hook: hook.should_intercept(action=MockAction("tag1")),
        )

        assert found is interceptor1

    def test_get_first_matching_interceptor_returns_none_if_no_match(self):
        """Test that get_first_matching_hook returns None if no interceptor matches."""

        @lifecycle.interceptor_hook("test_no_match_interceptor")
        class NonMatchingInterceptor:
            def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                return False

            def intercept_run(self, *, action: Any, state: Any, **future_kwargs: Any) -> dict:
                return {}

        interceptor = NonMatchingInterceptor()
        adapter_set = LifecycleAdapterSet(interceptor)

        # Should return None when predicate doesn't match
        found = adapter_set.get_first_matching_hook(
            "test_no_match_interceptor", lambda hook: hook.should_intercept(action=None)
        )

        assert found is None

    def test_get_first_matching_interceptor_returns_none_if_not_registered(self):
        """Test that unregistered interceptor types return None."""

        adapter_set = LifecycleAdapterSet()

        # Should return None for unregistered interceptor type
        found = adapter_set.get_first_matching_hook(
            "unregistered_interceptor_type", lambda hook: True
        )

        assert found is None

    def test_get_first_matching_interceptor_inheritance(self):
        """Test that interceptor discovery works with inheritance."""

        @lifecycle.interceptor_hook("test_inheritance_interceptor")
        class BaseInterceptor(abc.ABC):
            @abc.abstractmethod
            def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                pass

            @abc.abstractmethod
            def intercept_run(self, *, action: Any, state: Any, **future_kwargs: Any) -> dict:
                pass

        class ConcreteInterceptor(BaseInterceptor):
            def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                return True

            def intercept_run(self, *, action: Any, state: Any, **future_kwargs: Any) -> dict:
                return {}

        interceptor = ConcreteInterceptor()
        adapter_set = LifecycleAdapterSet(interceptor)

        # Should find interceptor through inheritance
        found = adapter_set.get_first_matching_hook(
            "test_inheritance_interceptor", lambda hook: hook.should_intercept(action=None)
        )

        assert found is interceptor

    def test_get_first_matching_interceptor_multiple_types(self):
        """Test that different interceptor types can coexist."""

        @lifecycle.interceptor_hook("type_a_interceptor")
        class TypeAInterceptor:
            def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                return True

            def intercept_run(self, *, action: Any, state: Any, **future_kwargs: Any) -> dict:
                return {"type": "A"}

        @lifecycle.interceptor_hook("type_b_interceptor")
        class TypeBInterceptor:
            def should_intercept(self, *, action: Any, **future_kwargs: Any) -> bool:
                return True

            def intercept_run(self, *, action: Any, state: Any, **future_kwargs: Any) -> dict:
                return {"type": "B"}

        interceptor_a = TypeAInterceptor()
        interceptor_b = TypeBInterceptor()
        adapter_set = LifecycleAdapterSet(interceptor_a, interceptor_b)

        # Should find correct interceptor by type
        found_a = adapter_set.get_first_matching_hook(
            "type_a_interceptor", lambda hook: hook.should_intercept(action=None)
        )
        found_b = adapter_set.get_first_matching_hook(
            "type_b_interceptor", lambda hook: hook.should_intercept(action=None)
        )

        assert found_a is interceptor_a
        assert found_b is interceptor_b
        assert found_a.intercept_run(action=None, state=None) == {"type": "A"}
        assert found_b.intercept_run(action=None, state=None) == {"type": "B"}

    def test_get_first_matching_hook_falls_back_to_standard_hooks(self):
        """Test that get_first_matching_hook still works for standard hooks."""

        @lifecycle.base_hook("test_standard_hook")
        class StandardHook:
            def test_standard_hook(self, *, app_id: str, **future_kwargs: Any):
                pass

        hook = StandardHook()
        adapter_set = LifecycleAdapterSet(hook)

        # Should find standard hook
        found = adapter_set.get_first_matching_hook("test_standard_hook", lambda h: True)

        assert found is hook
