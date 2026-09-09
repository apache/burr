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

import argparse

import openai

from burr.core import ApplicationBuilder, State, action
from burr.integrations.persisters.b_aerospike import AerospikePersister

MODEL = "gpt-4o-mini"
MAX_HISTORY_ITEMS = 20
client = openai.Client()


@action(reads=["chat_history"], writes=["prompt", "chat_history"])
def human_input(state: State, prompt: str) -> State:
    chat_item = {"content": prompt, "role": "user"}
    chat_history = [*state["chat_history"], chat_item][-MAX_HISTORY_ITEMS:]
    return state.update(prompt=prompt, chat_history=chat_history)


@action(reads=["chat_history"], writes=["response", "chat_history"])
def ai_response(state: State) -> State:
    content = client.chat.completions.create(
        model=MODEL,
        messages=state["chat_history"],
    ).choices[0].message.content
    chat_item = {"content": content, "role": "assistant"}
    chat_history = [*state["chat_history"], chat_item][-MAX_HISTORY_ITEMS:]
    return state.update(response=content, chat_history=chat_history)


def build_application(persister: AerospikePersister, app_id: str, partition_key: str):
    return (
        ApplicationBuilder()
        .with_actions(human_input, ai_response)
        .with_transitions(
            ("human_input", "ai_response"),
            ("ai_response", "human_input"),
        )
        .initialize_from(
            persister,
            resume_at_next_action=True,
            default_state={"chat_history": []},
            default_entrypoint="human_input",
        )
        .with_state_persister(persister)
        .with_identifiers(app_id=app_id, partition_key=partition_key)
        .build()
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", default="aerospike-chatbot")
    parser.add_argument("--partition-key", default="example-user")
    parser.add_argument("--prompt")
    args = parser.parse_args()

    with AerospikePersister.from_values(
        hosts=[("127.0.0.1", 3000)],
        namespace="test",
        key_prefix="aerospike-example",
    ) as persister:
        persister.initialize()
        app = build_application(persister, args.app_id, args.partition_key)
        if args.prompt:
            *_, state = app.run(halt_after=["ai_response"], inputs={"prompt": args.prompt})
            print(state["response"])
            return

        while True:
            prompt = input("you: ").strip()
            if prompt.lower() in {"exit", "quit"}:
                break
            *_, state = app.run(halt_after=["ai_response"], inputs={"prompt": prompt})
            print("assistant:", state["response"])


if __name__ == "__main__":
    main()
