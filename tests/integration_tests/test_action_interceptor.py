# Tests for action execution interceptor hooks
from typing import Any, Dict, Generator, Optional, Tuple

import pytest

from burr.core import Action, ApplicationBuilder, State, action
from burr.core.action import streaming_action
from burr.lifecycle import (
    ActionExecutionInterceptorHook,
    ActionExecutionInterceptorHookAsync,
    PostRunStepHookWorker,
    PreRunStepHookWorker,
    StreamingActionInterceptorHook,
)


# Test actions
@action(reads=["x"], writes=["y"])
def add_one(state: State) -> Tuple[dict, State]:
    result = {"y": state["x"] + 1}
    return result, state.update(**result)


@action(reads=["x"], writes=["z"], tags=["intercepted"])
def multiply_by_two(state: State) -> Tuple[dict, State]:
    result = {"z": state["x"] * 2}
    return result, state.update(**result)


@streaming_action(reads=["prompt"], writes=["response"], tags=["streaming_intercepted"])
def streaming_responder(state: State) -> Generator[Tuple[dict, Optional[State]], None, None]:
    """Simple streaming action for testing"""
    tokens = ["Hello", " ", "World", "!"]
    buffer = []
    for token in tokens:
        buffer.append(token)
        yield {"response": token}, None
    full_response = "".join(buffer)
    yield {"response": full_response}, state.update(response=full_response)


@action(reads=["x"], writes=["w"], tags=["intercepted"])
async def async_multiply(state: State) -> Tuple[dict, State]:
    """Async action for testing"""
    import asyncio

    await asyncio.sleep(0.01)  # Simulate async work
    result = {"w": state["x"] * 3}
    return result, state.update(**result)


# Mock interceptor that captures execution
class MockActionInterceptor(ActionExecutionInterceptorHook):
    """Test interceptor that tracks which actions were intercepted"""

    def __init__(self):
        self.intercepted_actions = []
        self.worker_hooks_called = []

    def should_intercept(self, *, action: Action, **kwargs) -> bool:
        # Intercept actions with the "intercepted" tag
        return "intercepted" in action.tags

    def intercept_run(
        self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
    ) -> dict:
        self.intercepted_actions.append(action.name)

        # Extract worker_adapter_set if provided
        worker_adapter_set = kwargs.get("worker_adapter_set")

        # Call worker pre-hooks if they exist
        if worker_adapter_set:
            worker_adapter_set.call_all_lifecycle_hooks_sync(
                "pre_run_step_worker",
                action=action,
                state=state,
                inputs=inputs,
            )

        # Simulate "remote" execution - check if it's a single-step action
        # For single-step actions, we need to call run_and_update and handle both result and state
        if hasattr(action, "single_step") and action.single_step:
            # Store the new state in a special key that _run_single_step_action will extract
            result, new_state = action.run_and_update(state, **inputs)
            # Store state in result for extraction
            result_with_state = result.copy()
            result_with_state["__INTERCEPTOR_NEW_STATE__"] = new_state
            result = result_with_state
        else:
            # For multi-step actions, call run
            state_to_use = state.subset(*action.reads)
            action.validate_inputs(inputs)
            result = action.run(state_to_use, **inputs)

        # Call worker post-hooks if they exist
        if worker_adapter_set:
            worker_adapter_set.call_all_lifecycle_hooks_sync(
                "post_run_step_worker",
                action=action,
                state=state,
                result=result,
                exception=None,
            )

        return result


class MockStreamingInterceptor(StreamingActionInterceptorHook):
    """Test interceptor for streaming actions"""

    def __init__(self):
        self.intercepted_actions = []

    def should_intercept(self, *, action: Action, **kwargs) -> bool:
        return "streaming_intercepted" in action.tags

    def intercept_stream_run_and_update(
        self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
    ):
        self.intercepted_actions.append(action.name)

        # Extract worker_adapter_set if provided
        worker_adapter_set = kwargs.get("worker_adapter_set")

        # Call worker pre-stream-hooks if they exist
        if worker_adapter_set:
            worker_adapter_set.call_all_lifecycle_hooks_sync(
                "pre_start_stream_worker",
                action=action.name,
                state=state,
                inputs=inputs,
            )

        # Run the streaming action normally (simulating remote execution)
        generator = action.stream_run_and_update(state, **inputs)
        result = None
        for item in generator:
            result = item
            yield item

        # Call worker post-stream-hooks if they exist
        if worker_adapter_set and result:
            worker_adapter_set.call_all_lifecycle_hooks_sync(
                "post_end_stream_worker",
                action=action.name,
                result=result[0] if result else None,
                exception=None,
            )


class WorkerPreHook(PreRunStepHookWorker):
    """Test worker hook that runs before action execution"""

    def __init__(self):
        self.called_actions = []

    def pre_run_step_worker(
        self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
    ):
        self.called_actions.append(("pre", action.name))


class WorkerPostHook(PostRunStepHookWorker):
    """Test worker hook that runs after action execution"""

    def __init__(self):
        self.called_actions = []

    def post_run_step_worker(
        self,
        *,
        action: Action,
        state: State,
        result: Optional[Dict[str, Any]],
        exception: Exception,
        **kwargs,
    ):
        self.called_actions.append(("post", action.name))


def test_interceptor_intercepts_tagged_action():
    """Test that interceptor only intercepts actions with specific tags"""
    interceptor = MockActionInterceptor()

    app = (
        ApplicationBuilder()
        .with_state(x=5)
        .with_actions(add_one, multiply_by_two)
        .with_transitions(
            ("add_one", "multiply_by_two"),
            ("multiply_by_two", "add_one"),
        )
        .with_entrypoint("add_one")
        .with_hooks(interceptor)
        .build()
    )

    # Run add_one (not intercepted)
    action, result, state = app.step()
    assert action.name == "add_one"
    assert state["y"] == 6
    assert "add_one" not in interceptor.intercepted_actions

    # Run multiply_by_two (intercepted)
    action, result, state = app.step()
    assert action.name == "multiply_by_two"
    assert state["z"] == 10  # 5 * 2, using original x value
    assert "multiply_by_two" in interceptor.intercepted_actions


def test_interceptor_calls_worker_hooks():
    """Test that interceptor properly calls worker hooks"""
    interceptor = MockActionInterceptor()
    worker_pre = WorkerPreHook()
    worker_post = WorkerPostHook()

    app = (
        ApplicationBuilder()
        .with_state(x=10)
        .with_actions(multiply_by_two)
        .with_entrypoint("multiply_by_two")
        .with_hooks(interceptor, worker_pre, worker_post)
        .build()
    )

    action, result, state = app.step()
    assert action.name == "multiply_by_two"
    assert state["z"] == 20

    # Verify interceptor ran
    assert "multiply_by_two" in interceptor.intercepted_actions

    # Verify worker hooks were called
    assert ("pre", "multiply_by_two") in worker_pre.called_actions
    assert ("post", "multiply_by_two") in worker_post.called_actions


def test_no_interceptor_normal_execution():
    """Test that actions run normally without interceptors"""
    app = (
        ApplicationBuilder()
        .with_state(x=3)
        .with_actions(add_one, multiply_by_two)
        .with_transitions(
            ("add_one", "multiply_by_two"),
        )
        .with_entrypoint("add_one")
        .build()
    )

    # Both should run normally
    action, result, state = app.step()
    assert action.name == "add_one"
    assert state["y"] == 4

    action, result, state = app.step()
    assert action.name == "multiply_by_two"
    assert state["z"] == 6  # 3 * 2


def test_streaming_action_interceptor():
    """Test interceptor for streaming actions"""
    streaming_interceptor = MockStreamingInterceptor()

    app = (
        ApplicationBuilder()
        .with_state(prompt="test")
        .with_actions(streaming_responder)
        .with_entrypoint("streaming_responder")
        .with_hooks(streaming_interceptor)
        .build()
    )

    # Run streaming action
    action, streaming_container = app.stream_result(
        halt_after=["streaming_responder"],
    )

    # Consume the stream
    tokens = []
    for item in streaming_container:
        tokens.append(item["response"])

    result, final_state = streaming_container.get()

    # Verify interceptor ran
    assert "streaming_responder" in streaming_interceptor.intercepted_actions

    # Verify streaming worked correctly
    assert tokens == ["Hello", " ", "World", "!"]
    assert final_state["response"] == "Hello World!"


def test_multiple_interceptors_first_wins():
    """Test that when multiple interceptors match, the first one wins"""

    class FirstInterceptor(ActionExecutionInterceptorHook):
        def __init__(self):
            self.called = False

        def should_intercept(self, *, action: Action, **kwargs) -> bool:
            return "intercepted" in action.tags

        def intercept_run(
            self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
        ) -> dict:
            self.called = True
            # Return a custom result with state for single-step actions
            result = {"z": 999}
            if hasattr(action, "single_step") and action.single_step:
                result["__INTERCEPTOR_NEW_STATE__"] = state.update(z=999)
            return result

    class SecondInterceptor(ActionExecutionInterceptorHook):
        def __init__(self):
            self.called = False

        def should_intercept(self, *, action: Action, **kwargs) -> bool:
            return "intercepted" in action.tags

        def intercept_run(
            self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
        ) -> dict:
            self.called = True
            result = {"z": 777}
            if hasattr(action, "single_step") and action.single_step:
                result["__INTERCEPTOR_NEW_STATE__"] = state.update(z=777)
            return result

    first = FirstInterceptor()
    second = SecondInterceptor()

    app = (
        ApplicationBuilder()
        .with_state(x=5)
        .with_actions(multiply_by_two)
        .with_entrypoint("multiply_by_two")
        .with_hooks(first, second)  # first is registered first
        .build()
    )

    action, result, state = app.step()

    # First interceptor should have been called
    assert first.called
    assert state["z"] == 999

    # Second interceptor should NOT have been called
    assert not second.called


@pytest.mark.asyncio
async def test_async_interceptor_with_sync_action():
    """Test that async interceptors work with sync actions"""
    import asyncio

    class AsyncMockInterceptor(ActionExecutionInterceptorHookAsync):
        """Async interceptor that simulates async execution (e.g., Ray with asyncio)"""

        def __init__(self):
            self.intercepted_actions = []
            self.async_calls_made = 0

        def should_intercept(self, *, action: Action, **kwargs) -> bool:
            return "intercepted" in action.tags

        async def intercept_run(
            self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
        ) -> dict:
            self.intercepted_actions.append(action.name)

            # Simulate async operation (e.g., waiting for Ray actor)
            await asyncio.sleep(0.01)
            self.async_calls_made += 1

            # Execute action (sync action, but in async context)
            if hasattr(action, "single_step") and action.single_step:
                result, new_state = action.run_and_update(state, **inputs)
                result_with_state = result.copy()
                result_with_state["__INTERCEPTOR_NEW_STATE__"] = new_state
                result = result_with_state
            else:
                state_to_use = state.subset(*action.reads)
                result = action.run(state_to_use, **inputs)

            return result

    interceptor = AsyncMockInterceptor()

    app = (
        ApplicationBuilder()
        .with_state(x=5)
        .with_actions(add_one, multiply_by_two)
        .with_transitions(
            ("add_one", "multiply_by_two"),
            ("multiply_by_two", "add_one"),
        )
        .with_entrypoint("add_one")
        .with_hooks(interceptor)
        .build()
    )

    # Run add_one (not intercepted) - should work with astep
    action, result, state = await app.astep()
    assert action.name == "add_one"
    assert state["y"] == 6
    assert "add_one" not in interceptor.intercepted_actions
    assert interceptor.async_calls_made == 0

    # Run multiply_by_two (intercepted) - async interceptor should be called
    action, result, state = await app.astep()
    assert action.name == "multiply_by_two"
    assert state["z"] == 10  # 5 * 2
    assert "multiply_by_two" in interceptor.intercepted_actions
    assert interceptor.async_calls_made == 1


def test_interceptor_with_field_level_serde():
    """Test that interceptors properly handle non-serializable objects via field-level serde"""

    # Create a mock non-serializable object (simulating DB client)
    class DummyDBClient:
        def __init__(self, connection_string: str):
            self.connection_string = connection_string

        def query(self, sql: str):
            return f"Result from {self.connection_string}: {sql}"

    # Register field-level serde for db_client
    from burr.core.state import register_field_serde

    def serialize_db_client(value: Any, **kwargs) -> dict:
        """Serialize DB client to connection string"""
        return {
            "connection_string": value.connection_string,
            "type": "db_client",
        }

    def deserialize_db_client(value: dict, **kwargs) -> Any:
        """Recreate DB client from connection string"""
        return DummyDBClient(value["connection_string"])

    register_field_serde("db_client", serialize_db_client, deserialize_db_client)

    # Create interceptor that uses serialize/deserialize
    class SerdeAwareInterceptor(ActionExecutionInterceptorHook):
        def __init__(self):
            self.intercepted_actions = []
            self.serialized_states = []
            self.deserialized_states = []

        def should_intercept(self, *, action: Action, **kwargs) -> bool:
            return "intercepted" in action.tags

        def intercept_run(
            self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
        ) -> dict:
            self.intercepted_actions.append(action.name)

            # Serialize state (this will use field-level serde for db_client)
            state_subset = state.subset(*action.reads) if action.reads else state
            state_dict = state_subset.serialize()
            self.serialized_states.append(state_dict)

            # Deserialize on "worker" side
            worker_state = State.deserialize(state_dict)
            self.deserialized_states.append(worker_state)

            # Execute action
            if hasattr(action, "single_step") and action.single_step:
                result, new_state = action.run_and_update(worker_state, **inputs)
                # Serialize new_state before returning
                new_state_dict = new_state.serialize()
                # Deserialize when reconstructing
                reconstructed_state = State.deserialize(new_state_dict)
                result_with_state = result.copy()
                result_with_state["__INTERCEPTOR_NEW_STATE__"] = reconstructed_state
                return result_with_state
            else:
                state_to_use = worker_state.subset(*action.reads)
                result = action.run(state_to_use, **inputs)
                return result

    # Create action that uses db_client
    @action(reads=["x", "db_client"], writes=["y"], tags=["intercepted"])
    def query_db(state: State) -> Tuple[dict, State]:
        """Action that uses db_client from state"""
        db_client = state["db_client"]
        query_result = db_client.query(f"SELECT * FROM table WHERE x={state['x']}")
        result = {"y": query_result}
        return result, state.update(**result)

    interceptor = SerdeAwareInterceptor()
    db_client = DummyDBClient("postgresql://localhost/db")

    app = (
        ApplicationBuilder()
        .with_state(x=5, db_client=db_client)
        .with_actions(query_db)
        .with_entrypoint("query_db")
        .with_hooks(interceptor)
        .build()
    )

    # Run action
    executed_action, result, state = app.step()

    # Verify interceptor ran
    assert "query_db" in interceptor.intercepted_actions

    # Verify state was serialized (db_client should be converted to dict)
    serialized_state = interceptor.serialized_states[0]
    assert "db_client" in serialized_state
    assert isinstance(serialized_state["db_client"], dict)
    assert serialized_state["db_client"]["type"] == "db_client"
    assert serialized_state["db_client"]["connection_string"] == "postgresql://localhost/db"

    # Verify state was deserialized (db_client should be recreated)
    deserialized_state = interceptor.deserialized_states[0]
    assert "db_client" in deserialized_state
    assert isinstance(deserialized_state["db_client"], DummyDBClient)
    assert deserialized_state["db_client"].connection_string == "postgresql://localhost/db"

    # Verify final state has working db_client
    assert "db_client" in state
    assert isinstance(state["db_client"], DummyDBClient)
    assert "Result from postgresql://localhost/db" in state["y"]


@pytest.mark.asyncio
async def test_async_interceptor_with_async_action():
    """Test that async interceptors work with async actions"""
    import asyncio

    class AsyncMockInterceptor(ActionExecutionInterceptorHookAsync):
        def __init__(self):
            self.intercepted_actions = []

        def should_intercept(self, *, action: Action, **kwargs) -> bool:
            return "intercepted" in action.tags

        async def intercept_run(
            self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
        ) -> dict:
            self.intercepted_actions.append(action.name)

            # Simulate async execution
            await asyncio.sleep(0.01)

            # Execute async action
            if hasattr(action, "single_step") and action.single_step:
                result, new_state = await action.run_and_update(state, **inputs)
                result_with_state = result.copy()
                result_with_state["__INTERCEPTOR_NEW_STATE__"] = new_state
                return result_with_state
            else:
                state_to_use = state.subset(*action.reads)
                result = await action.run(state_to_use, **inputs)
                return result

    interceptor = AsyncMockInterceptor()

    app = (
        ApplicationBuilder()
        .with_state(x=7)
        .with_actions(async_multiply)
        .with_entrypoint("async_multiply")
        .with_hooks(interceptor)
        .build()
    )

    # Run async action with async interceptor
    action, result, state = await app.astep()
    assert action.name == "async_multiply"
    assert state["w"] == 21  # 7 * 3
    assert "async_multiply" in interceptor.intercepted_actions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
