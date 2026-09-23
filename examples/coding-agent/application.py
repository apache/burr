"""Tools the coding agent can call. Each takes typed args and returns a dict."""
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

import inspect
import json
import os
from typing import Callable, Optional

from burr.core import State, action, expr, when
from burr.core.application import ApplicationBuilder

from tools import list_files, read_file, run_bash, write_file

TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "run_bash": run_bash,
}

TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": fn.__doc__ or name,
            "parameters": {
                "type": "object",
                "properties": {
                    p.name: {
                        "type": TYPE_MAP.get(p.annotation, "string"),
                        "description": p.name,
                    }
                    for p in inspect.signature(fn).parameters.values()
                },
                "required": [
                    p.name
                    for p in inspect.signature(fn).parameters.values()
                    if p.default is inspect.Parameter.empty
                ],
            },
        },
    }
    for name, fn in TOOLS.items()
]

SYSTEM_PROMPT = (
    "You are a coding agent working inside a project directory. "
    "Use the tools to inspect and modify files, and to run commands. "
    "Work one step at a time: look before you edit, and verify changes by running them. "
    "When the task is complete, reply with a short summary and request no tool."
)


# --- LLM clients -----------------------------------------------------------
# Both return the same shape:
#   {"content": str | None, "tool_calls": [{"id", "name", "args"}]}


class OpenAIClient:
    """Calls OpenAI's chat completions API with tool calling enabled."""

    def __init__(self, model: str = "gpt-4o"):
        self.model = model

    def __call__(self, messages: list[dict]) -> dict:
        import openai

        response = openai.chat.completions.create(
            model=self.model, messages=messages, tools=OPENAI_TOOLS
        )
        message = response.choices[0].message
        calls = [
            {"id": c.id, "name": c.function.name, "args": json.loads(c.function.arguments)}
            for c in (message.tool_calls or [])
        ]
        return {"content": message.content, "tool_calls": calls}


class ScriptedClient:
    """Replays a fixed list of responses. Lets the example run without an API key."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.index = 0

    def __call__(self, messages: list[dict]) -> dict:
        if self.index >= len(self.responses):
            return {"content": "Script exhausted.", "tool_calls": []}
        response = self.responses[self.index]
        self.index += 1
        return response


DEFAULT_SCRIPT = [
    {"content": None, "tool_calls": [{"id": "c1", "name": "list_files", "args": {}}]},
    {
        "content": None,
        "tool_calls": [
            {"id": "c2", "name": "write_file",
             "args": {"path": "hello.py", "contents": "print('hello from the agent')\n"}}
        ],
    },
    {"content": None, "tool_calls": [{"id": "c3", "name": "run_bash",
                                      "args": {"command": "python hello.py"}}]},
    {"content": "Created hello.py and confirmed it runs.", "tool_calls": []},
]


def get_client():
    """Real client when OPENAI_API_KEY is set, otherwise the scripted stand-in."""
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIClient()
    return ScriptedClient(DEFAULT_SCRIPT)


# --- Actions ---------------------------------------------------------------


@action(reads=[], writes=["task", "messages", "steps", "done", "final_answer"])
def human_input(state: State, task: str) -> State:
    """Takes a task from the user and starts a fresh run."""
    return state.update(
        task=task,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ],
        steps=0,
        done=False,
        final_answer=None,
    )


@action(reads=["messages"], writes=["messages"])
def create_prompt(state: State) -> State:
    """Seam for shaping the prompt before each call -- add file trees, summaries, etc."""
    return state.update(messages=state["messages"])


@action(
    reads=["messages", "steps"],
    writes=["messages", "next_tool", "next_args", "last_tool_call_id",
            "steps", "done", "final_answer"],
)
def call_llm(state: State, client: Callable) -> State:
    """Asks the model what to do next: call a tool, or finish."""
    result = client(state["messages"])
    calls = result["tool_calls"]

    if not calls:
        return state.update(
            messages=state["messages"] + [{"role": "assistant", "content": result["content"]}],
            next_tool=None,
            next_args={},
            last_tool_call_id=None,
            steps=state["steps"] + 1,
            done=True,
            final_answer=result["content"],
        )

    # One tool per iteration keeps the graph readable; extras are dropped.
    call = calls[0]
    assistant_message = {
        "role": "assistant",
        "content": result["content"],
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["args"])},
            }
        ],
    }
    return state.update(
        messages=state["messages"] + [assistant_message],
        next_tool=call["name"],
        next_args=call["args"],
        last_tool_call_id=call["id"],
        steps=state["steps"] + 1,
        done=False,
        final_answer=None,
    )


@action(reads=["next_args", "last_tool_call_id", "messages"], writes=["messages"])
def execute_tool(state: State, tool_function: Callable) -> State:
    """Runs one tool and feeds its result back to the model."""
    result = tool_function(**state["next_args"])
    return state.update(
        messages=state["messages"]
        + [
            {
                "role": "tool",
                "tool_call_id": state["last_tool_call_id"],
                "content": json.dumps(result),
            }
        ]
    )


@action(reads=["final_answer", "steps", "max_steps"], writes=["final_answer"])
def respond(state: State) -> State:
    """Surfaces the answer, or explains that the budget ran out."""
    if state["final_answer"]:
        return state.update(final_answer=state["final_answer"])
    return state.update(
        final_answer=f"Stopped after {state['steps']} steps without finishing the task."
    )


def application(app_id: Optional[str] = None, max_steps: int = 15, client: Callable = None):
    """Builds the coding agent application."""
    client = client or get_client()
    return (
        ApplicationBuilder()
        .with_actions(
            human_input,
            create_prompt,
            respond,
            call_llm=call_llm.bind(client=client),
            read_file=execute_tool.bind(tool_function=read_file),
            write_file=execute_tool.bind(tool_function=write_file),
            list_files=execute_tool.bind(tool_function=list_files),
            run_bash=execute_tool.bind(tool_function=run_bash),
        )
        .with_transitions(
            ("human_input", "create_prompt"),
            ("create_prompt", "call_llm"),
            ("call_llm", "respond", when(done=True)),
            ("call_llm", "respond", expr("steps>=max_steps")),
            ("call_llm", "read_file", when(next_tool="read_file")),
            ("call_llm", "write_file", when(next_tool="write_file")),
            ("call_llm", "list_files", when(next_tool="list_files")),
            ("call_llm", "run_bash", when(next_tool="run_bash")),
            (["read_file", "write_file", "list_files", "run_bash"], "call_llm"),
            ("respond", "human_input"),
        )
        .with_state(max_steps=max_steps, steps=0, messages=[], done=False, final_answer=None)
        .with_identifiers(app_id=app_id)
        .with_entrypoint("human_input")
        .with_tracker(project="demo_coding_agent")
        .build()
    )


if __name__ == "__main__":
    app = application()
    app.visualize(output_file_path="./statemachine.png")
    _, _, state = app.run(
        halt_after=["respond"],
        inputs={"task": "Create a hello.py that prints a greeting, then run it."},
    )
    print(state["final_answer"])