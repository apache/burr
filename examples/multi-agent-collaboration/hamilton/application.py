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
Hamilton version of the multi-agent collaboration example.

This also adds a tracer to the Hamilton DAG to trace the execution of the nodes
within the Action so that they also show up in the Burr UI.
"""

import json
from typing import Any, Dict, Optional

import func_agent
from hamilton import driver
from hamilton import lifecycle as h_lifecycle
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_experimental.utilities import PythonREPL

from burr import core
from burr.core import Action, ApplicationBuilder, State, action, default
from burr.lifecycle import PostRunStepHook
from burr.tracking import client as burr_tclient
from burr.visibility import ActionSpanTracer, TracerFactory

# --- some set up for the tools ---

repl = PythonREPL()
tavily_tool = TavilySearchResults(max_results=5)


def python_repl(code: str) -> dict:
    """Use this to execute python code. If you want to see the output of a value,
    you should print it out with `print(...)`. This is visible to the user.

    :param code: string. The python code to execute.
    :return: the output
    """
    try:
        result = repl.run(code)
    except BaseException as e:
        return {"error": repr(e), "status": "error", "code": f"```python\n{code}\n```"}
    return {"status": "success", "code": f"```python\n{code}\n```", "Stdout": result}


# These are our tools that we will use in the application.
tools = [tavily_tool, python_repl]


class SimpleTracer(h_lifecycle.NodeExecutionHook):
    """Simple Hamilton Tracer that plugs into Burr's tracing capture.
    This will tell Burr about what Hamilton is doing internally.
    """

    def __init__(self, tracer: TracerFactory):
        self._tracer: TracerFactory = tracer
        self.active_spans = {}

    def run_before_node_execution(
        self,
        *,
        node_name: str,
        node_tags: Dict[str, Any],
        node_kwargs: Dict[str, Any],
        node_return_type: type,
        task_id: Optional[str],
        run_id: str,
        node_input_types: Dict[str, Any],
        **future_kwargs: Any,
    ):
        context_manager: ActionSpanTracer = self._tracer(node_name)
        context_manager.__enter__()
        self.active_spans[node_name] = context_manager

    def run_after_node_execution(
        self,
        *,
        node_name: str,
        node_tags: Dict[str, Any],
        node_kwargs: Dict[str, Any],
        node_return_type: type,
        result: Any,
        error: Optional[Exception],
        success: bool,
        task_id: Optional[str],
        run_id: str,
        **future_kwargs: Any,
    ):
        context_manager = self.active_spans.pop(node_name)
        context_manager.__exit__(None, None, None)


def initialize_agent_dag(agent_name: str, tracer: TracerFactory) -> driver.Driver:
    """Initialize the agent DAG with the tracer.

    Right now there is no difference between the agents, but this is here for future use.
    """
    tracer = SimpleTracer(tracer)
    # Initialize some things needed for tools.
    agent_dag = driver.Builder().with_modules(func_agent).with_adapters(tracer).build()
    return agent_dag


# --- End Tool Setup

# --- Start defining Action


@action(reads=["query", "messages"], writes=["messages"])
def chart_generator(state: State, __tracer: TracerFactory) -> tuple[dict, State]:
    """The chart generator action.

    :param state: state of the application
    :param __tracer: burr tracer that gets injected.
    :return:
    """
    query = state["query"]
    agent_dag = initialize_agent_dag("chart_generator", __tracer)
    result = agent_dag.execute(
        ["parsed_tool_calls", "llm_function_message"],
        inputs={
            "tools": [python_repl],
            "system_message": "Any charts you display will be visible by the user. When done say 'FINAL ANSWER'.",
            "user_query": query,
            "messages": state["messages"],
        },
    )
    # _code = result["parsed_tool_calls"][0]["function_args"]["code"]
    new_message = result["llm_function_message"]
    parsed_tool_calls = result["parsed_tool_calls"]
    state = state.update(parsed_tool_calls=parsed_tool_calls)
    state = state.append(messages=new_message)
    state = state.update(sender="chart_generator")
    return result, state


@action(reads=["query", "messages"], writes=["messages"])
def researcher(state: State, __tracer: TracerFactory) -> tuple[dict, State]:
    """The researcher action.

    :param state: state of the application
    :param __tracer: the burr tracer that gets injected.
    :return:
    """
    query = state["query"]
    agent_dag = initialize_agent_dag("researcher", __tracer)
    result = agent_dag.execute(
        ["parsed_tool_calls", "llm_function_message"],
        inputs={
            "tools": [tavily_tool],
            "system_message": "You should provide accurate data for the chart generator to use. When done say 'FINAL ANSWER'.",
            "user_query": query,
            "messages": state["messages"],
        },
    )
    new_message = result["llm_function_message"]
    parsed_tool_calls = result["parsed_tool_calls"]
    state = state.update(parsed_tool_calls=parsed_tool_calls)
    state = state.append(messages=new_message)
    state = state.update(sender="researcher")
    return result, state


@action(reads=["messages", "parsed_tool_calls"], writes=["messages", "parsed_tool_calls"])
def tool_node(state: State) -> tuple[dict, State]:
    """Given a tool call, execute it and return the result."""
    new_messages = []
    parsed_tool_calls = state["parsed_tool_calls"]

    for tool_call in parsed_tool_calls:
        tool_name = tool_call["function_name"]
        tool_args = tool_call["function_args"]
        tool_found = False
        for tool in tools:
            name = getattr(tool, "name", None)
            if name is None:
                name = tool.__name__
            if name == tool_name:
                tool_found = True
                kwargs = json.loads(tool_args)
                # Execute the tool!
                if hasattr(tool, "_run"):
                    result = tool._run(**kwargs)
                else:
                    result = tool(**kwargs)
                new_messages.append(
                    {
                        "tool_call_id": tool_call["id"],
                        "role": "tool",
                        "name": tool_name,
                        "content": result,
                    }
                )
        if not tool_found:
            raise ValueError(f"Tool {tool_name} not found.")

    for tool_result in new_messages:
        state = state.append(messages=tool_result)
    state = state.update(parsed_tool_calls=[])
    # We return a list, because this will get added to the existing list
    return {"messages": new_messages}, state


@action(reads=[], writes=[])
def terminal_step(state: State) -> tuple[dict, State]:
    """Terminal step we have here that does nothing, but it could"""
    return {}, state


class PrintStepHook(PostRunStepHook):
    """Prints the action and state after each step."""

    def post_run_step(self, *, state: "State", action: "Action", **future_kwargs):
        print("action=====\n", action)
        print("state======\n", state)


def default_state_and_entry_point(query: str = None) -> tuple[dict, str]:
    """Returns the default state and entry point for the application."""
    if query is None:
        query = (
            "Fetch the UK's GDP over the past 5 years,"
            " then draw a line graph of it."
            " Once the python code has been written and the graph drawn, the task is complete."
        )
    return {
        "messages": [],
        "query": query,
        "sender": "",
        "parsed_tool_calls": [],
    }, "researcher"


def main(query: str = None, app_instance_id: str = None, sequence_number: int = None):
    """Main function to run the application.

    :param query: the query for the agents to run over.
    :param app_instance_id: a prior app instance id to restart from.
    :param sequence_number: a prior sequence number to restart from.
    :return:
    """
    project_name = "demo_hamilton-multi-agent-v1"
    if app_instance_id:
        tracker = burr_tclient.LocalTrackingClient(project_name)
        persisted_state = tracker.load("demo", app_id=app_instance_id, sequence_no=sequence_number)
        if not persisted_state:
            print(f"Warning: No persisted state found for app_id {app_instance_id}.")
            state, entry_point = default_state_and_entry_point(query)
        else:
            state = persisted_state["state"]
            entry_point = persisted_state["position"]
    else:
        state, entry_point = default_state_and_entry_point(query)
    # look up app_id for particular user
    # if None -- then proceed with defaults
    # else load from state, and set entry point
    app = (
        ApplicationBuilder()
        .with_state(**state)
        .with_actions(
            researcher=researcher,
            chart_generator=chart_generator,
            tool_node=tool_node,
            terminal=terminal_step,
        )
        .with_transitions(
            ("researcher", "tool_node", core.expr("len(parsed_tool_calls) > 0")),
            (
                "researcher",
                "terminal",
                core.expr("'FINAL ANSWER' in messages[-1]['content']"),
            ),
            ("researcher", "chart_generator", default),
            ("chart_generator", "tool_node", core.expr("len(parsed_tool_calls) > 0")),
            (
                "chart_generator",
                "terminal",
                core.expr("'FINAL ANSWER' in messages[-1]['content']"),
            ),
            ("chart_generator", "researcher", default),
            ("tool_node", "researcher", core.expr("sender == 'researcher'")),
            ("tool_node", "chart_generator", core.expr("sender == 'chart_generator'")),
        )
        .with_identifiers(partition_key="demo")
        .with_entrypoint(entry_point)
        .with_hooks(PrintStepHook())
        .with_tracker(project=project_name)
        .build()
    )
    app.visualize(
        output_file_path="hamilton-multi-agent-v2", include_conditions=True, view=True, format="png"
    )
    app.run(halt_after=["terminal"])


if __name__ == "__main__":
    # Add an app_id to restart from last sequence in that state
    # e.g. fine the ID in the UI and then put it in here "app_f0e4a918-b49c-4ee1-9d2b-30c15104c51c"
    _app_id = None  # "app_4ed5b3b3-0f38-4b37-aed7-559d506174c7"
    _app_id = "8458dc58-7b6c-430b-9ab3-23450774f883"
    # _sequence_no = None  # 23
    _sequence_no = 5
    # main(None, None)
    main(_app_id, _sequence_no)

    # some test code
    # tavily_tool = TavilySearchResults(max_results=5)
    # result = tool_dag.execute(
    #     ["executed_tool_calls"],
    #     inputs={
    #         "tools": [tavily_tool],
    #         "system_message": "You should provide accurate data for the chart generator to use.",
    #         "user_query": "Fetch the UK's GDP over the past 5 years,"
    #         " then draw a line graph of it."
    #         " Once you have written code for the graph, finish.",
    #     },
    # )
    # import pprint
    #
    # pprint.pprint(result)
    #
    # result = tool_dag.execute(
    #     ["executed_tool_calls"],
    #     inputs={
    #         "tools": [python_repl],
    #         "system_message": "Any charts you display will be visible by the user.",
    #         "user_query": "Draw a simple line graph of y = x",
    #     },
    # )
    # import pprint
    #
    # pprint.pprint(result)
