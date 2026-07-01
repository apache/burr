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

import functools
import importlib
import json
from typing import Optional

import openai

from burr.core import Application, ApplicationBuilder, State, action, expr, when
from burr.core.graph import GraphBuilder
from burr.tracking import LocalTrackingClient

try:
    prompts = importlib.import_module("burr.examples.deep-researcher.prompts")
except ModuleNotFoundError:
    import prompts

try:
    utils = importlib.import_module("burr.examples.deep-researcher.deep_researcher_utils")
except ModuleNotFoundError:
    import deep_researcher_utils as utils


@functools.lru_cache
def _get_openai_client():
    """
    Creates and caches an OpenAI client instance.

    Returns:
        openai.Client: A cached OpenAI client instance.
    """
    openai_client = openai.Client()
    return openai_client


def query_openai(system_instructions, human_message_content, stream=False):
    """
    Sends a query to the OpenAI API and retrieves the response.

    Args:
        system_instructions (str): Instructions for the system message.
        human_message_content (str): Content of the human message.
        stream (bool, optional): Whether to stream the response. Defaults to False.

    Returns:
        str: The content of the response from the OpenAI API.
    """
    client = _get_openai_client()
    system_message = {"role": "system", "content": system_instructions}
    human_message = {"role": "user", "content": human_message_content}
    messages = []
    messages.append(system_message)
    messages.append(human_message)

    response = client.chat.completions.create(model="gpt-4o-mini", messages=messages, stream=stream)
    content = response.choices[0].message.content
    return content


@action(
    reads=[],
    writes=[
        "search_query",
        "research_topic",
        "sources_gathered",
        "web_research_results",
        "research_loop_count",
        "running_summary",
    ],
)
def generate_query(state: State, research_topic: str) -> State:
    """
    Generates a search query based on the research topic.

    Args:
        state (State): The current application state.
        research_topic (str): The topic to research.

    Returns:
        State: The updated state with the research topic and generated search query.
    """
    system_prompt_formatted = prompts.query_writer_instructions.format(
        research_topic=research_topic
    )
    human_prompt = "Generate a query for web search:"
    my_query = query_openai(system_prompt_formatted, human_prompt)
    as_dict = json.loads(my_query)
    return state.update(
        search_query=as_dict["query"],
        research_topic=research_topic,
        sources_gathered=[],
        web_research_results=[],
        research_loop_count=0,
        running_summary=None,
    )


@action(
    reads=[
        "search_query",
        "research_loop_count",
        "sources_gathered",
        "web_research_results",
    ],
    writes=["sources_gathered", "research_loop_count", "web_research_results"],
)
def web_research(state: State) -> State:
    """
    Performs web research based on the search query and updates the state.

    Args:
        state (State): The current application state.

    Returns:
        State: The updated state with gathered sources, research loop count, and web research results.
    """
    search_results = utils.tavily_search(
        state["search_query"], include_raw_content=True, max_results=1
    )
    search_str = utils.deduplicate_and_format_sources(
        search_results, max_tokens_per_source=1000, include_raw_content=True
    )
    sources_gathered = [utils.format_sources(search_results)]
    sources_gathered = state["sources_gathered"] + sources_gathered
    web_research_results = state["web_research_results"] + [search_str]
    research_loop_count = state["research_loop_count"] + 1

    return state.update(
        sources_gathered=sources_gathered,
        research_loop_count=research_loop_count,
        web_research_results=web_research_results,
    )


@action(
    reads=["running_summary", "web_research_results", "research_topic"],
    writes=["running_summary"],
)
def summarize_sources(state: State):
    """
    Summarizes the gathered sources and updates the running summary.

    Args:
        state (State): The current application state.

    Returns:
        State: The updated state with the new running summary.
    """
    existing_summary = state["running_summary"]
    most_recent_web_research = state["web_research_results"][-1]
    research_topic = state["research_topic"]

    if existing_summary:
        human_message_content = (
            f"<User Input> \n {research_topic} \n <User Input>\n\n"
            f"<Existing Summary> \n {existing_summary} \n <Existing Summary>\n\n"
            f"<New Search Results> \n {most_recent_web_research} \n <New Search Results>"
        )
    else:
        human_message_content = (
            f"<User Input> \n {research_topic} \n <User Input>\n\n"
            f"<Search Results> \n {most_recent_web_research} \n <Search Results>"
        )
    running_summary = query_openai(prompts.summarizer_instructions, human_message_content)

    while "<think>" in running_summary and "</think>" in running_summary:
        start = running_summary.find("<think>")
        end = running_summary.find("</think>") + len("</think>")
        running_summary = running_summary[:start] + running_summary[end:]
    return state.update(running_summary=running_summary)


@action(reads=["running_summary", "research_topic"], writes=["search_query"])
def reflect_on_summary(state: State):
    """
    Reflects on the running summary to identify knowledge gaps and generate a follow-up query.

    Args:
        state (State): The current application state.

    Returns:
        State: The updated state with the follow-up search query.
    """
    system_instructions = prompts.reflection_instructions.format(
        research_topic=state.get("research_topic")
    )
    human_message_content = f"Identify a knowledge gap and generate a follow-up web search query based on our existing knowledge: {state.get('running_summary')}"
    content = query_openai(system_instructions, human_message_content)
    follow_up_query = json.loads(content)

    query = follow_up_query.get("follow_up_query")
    if not query:
        fallback_query = f"Tell me more about {state.get('research_topic')}"
        state.update(search_query=fallback_query)
    return state.update(search_query=query or fallback_query)


@action(
    reads=["running_summary", "sources_gathered"],
    writes=["running_summary", "research_loop_count"],
)
def finalize_summary(state: State):
    """
    Finalizes the summary by combining the running summary and all gathered sources.

    Args:
        state (State): The current application state.

    Returns:
        State: The updated state with the finalized summary.
    """
    all_sources = "\n".join(source for source in state.get("sources_gathered"))
    running_summary = (
        f"## Summary\n\n{state.get('running_summary')}\n\n ### Sources:\n{all_sources}"
    )
    # reset research loop count
    return state.update(running_summary=running_summary, research_loop_count=0)


graph = (
    GraphBuilder()
    .with_actions(
        generate_query,
        web_research,
        summarize_sources,
        reflect_on_summary,
        finalize_summary,
    )
    .with_transitions(
        ("generate_query", "web_research"),
        ("web_research", "summarize_sources"),
        ("summarize_sources", "reflect_on_summary"),
        ("reflect_on_summary", "finalize_summary", when(research_loop_count=2)),
        (
            "reflect_on_summary",
            "web_research",
            expr("research_loop_count<2"),
        ),
        ("finalize_summary", "generate_query"),
    )
).build()


def application(
    app_id: Optional[str] = None,
    project: str = "demo_deep_researcher",
    username: str = None,
) -> Application:
    """
    Creates and configures an application instance for conducting research.

    Args:
        app_id (Optional[str]): A unique identifier for the application instance. Defaults to None.
        project (str): The project name for tracking. Defaults to "demo_deep_researcher".
        username (Optional[str]): The username associated with the application instance.

    Returns:
        Application: A configured application instance ready to run.
    """
    tracker = LocalTrackingClient(project=project)
    builder = (
        ApplicationBuilder()
        .with_graph(graph)
        .with_tracker("local", project=project)
        .with_identifiers(app_id=app_id, partition_key=username)
        .initialize_from(
            tracker,
            resume_at_next_action=True,
            default_state={"research_loop_count": 0, "running_summary": None},
            default_entrypoint="generate_query",
        )
    )
    return builder.build()


if __name__ == "__main__":
    """
    Entry point for the application. Initializes and runs the research application.
    """
    research_topic = "getting a job in datascience"
    app_id = "1"

    app = application(app_id=app_id)
    app.visualize(
        output_file_path="statemachine",
        include_conditions=True,
        view=False,
        format="png",
    )
    action, state, result = app.run(
        halt_after=["finalize_summary"], inputs={"research_topic": research_topic}
    )
    print(app.state["running_summary"])
