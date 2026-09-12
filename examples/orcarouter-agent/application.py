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

"""A minimal Burr agent that talks to [OrcaRouter](https://www.orcarouter.ai).

[OrcaRouter](https://www.orcarouter.ai) exposes an OpenAI-compatible API at
``https://api.orcarouter.ai/v1``, so we can point the ``openai`` client at it
and use the ``orcarouter/auto`` model alias. Set ``ORCAROUTER_API_KEY`` to
your OrcaRouter key before running.
"""

import os
from typing import Tuple

import openai

from burr.core import ApplicationBuilder, State, action

ORCAROUTER_BASE_URL = os.getenv("ORCAROUTER_BASE_URL", "https://api.orcarouter.ai/v1")
ORCAROUTER_MODEL = os.getenv("ORCAROUTER_MODEL", "orcarouter/auto")


def _orcarouter_client() -> openai.OpenAI:
    """Create an OpenAI-compatible client pointed at the OrcaRouter gateway."""
    return openai.OpenAI(
        base_url=ORCAROUTER_BASE_URL,
        api_key=os.environ["ORCAROUTER_API_KEY"],
    )


@action(reads=[], writes=["prompt", "chat_history"])
def human_input(state: State, prompt: str) -> Tuple[dict, State]:
    """Pull human input from the outside world and add it to the chat history."""
    chat_item = {"content": prompt, "role": "user"}
    return {"prompt": prompt}, state.update(prompt=prompt).append(chat_history=chat_item)


@action(reads=["chat_history"], writes=["response", "chat_history"])
def ai_response(state: State) -> Tuple[dict, State]:
    """Query OrcaRouter with the full chat history."""
    client = _orcarouter_client()
    content = (
        client.chat.completions.create(
            model=ORCAROUTER_MODEL,
            messages=state["chat_history"],
        )
        .choices[0]
        .message.content
    )
    chat_item = {"content": content, "role": "assistant"}
    return {"response": content}, state.update(response=content).append(chat_history=chat_item)


def application():
    return (
        ApplicationBuilder()
        .with_actions(
            human_input=human_input,
            ai_response=ai_response,
        )
        .with_transitions(
            ("human_input", "ai_response"),
            ("ai_response", "human_input"),
        )
        .with_state(chat_history=[])
        .with_entrypoint("human_input")
        .build()
    )


if __name__ == "__main__":
    import sys

    app = application()
    app.visualize(
        output_file_path="statemachine",
        include_conditions=False,
        view=False,
        format="png",
    )

    prompt = sys.argv[1] if len(sys.argv) > 1 else "Tell me a one-sentence fact about the ocean."
    _, result, state = app.run(halt_after=["ai_response"], inputs={"prompt": prompt})
    print(result["response"])
