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

from typing import Tuple

import openai  # replace this with your favorite LLM client library

from burr.core import ApplicationBuilder, State, action, when


@action(reads=[], writes=["prompt", "chat_history"])
def human_input(state: State, prompt: str) -> Tuple[dict, State]:
    """Pulls human input from the outside world and massages it into a standard chat format.
    Note we're adding it into the chat history (with an `append` operation). This
    is just for convenience of reference -- we could easily just store the chat history
    and access it.
    """

    chat_item = {"content": prompt, "role": "user"}
    # return the prompt as the result
    # put the prompt in state and update the chat_history
    return {"prompt": prompt}, state.update(prompt=prompt).append(chat_history=chat_item)


@action(reads=["chat_history"], writes=["response", "chat_history"])
def ai_response(state: State) -> Tuple[dict, State]:
    """Queries OpenAI with the chat. You could easily use langchain, etc... to handle this,
    but we wanted to keep it simple to demonstrate"""
    client = openai.Client()  # replace this with your favorite LLM client library
    content = (
        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=state["chat_history"],
        )
        .choices[0]
        .message.content
    )
    chat_item = {"content": content, "role": "assistant"}
    # return the response as the result
    # put the response in state and update the chat history
    return {"response": content}, state.update(response=content).append(chat_history=chat_item)


@action(reads=["prompt"], writes=["safe"])
def safety_check(state: State) -> Tuple[dict, State]:
    safe = "unsafe" not in state["prompt"]
    return {"safe": safe}, state.update(safe=safe)


@action(reads=[], writes=["response", "chat_history"])
def unsafe_response(state: State) -> Tuple[dict, State]:
    content = "I'm sorry, my overlords have forbidden me to respond."
    new_state = state.update(response=content).append(
        chat_history={"content": content, "role": "assistant"}
    )
    return {"response": content}, new_state


def application():
    return (
        ApplicationBuilder()
        .with_actions(
            human_input=human_input,
            ai_response=ai_response,
            safety_check=safety_check,
            unsafe_response=unsafe_response,
        )
        .with_transitions(
            ("human_input", "safety_check"),
            ("safety_check", "unsafe_response", when(safe=False)),
            ("safety_check", "ai_response", when(safe=True)),
            (["unsafe_response", "ai_response"], "human_input"),
        )
        .with_state(chat_history=[])
        .with_entrypoint("human_input")
        .with_tracker("local", project="demo_getting_started")
        .build()
    )


if __name__ == "__main__":
    app = application()
    app.visualize(include_conditions=True, format="png", view=True, output_file_path="statemachine")
    # for prompt in [
    #     "Who was Aaron Burr, sir?",
    #     "Who was Aaron Burr, sir (unsafe)?",
    #     "If you had ml/ai libraries called 'Hamilton' and 'Burr', what would they do?",
    #     "Who was Aaron Burr, sir?",
    #     "Who was Aaron Burr, sir (unsafe)?",
    #     "If you had ml/ai libraries called 'Hamilton' and 'Burr', what would they do?",
    # ]:
    #     action_we_ran, result, state = app.run(
    #         halt_after=["ai_response", "unsafe_response"],
    #         inputs={"prompt": prompt}
    #     )
    # for item in state['chat_history']:
    #     print(item['role'] + ':' + item['content'] + '\n')
