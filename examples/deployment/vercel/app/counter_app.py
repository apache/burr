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

"""
This is a very simple counting application.

It's here to help you get the mechanics of deploying a Burr application to AWS Lambda.
"""

import time

import burr.core
from burr.core import Application, Result, State, default, expr
from burr.core.action import action
from burr.core.graph import GraphBuilder


@action(reads=["counter"], writes=["counter"])
def counter(state: State) -> State:
    result = {"counter": state["counter"] + 1}
    time.sleep(0.5)  # sleep to simulate a longer running function
    return state.update(**result)


# our graph.
graph = (
    GraphBuilder()
    .with_actions(counter=counter, result=Result("counter"))
    .with_transitions(
        ("counter", "counter", expr("counter < counter_limit")),
        ("counter", "result", default),
    )
    .build()
)


def application(count_up_to: int = 10) -> Application:
    """function to return a burr application"""
    return (
        burr.core.ApplicationBuilder()
        .with_graph(graph)
        .with_state(**{"counter": 0, "counter_limit": count_up_to})
        .with_entrypoint("counter")
        .build()
    )

