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

# This is a simple chatbot to trace Langfuse

"""
Requires the following environment variables (see https://langfuse.com):

- LANGFUSE_PUBLIC_KEY
- LANGFUSE_SECRET_KEY
- LANGFUSE_HOST (e.g. https://cloud.langfuse.com)
- OPENAI_API_KEY
"""

from typing import Optional, Tuple

import openai

from burr.core import Application, ApplicationBuilder, State
from burr.core.action import action
from burr.integrations.langfuse import LangfuseBridge
from burr.visibility import TracerFactory, trace

try:
    # Optional: with the openai instrumentor installed, LLM calls (prompts, completions, token usage) show up as generations nested inside Burr steps.
    # pip install opentelemetry-instrumentation-openai
    from opentelemetry.instrumentation.openai import OpenAIInstrumentor

    OpenAIInstrumentor().instrument()
except ImportError:
    pass


@action(reads=[], writes=["chat_history", "prompt"])
def process_prompt(state: State, prompt: str) -> Tuple[dict, State]:
    result = {"chat_item": {"role": "user", "content": prompt}}
    return result, state.append(chat_history=result["chat_item"]).update(prompt=prompt)


@trace()
def _query_openai(prompt: str, chat_history: Optional[list] = None) -> str:
    client = openai.Client()
    result = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant"},
            *(chat_history or []),
            {"role": "user", "content": prompt},
        ],
    )
    return result.choices[0].message.content


@action(reads=["prompt", "chat_history"], writes=["chat_history"])
def chat_response(state: State, __tracer: TracerFactory) -> Tuple[dict, State]:
    with __tracer("prepare_history"):
        chat_history = state["chat_history"].copy()
        __tracer.log_attributes(history_length=len(chat_history))
    content = _query_openai(prompt=state["prompt"], chat_history=chat_history[:-1])
    result = {"chat_item": {"role": "assistant", "content": content}}
    return result, state.append(chat_history=result["chat_item"])


def application(
    app_id: Optional[str] = None,
    user_id: Optional[str] = None,
    bridge: Optional[LangfuseBridge] = None,
) -> Application:
    return (
        ApplicationBuilder()
        .with_actions(process_prompt, chat_response)
        .with_transitions(
            ("process_prompt", "chat_response"),
            ("chat_response", "process_prompt"),
        )
        .with_state(chat_history=[])
        .with_entrypoint("process_prompt")
        .with_identifiers(app_id=app_id, partition_key=user_id)
        # reads LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY/LANGFUSE_HOST from the environment.
        # app_id maps to the Langfuse session, partition_key to the Langfuse user.
        .with_hooks(bridge if bridge is not None else LangfuseBridge())
        .build()
    )


if __name__ == "__main__":
    bridge = LangfuseBridge()
    app = application(user_id="example-user", bridge=bridge)
    for user_prompt in ["What is Burr?", "And what is Langfuse?"]:
        # each .run() call logs one trace to Langfuse
        action_, result, state = app.run(
            halt_after=["chat_response"], inputs={"prompt": user_prompt}
        )
        print(state["chat_history"][-1]["content"])
    # flush before exiting a short-lived script -- the client batches exports
    bridge.langfuse_client.flush()
