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

import os
import textwrap

import lancedb
import openai

from burr.core import Application, ApplicationBuilder, State, action
from burr.lifecycle import PostRunStepHook


@action(reads=[], writes=["relevant_chunks", "chat_history"])
def relevant_chunk_retrieval(
    state: State,
    user_query: str,
    lancedb_con: lancedb.DBConnection,
) -> State:
    """Search LanceDB with the user query and return the top 4 results"""
    text_chunks_table = lancedb_con.open_table("apache_burr___contexts")
    search_results = (
        text_chunks_table.search(user_query).select(["text", "id__"]).limit(4).to_list()
    )

    return state.update(relevant_chunks=search_results).append(chat_history=user_query)


@action(reads=["chat_history", "relevant_chunks"], writes=["chat_history"])
def bot_turn(state: State, llm_client: openai.OpenAI) -> State:
    """Collect relevant chunks and produce a response to the user query"""
    user_query = state["chat_history"][-1]
    relevant_chunks = state["relevant_chunks"]

    system_prompt = textwrap.dedent(
        """You are a conversational agent designed to discuss and provide \
        insights about various blog posts. Your task is to engage users in \
        meaningful conversations based on the content of the blog articles they mention.
        """
    )
    joined_chunks = " ".join([c["text"] for c in relevant_chunks])
    user_prompt = "BLOGS CONTENT\n" + joined_chunks + "\nUSER QUERY\n" + user_query

    response = llm_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    bot_answer = response.choices[0].message.content

    return state.append(chat_history=bot_answer)


class PrintBotAnswer(PostRunStepHook):
    """Hook to print the bot's answer"""

    def post_run_step(self, *, state, action, **future_kwargs):
        if action.name == "bot_turn":
            print("\n🤖: ", state["chat_history"][-1])


def build_application() -> Application:
    """Create the Burr `Application`. This is responsible for instantiating the
    OpenAI client and the LanceDB connection
    """
    llm_client = openai.OpenAI()
    lancedb_con = lancedb.connect(os.environ["DESTINATION__LANCEDB__CREDENTIALS__URI"])

    return (
        ApplicationBuilder()
        .with_actions(
            relevant_chunk_retrieval.bind(lancedb_con=lancedb_con),
            bot_turn.bind(llm_client=llm_client),
        )
        .with_transitions(
            ("relevant_chunk_retrieval", "bot_turn"),
            ("bot_turn", "relevant_chunk_retrieval"),
        )
        .with_entrypoint("relevant_chunk_retrieval")
        .with_tracker("local", project="substack-rag", use_otel_tracing=True)
        .with_hooks(PrintBotAnswer())
        .build()
    )


if __name__ == "__main__":
    import utils

    from burr.integrations.opentelemetry import init_instruments

    utils.set_environment_variables()  # set environment variables for LanceDB
    init_instruments("openai", "lancedb")  # register the OpenTelemetry instrumentation

    # build the Burr `Application`
    app = build_application()
    app.visualize("statemachine.png")

    # Launch the Burr application in a `while` loop
    print("\n## Lauching RAG application ##")
    while True:
        user_query = input("\nAsk something or type `quit/q` to exit: ")
        if user_query.lower() in ["quit", "q"]:
            break

        _, _, _ = app.run(
            halt_after=["bot_turn"],
            inputs={"user_query": user_query},
        )
