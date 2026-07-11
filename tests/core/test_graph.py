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

from typing import Callable

import pytest

from burr.core import Action, Condition, Result, State, default
from burr.core.graph import GraphBuilder, _validate_actions, _validate_transitions


# TODO -- share versions among tests, this is duplicated in test_application.py
class PassedInAction(Action):
    def __init__(
        self,
        reads: list[str],
        writes: list[str],
        fn: Callable[..., dict],
        update_fn: Callable[[dict, State], State],
        inputs: list[str],
        tags: list[str] = None,
    ):
        super(PassedInAction, self).__init__()
        self._reads = reads
        self._writes = writes
        self._fn = fn
        self._update_fn = update_fn
        self._inputs = inputs
        self._tags = tags

    def run(self, state: State, **run_kwargs) -> dict:
        return self._fn(state, **run_kwargs)

    @property
    def inputs(self) -> list[str]:
        return self._inputs

    def update(self, result: dict, state: State) -> State:
        return self._update_fn(result, state)

    @property
    def reads(self) -> list[str]:
        return self._reads

    @property
    def writes(self) -> list[str]:
        return self._writes

    @property
    def tags(self) -> list[str]:
        return self._tags or []


def test__validate_transitions_correct():
    _validate_transitions(
        [("counter", "counter", Condition.expr("count < 10")), ("counter", "result", default)],
        {"counter", "result"},
    )


def test__validate_transitions_missing_action():
    with pytest.raises(ValueError, match="not found"):
        _validate_transitions(
            [
                ("counter", "counter", Condition.expr("count < 10")),
                ("counter", "result", default),
            ],
            {"counter"},
        )


def test__validate_transitions_redundant_transition():
    with pytest.raises(ValueError, match="redundant"):
        _validate_transitions(
            [
                ("counter", "counter", Condition.expr("count < 10")),
                ("counter", "result", default),
                ("counter", "counter", default),  # this is unreachable as we already have a default
            ],
            {"counter", "result"},
        )


def test__validate_actions_valid():
    _validate_actions([Result("test")])


def test__validate_actions_empty():
    with pytest.raises(ValueError, match="at least one"):
        _validate_actions([])


def test__validate_actions_duplicated():
    with pytest.raises(ValueError, match="duplicated"):
        _validate_actions([Result("test"), Result("test")])


base_counter_action = PassedInAction(
    reads=["count"],
    writes=["count"],
    fn=lambda state: {"count": state.get("count", 0) + 1},
    update_fn=lambda result, state: state.update(**result),
    inputs=[],
    tags=["tag1", "tag2"],
)


def test_graph_builder_builds():
    graph = (
        GraphBuilder()
        .with_actions(counter=base_counter_action, result=Result("count"))
        .with_transitions(
            ("counter", "counter", Condition.expr("count < 10")), ("counter", "result")
        )
        .build()
    )
    assert len(graph.actions) == 2
    assert len(graph.transitions) == 2


def test_graph_builder_with_graph():
    graph1 = (
        GraphBuilder()
        .with_actions(counter=base_counter_action)
        .with_transitions(("counter", "counter", Condition.expr("count < 10")))
        .build()
    )
    graph2 = (
        GraphBuilder()
        .with_actions(counter2=base_counter_action)
        .with_transitions(("counter2", "counter2", Condition.expr("count < 20")))
        .build()
    )
    graph = (
        GraphBuilder()
        .with_graph(graph1)
        .with_graph(graph2)
        .with_actions(result=Result("count"))
        .with_transitions(
            ("counter", "counter2"),
            ("counter2", "result"),
        )
    )
    assert len(graph.actions) == 3
    assert len(graph.transitions) == 4


def test_graph_builder_get_next_node():
    graph = (
        GraphBuilder()
        .with_actions(counter=base_counter_action, result=Result("count"))
        .with_transitions(
            ("counter", "counter", Condition.expr("count < 10")), ("counter", "result")
        )
        .build()
    )
    assert len(graph.actions) == 2
    assert len(graph.transitions) == 2
    assert graph.get_next_node(None, State({"count": 0}), entrypoint="counter").name == "counter"


def test_get_actions_by_tag():
    action_with_tags = PassedInAction(
        reads=["count"],
        writes=["count"],
        fn=lambda state: {"count": state.get("count", 0) + 1},
        update_fn=lambda result, state: state.update(**result),
        inputs=[],
        tags=["tag1", "tag2"],
    )

    action_with_tags_2 = PassedInAction(
        reads=["count"],
        writes=["count"],
        fn=lambda state: {"count": state.get("count", 0) + 1},
        update_fn=lambda result, state: state.update(**result),
        inputs=[],
        tags=["tag1", "tag3"],
    )
    graph = (
        GraphBuilder()
        .with_actions(counter1=action_with_tags, counter2=action_with_tags_2)
        .with_transitions(("counter1", "counter2"))
        .with_transitions(("counter2", "counter1"))
        .build()
    )
    # tag1 is in both actions, tag2 is in one, tag3 is in one
    assert len(graph.get_actions_by_tag("tag1")) == 2
    assert len(graph.get_actions_by_tag("tag2")) == 1
    assert len(graph.get_actions_by_tag("tag3")) == 1
    with pytest.raises(ValueError, match="not found"):
        graph.get_actions_by_tag("tag4")


def _flaky_handler_graph():
    """Source 'flaky' has BOTH a default ('flaky'->'next') AND a wildcard guarded
    error route ('*'->'handler', error is not None). Plus 'next' and 'handler'
    actions so targets are real."""
    return (
        GraphBuilder()
        .with_actions(
            flaky=Result("count"),
            next=Result("count"),
            handler=Result("count"),
        )
        .with_transitions(
            ("flaky", "next"),  # default
            ("*", "handler", Condition.expr("error is not None")),
        )
        .build()
    )


def test_wildcard_guarded_route_beats_source_default_when_error_set():
    """THE crux test: with error set, a guarded wildcard wins over the source's own default."""
    graph = _flaky_handler_graph()
    state = State({"count": 0, "error": {"type": "ValueError"}})
    assert graph.get_next_node("flaky", state, entrypoint="flaky").name == "handler"


def test_wildcard_guarded_route_falls_through_to_source_default_when_error_unset():
    graph = _flaky_handler_graph()
    state = State({"count": 0, "error": None})
    assert graph.get_next_node("flaky", state, entrypoint="flaky").name == "next"


def test_specific_guarded_beats_wildcard_guarded():
    """A source-specific guarded transition wins over a wildcard guarded transition."""
    graph = (
        GraphBuilder()
        .with_actions(
            a=Result("count"),
            specific=Result("count"),
            wild=Result("count"),
        )
        .with_transitions(
            ("a", "specific", Condition.expr("error is not None")),
            ("*", "wild", Condition.expr("error is not None")),
        )
        .build()
    )
    state = State({"count": 0, "error": {"type": "ValueError"}})
    assert graph.get_next_node("a", state, entrypoint="a").name == "specific"


def test_default_last_regression_resolves_identically():
    """Existing guarded + default-last graph (no wildcards) resolves as before."""
    graph = (
        GraphBuilder()
        .with_actions(counter=base_counter_action, result=Result("count"))
        .with_transitions(
            ("counter", "counter", Condition.expr("count < 10")),
            ("counter", "result"),
        )
        .build()
    )
    assert (
        graph.get_next_node("counter", State({"count": 0}), entrypoint="counter").name == "counter"
    )
    assert (
        graph.get_next_node("counter", State({"count": 10}), entrypoint="counter").name == "result"
    )


def test__validate_transitions_accepts_wildcard():
    assert _validate_transitions(
        [("*", "handler", Condition.expr("error is not None"))],
        {"flaky", "handler"},
    )
