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
This shows how to do a nested example of a hierarchical agent that uses
teams. What that means is that we will use Burr within Burr!

We're still deciding on a nicer way to do this, but for now, this is one
way to do it.

Note: you could unroll this into a single application.
"""

import uuid

import agent_supervisor

from burr import core
from burr.core import ApplicationBuilder, State, action, default
from burr.tracking import client as burr_tclient

# --- Define some tools

tools = []  # these could be functions, etc.

# --- Start defining Action


@action(reads=["query", "messages"], writes=["next_step"])
def supervisor_agent(state: State) -> tuple[dict, State]:
    """This agent decides what to do next given the current context.

    i.e. call which team, or terminate.

    :param state: state of the application
    :return:
    """
    _query = state["query"]  # noqa:F841
    _message = state["messages"]  # noqa:F841
    _agents = ["team_1", "team_2"]  # noqa:F841
    # Do LLM call, passing in current information and options
    # determine what to do next
    _result = {"next_step": "team_or_terminate"}
    return _result, state.update(**_result)


@action(reads=["query", "messages"], writes=["result"])
def team_1(state: State) -> tuple[dict, State]:
    """A team specializing in some task.

    :param state: state of the application
    :return:
    """
    _query = state["query"]  # noqa:F841
    _message = state["messages"]  # noqa:F841
    _id = str(uuid.uuid4())
    _app = agent_supervisor.main("some user query", _id)
    _last_action, _result, _state = _app.run(halt_after=["terminal"])  # noqa:F841
    # pull results and updates accordingly
    _result = {"result": _result}
    return _result, state.update(**_result)


@action(reads=["query", "messages"], writes=["result"])
def team_2(state: State) -> tuple[dict, State]:
    """A team specializing in some other task.

    :param state: state of the application
    :return:
    """
    _query = state["query"]  # noqa:F841
    _message = state["messages"]  # noqa:F841
    _id = str(uuid.uuid4())
    _app = agent_supervisor.main("some user query", _id)
    _last_action, _result, _state = _app.run(halt_after=["terminal"])  # noqa:F841
    # pull results and updates accordingly
    _result = {"result": _result}
    return _result, state.update(**_result)


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
    }, "supervisor_agent"


def main(query: str = None, app_instance_id: str = None, sequence_number: int = None):
    """Main function to run the application.

    :param query: the query for the agents to run over.
    :param app_instance_id: a prior app instance id to restart from.
    :param sequence_number: a prior sequence number to restart from.
    :return:
    """
    project_name = "template:hierarchical-agent-teams"
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
            supervisor_agent=supervisor_agent,
            team_1=team_1,
            team_2=team_2,
            terminal=terminal_step,
        )
        .with_transitions(
            ("supervisor_agent", "team_1", core.when(next_step="team_1")),
            ("supervisor_agent", "team_2", core.when(next_step="team_2")),
            ("supervisor_agent", "terminal", core.when(next_step="terminate")),
            ("team_1", "supervisor_agent", default),
            ("team_2", "supervisor_agent", default),
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
        output_file_path="hierarchical_agent_teams",
        include_conditions=True,
        view=True,
        format="png",
    )
    # app.run(halt_after=["terminal"])
