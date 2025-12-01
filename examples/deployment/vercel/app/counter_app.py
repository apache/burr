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
    