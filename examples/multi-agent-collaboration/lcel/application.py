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
Langchain version of the multi-agent collaboration example.

This also adds a tracer to the Langchain calls to trace the execution of the nodes
within the Action so that they also show up in the Burr UI. This is a
very simple tracer, it could easily be extended to include more information.
"""
import json
import uuid
from typing import Annotated, Any, Optional
from uuid import UUID

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import FunctionMessage, HumanMessage
from langchain_core.outputs import LLMResult
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_function
from langchain_experimental.utilities import PythonREPL
from langchain_openai import ChatOpenAI
from langgraph.prebuilt.tool_executor import ToolExecutor, ToolInvocation

from burr import core
from burr.core import Action, State, action, default, expr
from burr.lifecycle import PostRunStepHook
from burr.tracking import client as burr_tclient
from burr.visibility import ActionSpanTracer, TracerFactory

# ---- Define the tools -----
tavily_tool = TavilySearchResults(max_results=5)
repl = PythonREPL()


@tool
def python_repl(code: Annotated[str, "The python code to execute to generate your chart."]):
    """Use this to execute python code. If you want to see the output of a value,
    you should print it out with `print(...)`. This is visible to the user."""
    try:
        # Warning: This executes code locally, which can be unsafe when not sandboxed
        result = repl.run(code)
    except BaseException as e:
        return f"Failed to execute. Error: {repr(e)}"
    return f"Succesfully executed:\n```python\n{code}\n```\nStdout: {result}"


tools = [tavily_tool, python_repl]
tool_executor = ToolExecutor(tools)


# Define the tracer
class LangChainTracer(BaseCallbackHandler):
    """Example tracer to plug into Burr's tracing capture."""

    def __init__(self, tracer: TracerFactory):
        self._tracer: TracerFactory = tracer
        self.active_spans = {}

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any) -> Any:
        """Run when LLM starts running."""
        model_name = kwargs["invocation_params"]["model_name"]
        run_id = kwargs["run_id"]
        name = (model_name + "_" + str(run_id))[:30]
        context_manager: ActionSpanTracer = self._tracer(name)
        context_manager.__enter__()
        self.active_spans[name] = context_manager

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        """Run when LLM ends running."""
        model_name = response.llm_output["model_name"]
        name = (model_name + "_" + str(run_id))[:30]
        context_manager = self.active_spans.pop(name)
        context_manager.__exit__(None, None, None)


# Agents / actions
def create_agent(llm, tools, system_message: str):
    """Helper function to create an agent with a system message and tools."""
    functions = [convert_to_openai_function(t) for t in tools]

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a helpful AI assistant, collaborating with other assistants."
                " Use the provided tools to progress towards answering the question."
                " If you are unable to fully answer, that's OK, another assistant with different tools "
                " will help where you left off. Execute what you can to make progress."
                " If you or any of the other assistants have the final answer or deliverable,"
                " prefix your response with FINAL ANSWER so the team knows to stop."
                " You have access to the following tools: {tool_names}.\n{system_message}",
            ),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )
    prompt = prompt.partial(system_message=system_message)
    prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
    return prompt | llm.bind_functions(functions)


def _exercise_agent(messages: list, sender: str, agent, name: str, tracer: TracerFactory) -> dict:
    """Helper function to exercise the agent code."""
    tracer = LangChainTracer(tracer)
    result = agent.invoke({"messages": messages, "sender": sender}, config={"callbacks": [tracer]})
    # We convert the agent output into a format that is suitable to append to the global state
    if isinstance(result, FunctionMessage):
        pass
    else:
        result = HumanMessage(**result.dict(exclude={"type", "name"}), name=name)
    return {
        "messages": result,
        # Since we have a strict workflow, we can
        # track the sender so we know who to pass to next.
        "sender": name,
    }


# Define the actual agents via langchain
llm = ChatOpenAI(model="gpt-4o-mini")
research_agent = create_agent(
    llm,
    [tavily_tool],
    system_message="You should provide accurate data for the chart generator to use.",
)
chart_agent = create_agent(
    llm,
    [python_repl],
    system_message="Any charts you display will be visible by the user.",
)


@action(reads=["messages", "sender"], writes=["messages", "sender"])
def research_node(state: State, __tracer: TracerFactory) -> tuple[dict, State]:
    # Research agent and node
    result = _exercise_agent(
        state["messages"], state["sender"], research_agent, "Researcher", __tracer
    )
    return result, state.append(messages=result["messages"]).update(sender="Researcher")


@action(reads=["messages", "sender"], writes=["messages", "sender"])
def chart_node(state: State, __tracer: TracerFactory) -> tuple[dict, State]:
    # Chart agent and node
    result = _exercise_agent(
        state["messages"], state["sender"], chart_agent, "Chart Generator", __tracer
    )
    return result, state.append(messages=result["messages"]).update(sender="Chart Generator")


@action(reads=["messages"], writes=["messages"])
def tool_node(state: State) -> tuple[dict, State]:
    """This runs tools in the graph

    It takes in an agent action and calls that tool and returns the result."""
    messages = state["messages"]
    # Based on the continue condition
    # we know the last message involves a function call
    last_message = messages[-1]
    # We construct an ToolInvocation from the function_call
    tool_input = json.loads(last_message.additional_kwargs["function_call"]["arguments"])
    # We can pass single-arg inputs by value
    if len(tool_input) == 1 and "__arg1" in tool_input:
        tool_input = next(iter(tool_input.values()))
    tool_name = last_message.additional_kwargs["function_call"]["name"]
    action = ToolInvocation(
        tool=tool_name,
        tool_input=tool_input,
    )
    # We call the tool_executor and get back a response
    response = tool_executor.invoke(action)
    # We use the response to create a FunctionMessage
    function_message = FunctionMessage(
        content=f"{tool_name} response: {str(response)}", name=action.tool
    )
    # We return a list, because this will get added to the existing list
    return {"messages": [function_message]}, state.append(messages=function_message)


@action(reads=[], writes=[])
def terminal_step(state: State) -> tuple[dict, State]:
    """Terminal step we have here that does nothing, but it could"""
    return {}, state


class PrintStepHook(PostRunStepHook):
    def post_run_step(self, *, state: "State", action: "Action", **future_kwargs):
        print("action=====\n", action)
        print("state======\n", state)


def default_state_and_entry_point(query: str = None) -> tuple[dict, str]:
    """Sets the default state & entry point
    :param query: the query for the agents to work on.
    :return:
    """
    if query is None:
        query = (
            "Fetch the UK's GDP over the past 5 years,"
            " then draw a line graph of it."
            " Once you code it up, finish."
        )
    return (
        dict(
            messages=[HumanMessage(content=query)],
            sender=None,
        ),
        "researcher",
    )


def main(query: str = None, app_instance_id: str = None, sequence_id: int = None):
    """Main function to run the multi-agent collaboration example.

    Pass in a query to start from a specific query.
    Pass in an app_instance_id to restart from a previous run.
    Pass in an sequence_id to restart from a previous run and a specific position in it.
    """
    if app_instance_id is None:
        app_instance_id = str(uuid.uuid4())
    project_name = "demo_lcel-multi-agent"
    tracker_persister = burr_tclient.LocalTrackingClient(project_name)
    default_state, default_entrypoint = default_state_and_entry_point(query)
    app = (
        core.ApplicationBuilder()
        .with_actions(
            researcher=research_node,
            charter=chart_node,
            call_tool=tool_node,
            terminal=terminal_step,
        )
        .with_transitions(
            ("researcher", "call_tool", expr("'function_call' in messages[-1].additional_kwargs")),
            ("researcher", "terminal", expr("'FINAL ANSWER' in messages[-1].content")),
            ("researcher", "charter", default),
            ("charter", "call_tool", expr("'function_call' in messages[-1].additional_kwargs")),
            ("charter", "terminal", expr("'FINAL ANSWER' in messages[-1].content")),
            ("charter", "researcher", default),
            ("call_tool", "researcher", expr("sender == 'Researcher'")),
            ("call_tool", "charter", expr("sender == 'Chart Generator'")),
        )
        .with_identifiers(
            app_id=app_instance_id, partition_key="sample_user", sequence_id=sequence_id
        )
        .initialize_from(
            tracker_persister,
            resume_at_next_action=True,
            default_state=default_state,
            default_entrypoint=default_entrypoint,
        )
        .with_hooks(PrintStepHook())
        .with_tracker(tracker_persister)
        .build()
    )
    app.visualize(
        output_file_path="lcel-multi-agent", include_conditions=True, view=True, format="png"
    )
    app.run(halt_after=["terminal"])


if __name__ == "__main__":
    main(app_instance_id="e80f405b-2c79-4bc9-88d2-23413ceb5881", sequence_id=8)
    # main("Fetch the UK's GDP over the past 5 years,"
    #                  " then draw a line graph of it."
    #                  " Once you code it up, finish.")
    # main(app_instance_id=SOME_APP_ID)  # use this to restart from a previous state
