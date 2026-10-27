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
Agent supervisor example.

This fleshes out the `agent_supervisor.py` template in `examples/templates/`
with a real, runnable implementation: an LLM-driven supervisor that routes
between a `researcher` agent (web search) and a `coder` agent (python
execution / chart generation), similar in spirit to the `multi-agent-collaboration`
example -- but here routing is decided by the supervisor's own LLM call at each
step, rather than fixed transitions.

This mirrors LangGraph's own "agent supervisor" pattern:
https://github.com/langchain-ai/langgraph/blob/main/examples/multi_agent/agent_supervisor.ipynb

Uses the plain OpenAI SDK for LLM calls (see `examples/email-assistant`), rather
than LangChain or Hamilton, to keep the example dependency-light and easy to follow.
"""
import functools
import json
import os

import openai

from burr import core
from burr.core import ApplicationBuilder, State, action, default
from burr.tracking import client as burr_tclient

# --- Set up the LLM client ---


@functools.lru_cache
def _get_openai_client():
    return openai.Client()


# --- Define the tools ---


def web_search(query: str) -> str:
    """Search the web for information relevant to `query`.

    This is a placeholder -- swap in a real search tool (e.g. Tavily) by
    setting the TAVILY_API_KEY environment variable and calling out to it here.
    """
    if os.environ.get("TAVILY_API_KEY"):
        from tavily import TavilyClient

        tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
        response = tavily_client.search(query, max_results=5)
        return json.dumps(response.get("results", []))
    return f"[no TAVILY_API_KEY set -- pretend this is search results for: {query}]"


def python_exec(code: str) -> str:
    """Execute python code and return anything printed to stdout.

    Warning: executes code locally/unsandboxed -- for demonstration only.
    """
    import io
    from contextlib import redirect_stdout

    output = io.StringIO()
    try:
        with redirect_stdout(output):
            exec(code, {})
    except BaseException as e:
        return f"Failed to execute. Error: {repr(e)}"
    return f"Executed:\n```python\n{code}\n```\nStdout: {output.getvalue()}"


TOOLS = {
    "web_search": web_search,
    "python_exec": python_exec,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "python_exec",
            "description": "Execute python code, e.g. to compute or chart something.",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        },
    },
]

MEMBERS = ["researcher", "coder"]

# --- Start defining Actions ---


@action(reads=["query", "messages"], writes=["next_step"])
def supervisor_agent(state: State) -> tuple[dict, State]:
    """Decides which agent should act next, or whether to terminate."""
    client = _get_openai_client()
    options = MEMBERS + ["FINISH"]
    system_message = (
        "You are a supervisor managing a conversation between the following "
        f"workers: {', '.join(MEMBERS)}. Given the request and the conversation so far, "
        "respond with which worker should act next. Each worker will perform a task "
        "and report back. When the task is complete, respond with FINISH. "
        f"Respond with exactly one word: one of {options}."
    )
    messages = [{"role": "system", "content": system_message}]
    messages.append({"role": "user", "content": state["query"]})
    messages.extend(state["messages"])
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
    )
    choice = response.choices[0].message.content.strip()
    next_step = choice if choice in options else "FINISH"
    result = {"next_step": "terminate" if next_step == "FINISH" else next_step}
    return result, state.update(**result)


def _run_agent(state: State, system_message: str, sender: str) -> tuple[dict, State]:
    """Shared logic for the researcher/coder agents: call the LLM with tools bound."""
    client = _get_openai_client()
    messages = [{"role": "system", "content": system_message}]
    messages.append({"role": "user", "content": state["query"]})
    messages.extend(state["messages"])
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        tools=TOOL_SCHEMAS,
    )
    message = response.choices[0].message
    tool_calls = []
    for tool_call in message.tool_calls or []:
        tool_calls.append(
            {
                "id": tool_call.id,
                "name": tool_call.function.name,
                "args": tool_call.function.arguments,
            }
        )
    new_message = {"role": "assistant", "content": message.content or "", "name": sender}
    result = {"parsed_tool_calls": tool_calls}
    new_state = state.append(messages=new_message).update(
        parsed_tool_calls=tool_calls, sender=sender
    )
    return result, new_state


@action(reads=["query", "messages"], writes=["messages", "parsed_tool_calls", "sender"])
def researcher(state: State) -> tuple[dict, State]:
    """The research agent -- gathers information via web search."""
    return _run_agent(
        state,
        system_message="You are a researcher. Use web_search to gather accurate "
        "information for the coder to use. Say FINAL ANSWER when done.",
        sender="researcher",
    )


@action(reads=["query", "messages"], writes=["messages", "parsed_tool_calls", "sender"])
def coder(state: State) -> tuple[dict, State]:
    """The coder agent -- writes/executes python to process data or make charts."""
    return _run_agent(
        state,
        system_message="You are a coder. Use python_exec to compute or chart results "
        "based on what the researcher found. Say FINAL ANSWER when done.",
        sender="coder",
    )


@action(reads=["messages", "parsed_tool_calls"], writes=["messages", "parsed_tool_calls"])
def tool_node(state: State) -> tuple[dict, State]:
    """Executes any pending tool calls and appends their results to messages."""
    new_messages = []
    for tool_call in state["parsed_tool_calls"]:
        tool_fn = TOOLS[tool_call["name"]]
        args = json.loads(tool_call["args"])
        result = tool_fn(**args)
        new_messages.append(
            {"role": "tool", "tool_call_id": tool_call["id"], "content": str(result)}
        )
    new_state = state
    for message in new_messages:
        new_state = new_state.append(messages=message)
    new_state = new_state.update(parsed_tool_calls=[])
    return {"messages": new_messages}, new_state


@action(reads=["messages"], writes=[])
def terminal_step(state: State) -> tuple[dict, State]:
    """Terminal step -- does nothing, but could summarize/return a final result."""
    return {}, state


def default_state_and_entry_point(query: str = None) -> tuple[dict, str]:
    """Returns the default state and entry point for the application."""
    if query is None:
        query = (
            "Fetch the UK's GDP over the past 5 years, then draw a line graph of it. "
            "Once the chart code has been written, the task is complete."
        )
    return {
        "messages": [],
        "query": query,
        "sender": "",
        "parsed_tool_calls": [],
        "next_step": "",
    }, "supervisor_agent"


def main(query: str = None, app_instance_id: str = None, sequence_number: int = None):
    """Main function to run the application.

    :param query: the query for the agents to run over.
    :param app_instance_id: a prior app instance id to restart from.
    :param sequence_number: a prior sequence number to restart from.
    """
    project_name = "demo_agent-supervisor"
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

    app = (
        ApplicationBuilder()
        .with_state(**state)
        .with_actions(
            supervisor_agent=supervisor_agent,
            researcher=researcher,
            coder=coder,
            tool_node=tool_node,
            terminal=terminal_step,
        )
        .with_transitions(
            ("supervisor_agent", "researcher", core.when(next_step="researcher")),
            ("supervisor_agent", "coder", core.when(next_step="coder")),
            ("supervisor_agent", "terminal", core.when(next_step="terminate")),
            ("researcher", "tool_node", core.expr("len(parsed_tool_calls) > 0")),
            ("researcher", "supervisor_agent", default),
            ("coder", "tool_node", core.expr("len(parsed_tool_calls) > 0")),
            ("coder", "supervisor_agent", default),
            ("tool_node", "researcher", core.when(sender="researcher")),
            ("tool_node", "coder", core.when(sender="coder")),
        )
        .with_identifiers(partition_key="demo")
        .with_entrypoint(entry_point)
        .with_tracker(project=project_name)
        .build()
    )
    return app


if __name__ == "__main__":
    app = main("Fetch the UK's GDP over the past 5 years, then draw a line graph of it.")
    app.visualize(
        output_file_path="statemachine", include_conditions=True, view=True, format="png"
    )
    app.run(halt_after=["terminal"])