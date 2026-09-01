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

from burr.core import Condition
from burr.core.graph import GraphBuilder

from tests.core.test_graph import PassedInAction


def _action(inputs=None):
    return PassedInAction(
        reads=["count"],
        writes=["count"],
        fn=lambda state: {"count": state.get("count", 0) + 1},
        update_fn=lambda result, state: state.update(**result),
        inputs=inputs or [],
    )


def test_mermaid_includes_inputs_state_and_conditions():
    graph = (
        GraphBuilder()
        .with_actions(counter=_action(["prompt"]), result=_action())
        .with_transitions(
            ("counter", "result", Condition.expr("count < 10")),
            ("result", "counter"),
        )
        .build()
    )

    diagram = graph.visualize(
        engine="mermaid",
        include_conditions=True,
        include_state=True,
    )

    assert 'action_0["counter(count): count"]' in diagram
    assert 'input_0["input: prompt"]' in diagram
    assert "input_0 -.-> action_0" in diagram
    assert 'action_0 -. "count &lt; 10" .-> action_1' in diagram
    assert "action_1 --> action_0" in diagram


def test_mermaid_ignores_framework_injected_inputs():
    graph = GraphBuilder().with_actions(counter=_action(["__context", "prompt"])).build()

    diagram = graph.visualize(engine="mermaid")

    assert "__context" not in diagram
    assert "input: prompt" in diagram
