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
Template for a multi-modal agent.

The idea is that this whole application functions as an agent that can do
multi-modal things.

Fill in the functions, and adjust/create new actions as needed.
"""

from typing import Tuple

from burr import tracking
from burr.core import Application, ApplicationBuilder, State, default, when
from burr.core.action import action


@action(reads=[], writes=["chat_history", "query"])
def apply_input_query(state: State, user_query: str) -> Tuple[dict, State]:
    # this is a simple example of how you might process a user query -- stick it directly into the chat history
    result = {"chat_item": {"role": "user", "content": user_query, "type": "text"}}
    new_state = state.append(chat_history=result["chat_item"]).update(query=user_query)
    return result, new_state


@action(reads=["prompt"], writes=["mode"])
def choose_mode(state: State) -> Tuple[dict, State]:
    """Code to choose a mode"""
    result = {"mode": "example"}
    return result, state.update(**result)


@action(reads=[], writes=["response"])
def unknown_action(state: State) -> Tuple[dict, State]:
    result = {
        "response": {
            "content": "None of the response modes I support apply to your question. Please clarify?",
            "type": "text",
            "role": "assistant",
        }
    }
    return result, state.update(**result)


@action(reads=["query", "chat_history", "mode"], writes=["response"])
def some_action(state: State) -> Tuple[dict, State]:
    """An example action -- create more of these to handle different modes"""
    _query = state["query"]  # noqa:F841
    _mode = state["mode"]  # noqa:F841
    _chat_history = state["chat_history"]  # noqa:F841
    result = {"response": {"some": "response"}}
    return result, state.update(**result)


@action(reads=["query", "mode", "response"], writes=["chat_history"])
def response(state: State) -> Tuple[dict, State]:
    """Function to create a response based on the prior action."""
    _result = {
        "content": state["response"],
        "type": state["mode"],
        "role": "assistant",
    }
    return _result, state.append(chat_history=_result)


def base_application(app_id: str, storage_dir: str, project_id: str) -> Application:
    """Creates the Burr application"""
    tracker = tracking.LocalTrackingClient(project=project_id, storage_dir=storage_dir)
    return (
        ApplicationBuilder()
        .with_actions(
            apply_input_query=apply_input_query,
            decide_mode=choose_mode,
            unknown_action=unknown_action,
            some_action=some_action,
            response=response,
        )
        .with_transitions(
            ("apply_input_query", "decide_mode", default),
            ("decide_mode", "unknown_action", when(mode="unknown")),
            ("decide_mode", "some_action", when(mode="some_action")),
            (["unknown_action", "some_action"], "response", default),
            ("response", "apply_input_query", default),
        )
        # initializes from the tracking log if it does not already exist
        .initialize_from(
            tracker,
            resume_at_next_action=False,  # always resume from entrypoint in the case of failure
            default_state={"chat_history": []},
            default_entrypoint="apply_input_query",
        )
        .with_tracker(tracker)
        .with_identifiers(app_id=app_id)
        .build()
    )


if __name__ == "__main__":
    import uuid

    app_id: str = str(uuid.uuid4())
    storage_dir: str = "~/.burr"
    project_id: str = "template:multi-modal-agent"
    app = base_application(app_id, storage_dir, project_id)
    app.visualize(
        output_file_path="multi_modal_agent", include_conditions=False, view=True, format="png"
    )
    # this is how you could run one cycle of the agent:
    # app.run(halt_after=["response"], inputs={"user_query": "Hello, world!"})
