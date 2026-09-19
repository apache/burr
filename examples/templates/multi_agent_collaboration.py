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
Template for multi-agent collaboration.

This contains a simple example of how to set up a multi-agent collaboration.
The functions are to be filled in with the actual code to run the agents.
"""

from burr import core
from burr.core import ApplicationBuilder, State, action, default
from burr.tracking import client as burr_tclient

# --- Define some tools

tools = []  # these could be functions, etc.

# --- Start defining Action


@action(reads=["query", "messages"], writes=["parsed_tool_calls"])
def some_agent_1(state: State) -> tuple[dict, State]:
    """An agent specializing in some task.

    :param state: state of the application
    :return:
    """
    _query = state["query"]  # noqa:F841
    _message = state["messages"]  # noqa:F841
    # Do LLM call, passing in tool information
    # determine which tool to call
    _result = {"tool_call": "some_tool", "tool_args": {"arg1": "value1"}}
    return _result, state.update(parsed_tool_calls=[_result], sender="some_agent_1")


@action(reads=["query", "messages"], writes=["parsed_tool_calls"])
def some_agent_2(state: State) -> tuple[dict, State]:
    """An agent specializing in some other task.

    :param state: state of the application
    :return:
    """
    _query = state["query"]  # noqa:F841
    _message = state["messages"]  # noqa:F841
    # Do LLM call, passing in tool information
    # determine which tool to call
    _result = {"tool_call": "some_tool2", "tool_args": {"arg1": "value1"}}
    return _result, state.update(parsed_tool_calls=[_result], sender="some_agent_2")


@action(reads=["messages", "parsed_tool_calls"], writes=["messages", "parsed_tool_calls"])
def tool_node(state: State) -> tuple[dict, State]:
    """Given a tool call, execute it and return the result."""
    _messages = state["messages"]  # noqa:F841
    _parsed_tool_calls = state["parsed_tool_calls"]  # noqa:F841
    # execute the tool call
    # get result and create new message
    _tool_results = [{"some": "message", "from": "tool_node"}]
    new_state = state.append(messages=_tool_results)
    new_state = new_state.update(parsed_tool_calls=[])
    # We return a list, because this will get added to the existing list
    return {"tool_results": _tool_results}, new_state


@action(reads=["messages"], writes=[])
def terminal_step(state: State) -> tuple[dict, State]:
    """Terminal step we have here that does nothing, but it could"""
    return {}, state


def default_state_and_entry_point(query: str = None) -> tuple[dict, str]:
    """Returns the default state and entry point for the application."""
    return {
        "messages": [],
        "query": query,
        "sender": "",
        "parsed_tool_calls": [],
    }, "some_agent_1"


def main(query: str = None, app_instance_id: str = None, sequence_number: int = None):
    """Main function to run the application.

    :param query: the query for the agents to run over.
    :param app_instance_id: a prior app instance id to restart from.
    :param sequence_number: a prior sequence number to restart from.
    :return:
    """
    project_name = "template:multi-agent-collaboration"
    if app_instance_id:
        tracker = burr_tclient.LocalTrackingClient(project_name)
        persisted_state = tracker.load("", app_id=app_instance_id, sequence_no=sequence_number)
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
            some_agent_1=some_agent_1,
            some_agent_2=some_agent_2,
            tool_node=tool_node,
            terminal=terminal_step,
        )
        .with_transitions(
            ("some_agent_1", "tool_node", core.expr("len(parsed_tool_calls) > 0")),
            (
                "some_agent_1",
                "terminal",
                core.expr("'SOMETHING_IN_MESSAGES' in messages[-1]['content']"),
            ),
            ("some_agent_1", "some_agent_2", default),
            ("some_agent_2", "tool_node", core.expr("len(parsed_tool_calls) > 0")),
            (
                "some_agent_2",
                "terminal",
                core.expr("'SOMETHING_IN_MESSAGES' in messages[-1]['content']"),
            ),
            ("some_agent_2", "some_agent_1", default),
            ("tool_node", "some_agent_1", core.expr("sender == 'some_agent_1'")),
            ("tool_node", "some_agent_2", core.expr("sender == 'some_agent_2'")),
        )
        .with_identifiers(partition_key="demo")
        .with_entrypoint(entry_point)
        .with_tracker(project=project_name)
        .build()
    )
    return app


if __name__ == "__main__":
    # Add an app_id to restart from last sequence in that state
    _app_id = "8458dc58-7b6c-430b-9ab3-23450774f883"
    app = main("some user query", _app_id)
    app.visualize(
        output_file_path="multi_agent_collaboration",
        include_conditions=True,
        view=True,
        format="png",
    )
    # app.run(halt_after=["terminal"])
