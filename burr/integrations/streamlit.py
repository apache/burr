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

import colorsys
import dataclasses
import inspect
import json
from typing import List, Optional

from burr.core import Application
from burr.core.action import FunctionBasedAction
from burr.integrations.base import require_plugin
from burr.integrations.hamilton import Hamilton, StateSource

try:
    import graphviz
    import matplotlib.colors as mc
    import streamlit as st
except ImportError as e:
    require_plugin(
        e,
        "streamlit",
    )


@dataclasses.dataclass
class Record:
    state: dict
    action: str
    result: dict


@dataclasses.dataclass
class AppState:
    display_index: Optional[int]  # index in the state/results dict
    history: list[Record]
    app: Application  # we have to have this for registering the state machine --
    num_prior_nodes: int = 5  # view last 5

    @property
    def current_action(self) -> Optional[str]:
        if self.display_index is None or len(self.history) == 0:
            return None
        return self.history[self.display_index].action

    @property
    def prior_actions(self) -> List[str]:
        if self.display_index is None or len(self.history) == 0:
            return []
        out = [
            record.action
            for record in self.history[
                max(self.display_index - self.num_prior_nodes, 0) : self.display_index
            ]
        ]
        return out

    @property
    def next_action(self) -> Optional[str]:
        if self.display_index < len(self.history) - 1:
            return self.history[self.display_index + 1].action
        if self.app.get_next_action() is None:
            return None
        return self.app.get_next_action().name  # return the future one

    @property
    def max_index(self) -> int:
        return len(self.history) - 1

    @classmethod
    def from_empty(cls, app: Application) -> "AppState":
        return AppState(display_index=0, history=[], app=app)


def load_state_from_log_file(jsonl_log_file: str, app: Application) -> AppState:
    """Initializes the state from a log file. This must have been logged using StateAndResultFullLogger.
    Note that, currently, you must pass in an Application object (although that will be optoinal in the future).

    :param jsonl_log_file: Log file to load
    :param app: Application object
    :return: AppState
    """
    out = []
    for i, line in enumerate(open(jsonl_log_file)):
        json_line = json.loads(line)
        record = Record(
            state=json_line["state"],
            action=json_line["action"],
            result=json_line["result"],
            # TODO -- add start time, end time
        )
        out.append(record)
    return AppState(display_index=len(out) - 1, history=out, app=app)


def update_state(new_state: AppState):
    st.session_state.burr_state = new_state


def get_state():
    if "burr_state" not in st.session_state:
        raise ValueError(
            "No state found in streamlit session state. To initialize the state, call "
            "initialize_state() as the first line from streamlit -- it will do nothing if the state is already initialized."
        )
    return st.session_state.get("burr_state")


def _modify_state_machine_digraph(
    digraph: graphviz.Digraph,
    current_node: str = None,
    prior_nodes: list = [],
    next_node: str = None,
):
    def lighten_color(color, amount=0.5):
        if amount > 1:
            amount = 1
        if amount < 0:
            amount = 0
        try:
            c = mc.cnames[color]
        except KeyError:
            c = color
        c = colorsys.rgb_to_hls(*mc.to_rgb(c))
        lightened_color = colorsys.hls_to_rgb(c[0], 1 - amount * (1 - c[1]), c[2])
        return mc.to_hex(lightened_color)

    seen = {current_node}
    digraph.node(current_node, fillcolor="darkgreen", style="rounded,filled", fontcolor="white")
    if next_node is not None:
        digraph.node(next_node, fillcolor="blue", style="rounded,filled", fontcolor="white")
        seen.add(next_node)
    base_color = "lightblue"
    for i, node in enumerate(prior_nodes):
        if node not in seen:
            seen.add(node)
            lighter_color = lighten_color(base_color, amount=1 - ((i + 1) * 0.1))
            digraph.node(node, fillcolor=lighter_color, style="rounded,filled", fontcolor="black")
        else:
            continue

    digraph.attr(bgcolor="transparent")


def render_state_machine(state: AppState):
    """Visualization of the current state machine. Highlights:
        1. Current node in blue (with white backgorund)
        2. Prior nodes in progressively lighter shades of blue

    Use this individually, or within the "render_explorer" view

    :param state:
    :return:
    """
    prior_nodes = state.prior_actions  # grab the prior nodes
    current_node = state.current_action
    next_node = state.next_action
    app = state.app
    visualized = app.visualize(None, include_conditions=False, include_state=False)
    if current_node is not None:
        _modify_state_machine_digraph(
            visualized, current_node=current_node, prior_nodes=prior_nodes, next_node=next_node
        )
    st.graphviz_chart(visualized, use_container_width=True)


def render_action(state: AppState):
    """Renders the current action, including the reads, writes, and the code for the action.
    With Hamilton actions, it will also show the visualization of the action.

    This can be used individually (with a state object) or within the "render_explorer" view.

    :param state:
    :return:
    """
    app: Application = state.app
    current_node = state.current_action
    actions = {action.name: action for action in app.graph.actions}
    if current_node is None:
        st.markdown("No current action.")
        return
    st.header(f"`{current_node}`")
    action_object = actions[current_node]
    is_hamilton = isinstance(action_object, Hamilton)
    is_function_api = isinstance(action_object, FunctionBasedAction)

    def format_read(var):
        out = f"- `{var}`"
        if is_hamilton:
            inputs = action_object._inputs  # TODO -- don't use private variables
            corresponding_input = {
                k: v for k, v in inputs.items() if isinstance(v, StateSource) and v.state_key == var
            }
            if corresponding_input:
                return f"- `state['{var}']` → `{list(corresponding_input.keys())[0]}`"
        return out

    def format_write(var):
        out = f"- `{var}`"
        if is_hamilton:
            outputs = action_object._outputs
            corresponding_output = {k: v for k, v in outputs.items() if v.key == var}
            k, v = list(corresponding_output.items())[0]
            if corresponding_output:
                out = f"- `state['{var}']`"
                if v.mode == "update":
                    out += f"← `{k}`"
                if v.mode == "append":
                    out += f" ← `state['{var}'].append({k})`"
                    # out += " (`.append()`)"
        return out

    reads = "\n".join([format_read(var) for var in action_object.reads])
    writes = "\n".join([format_write(var) for var in action_object.writes])
    st.markdown(f"#### Reads: \n {reads}")
    st.markdown(f"#### Writes: \n {writes}")
    if is_hamilton:
        digraph = action_object.visualize_step(show_legend=False)
        st.graphviz_chart(digraph, use_container_width=False)
    elif is_function_api:
        code = inspect.getsource(action_object.fn)
        st.code(code, language="python")
    else:
        code = inspect.getsource(action_object.__class__)
        st.code(code, language="python")


def render_state_results(state: AppState):
    """Render the state and results for the current state. This includes the state and the result of the action.
    This can be used individually (with a state object) or within the "render_explorer" view.

    :param state: State object
    :return: None
    """
    if len(state.history) == 0:  # empty, have not yet started
        return
    current_node = state.current_action
    st.header(f"`{current_node}`")
    state_to_render = state.history[state.display_index].state
    result_to_render = state.history[state.display_index].result
    # if "chat_history" in state_to_render:
    #     del state_to_render["chat_history"]
    st.header("State")
    st.json(state_to_render, expanded=True)
    st.header("Result")
    st.json(result_to_render, expanded=True)


def set_slider_to_current():
    st.session_state.index_slider = get_state().max_index


def render_explorer(app_state: AppState):
    """Renders the entire explorer, including the state machine, the action, and the state/results.

    :param app_state: State of the app
    :return: None
    """
    total_state_length = len(app_state.history)
    placeholder = st.empty()
    placeholder.markdown("`   `")
    if total_state_length > 1:
        slider_values = list(range(total_state_length))
        slider_strings = [record.action for record in app_state.history]

        def stringify(i):
            return slider_strings[i]

        slider = st.select_slider(
            "index",
            options=slider_values,
            label_visibility="hidden",
            format_func=stringify,
            key="index_slider",
        )
        current_node_index = slider
        # TODO -- consider a callback here instead
        app_state.display_index = current_node_index

    with placeholder.container(height=900):
        state_machine_view, step_view, data_view = st.tabs(
            ["Application", "Action", "State/Results"]
        )
        with st.container():
            with state_machine_view:
                render_state_machine(app_state)
            with step_view:
                render_action(app_state)
            with data_view:
                render_state_results(app_state)
    update_state(app_state)
