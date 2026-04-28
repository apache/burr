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

from pathlib import Path
from typing import Iterable, Literal

import google.generativeai as genai
import instructor
import lancedb
from dotenv import load_dotenv
from exa_py.api import Exa
from instructor.exceptions import InstructorRetryException
from lancedb.db import DBConnection
from lancedb.embeddings import get_registry
from lancedb.pydantic import LanceModel, Vector
from lancedb.table import Table
from pydantic import BaseModel, Field

from burr.core import Application, ApplicationBuilder, State, expr, when
from burr.core.action import action
from burr.tracking import LocalTrackingClient

load_dotenv()  # load your GOOGLE_API_KEY and EXA_API_KEY from a .env file


ask_gemini = instructor.from_gemini(
    client=genai.GenerativeModel(model_name="gemini-1.5-flash-latest")
)
exa = Exa(api_key=None)

BURR_DOCS_DIR = Path("burr_docs")
DOC_THRESH = 512
LANCE_URI = "lance/rag"
EMS_MODEL = "BAAI/bge-small-en-v1.5"  # for the embeddings in LanceDB
DEVICE = "cuda"  # or "cpu"
DOCS_LIMIT = 5  # number of documents to retrieve from the database or search engine
ATTEMPTS = 3  # ask_gemini will try to call `create` this many times before giving up


def chat_message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


def system_message(content: str) -> dict[str, str]:
    return chat_message(role="system", content=content)


def user_message(content: str) -> dict[str, str]:
    return chat_message(role="user", content=content)


def assistant_message(content: str) -> dict[str, str]:
    return chat_message(role="assistant", content=content)


def merge_short_docs(
    docs: list[str], file_name: str, doc_thresh: int = DOC_THRESH
) -> list[dict[str, str]]:
    """
    Merge short documents into longer ones for better performance.
    `file_name` is the name of the file the documents came from. It's just for metadata.
    """
    merged_docs = [{"text": docs[0], "file_name": file_name}]
    for doc in docs[1:]:
        last_text = merged_docs[-1]["text"]
        if len(last_text) <= doc_thresh:
            merged_docs[-1]["text"] = last_text.strip() + "\n" + doc
        else:
            merged_docs.append({"text": doc, "file_name": file_name})
    return merged_docs


def load_burr_docs(
    file_names: list[str] | str | None = None,
    burr_docs_dir: Path = BURR_DOCS_DIR,
    doc_thresh: int = DOC_THRESH,
) -> list[dict[str, str]]:
    """
    Load strings from text files in `burr_docs_dir` and merge short documents.
    If `file_names` is None, load all files in the directory.
    """
    if file_names is None:
        files_iter = burr_docs_dir.glob("*.txt")
    elif isinstance(file_names, str):
        files_iter = [file_names]
    else:
        files_iter = file_names
    docs = []
    for file in files_iter:
        docs += merge_short_docs(
            docs=(burr_docs_dir / Path(file).name).with_suffix(".txt").read_text().split("\n\n"),
            file_name=Path(file).stem,
            doc_thresh=doc_thresh,
        )
    return docs


def add_table(
    db: DBConnection,
    table_name: str,
    data: list[dict[str, str]],
    schema: type[LanceModel],
) -> Table:
    """
    Drop the table if it exists, create a new table, add data, and create a Full-Text Search index.
    Semenaitc Search is enabled by default. So creating an FTS index makes the table Hybrid Search ready.
    Learn more about Hybrid Search in LanceDB: https://lancedb.github.io/lancedb/hybrid_search/hybrid_search/
    """
    db.drop_table(name=table_name, ignore_missing=True)  # type: ignore
    table = db.create_table(name=table_name, schema=schema)
    table.add(data=data)
    table.create_fts_index(field_names="text")  # type: ignore
    return table


def route_template(
    table_names: Iterable[str],
    query: str,
    chat_history: list[dict[str, str]] | None = None,
) -> str:
    prompt = """\
<task>
You are a world-class router for user queries.
Given a user query, you may need some extra information for answering the query. So you need to select the best place to find the answer.
You have the following options:
1. You will have some vector database tables with information on specific topics. If the query is directly related to any of these topics, return the relevant table name.
2. If you can answer the query directly with your own knowledge, return "assistant".
3. If you don't have the answer to the query, you can search the internet for the answer. In this case, return "web_search".
</task>

<available_tables>
"""
    prompt += "\n".join(table_names)
    prompt += "\n</available_tables>"
    if chat_history:
        prompt += "\n\n<chat_history>\n"
        prompt += "\n".join(f"{msg['role']}: {msg['content']}" for msg in chat_history)
        prompt += "\n</chat_history>"
    prompt += f"\n\n<query>\n{query}\n</query>"
    return prompt


# used to get a structured response from the assistant when rewriting a query
class LanceDBQuery(BaseModel):
    keywords: list[str] = Field(..., min_length=1, max_length=10)
    query: str = Field(..., min_length=10, max_length=300)

    def __str__(self) -> str:
        return ", ".join(self.keywords) + ", " + self.query


def lancedb_query_template(query: str, chat_history: list[dict[str, str]]) -> str:
    prompt = f"""\
<task>
You are a world-class researcher with access to a vector database that can be one of or similar to ChromaDB, Weaviate, LanceDB, VertexAI, etc.
Given a user query, rewrite the query to find the most relevant information in the vector database.
Remember that the vector database has hybrid search capability, which means it can do both full-text search and vector similarity search.
So make sure to not remove any important keywords from the query. You can even add more keywords if you think they are relevant.
Split the query into a list of keywords and a string query.
</task>

<query>
{query}
</query>
"""

    if chat_history:
        chat_history_str = "\n".join(
            [f"{msg['role']}: {msg['content']}" for msg in chat_history]
        ).strip()
        prompt += f"\n<chat_history>\n{chat_history_str}\n</chat_history>"
    return prompt


# used to get a structured response from the assistant when extracting keywords for a web search
class ExaSearchKeywords(BaseModel):
    keywords: list[str] = Field(..., min_length=2, max_length=5)

    def __str__(self) -> str:
        return ", ".join(self.keywords)


def exa_search_query_template(query: str) -> str:
    return f"""\
<task>
You are a world-class internet researcher.
Given a user query, extract 2-5 keywords as queries for the web search. Including the topic background and main intent.
</task>

<examples>

<query>
What is Henry Feilden’s occupation?
</query>
<keywords>
Henry Feilden, occupation
</keywords>

<query>
In what city was Billy Carlson born?
</query>
<keywords>
city, Billy Carlson, born
</keywords>

<query>
What is the religion of John Gwynn?
</query>
<keywords>
religion, John Gwynn
</keywords>

<query>
What sport does Kiribati men’s national basketball team play?
</query>
<keywords>
sport, Kiribati men’s national basketball team play
</keywords>

</examples>

<query>
{query}
</query>
"""


def evaluator_template(query: str, document: str) -> str:
    return f"""\
<task>
You are a world-class document relevance evaluator.
Given a user query, does the following document have the exact information to answer the question? Answer True or False.
</task>

<query>
{query}
</query>

<document>
{document}
</document>
"""


def get_user_query() -> str:
    query = ""
    while not query:
        query = input("(exit, quit, q to exit) > ").strip()
    return query


@action(reads=["db", "chat_history"], writes=["query", "route"])
def router(state: State, query: str, attempts: int = ATTEMPTS) -> tuple[dict[str, str], State]:
    """
    Route the user `query` to the appropriate place for an answer.
    If the `query` is directly related to a table in the database, return the table name.
    If a web search is needed, return "web_search".
    If the `query` can be directly answered by the assistant, return "assistant".
    If the `query` contains "exit", "quit", or "q", return "terminate".
    If there is a `chat_history`, it will also be used as context for the routing.
    If it fails to route after `attempts`, it will return "assistant".
    We use `Instructor` to ensure that the router only returns valid routes.
    """
    if query.lower() in ["exit", "quit", "q"]:
        route = "terminate"
        return {"route": route}, state.update(query=query, route=route)
    db: DBConnection = state["db"]
    table_names = db.table_names()
    chat_history = state["chat_history"]
    # using this as a `response_model` to ensure the route is valid
    routes = Literal.__getitem__((*table_names, "web_search", "assistant"))  # type: ignore
    try:
        route = ask_gemini.create(
            messages=[
                user_message(
                    route_template(table_names=table_names, query=query, chat_history=chat_history)
                )  # type: ignore
            ],
            response_model=routes,  # type: ignore
            max_retries=attempts,
        )
    except Exception as e:
        print(f"Error in router: {e}")
        route = "assistant"
    return {"route": route}, state.update(query=query, route=route)  # type: ignore


@action(reads=["query", "chat_history"], writes=["lancedb_query"])
def rewrite_query_for_lancedb(
    state: State, rewrite_attempts: int = ATTEMPTS
) -> tuple[dict[str, str], State]:
    """
    Rewrite the user `query` to find the most relevant information in the LanceDB vector database.
    """
    query = state["query"]
    chat_history = state["chat_history"]
    try:
        query = str(
            ask_gemini.create(
                messages=[
                    user_message(
                        lancedb_query_template(query=query, chat_history=chat_history)  # type: ignore
                    )
                ],
                response_model=LanceDBQuery,
                max_retries=rewrite_attempts,
            )
        )
    except Exception as e:
        print(f"Error in rewrite_query_for_lancedb: {e}")
    return {"lancedb_query": query}, state.update(lancedb_query=query)


@action(reads=["db", "route", "lancedb_query", "docs_limit"], writes=["lancedb_results"])
def search_lancedb(state: State) -> tuple[dict[str, list[str]], State]:
    db: DBConnection = state["db"]
    try:
        lancedb_results = (
            db.open_table(name=state["route"])
            .search(query=state["lancedb_query"], query_type="hybrid")
            .limit(limit=state["docs_limit"])
            .to_pandas()["text"]
            .tolist()
        )
    except Exception as e:
        print(f"Error in search_lancedb: {e}")
        lancedb_results = []
    return {"lancedb_results": lancedb_results}, state.update(lancedb_results=lancedb_results)


@action(reads=["query", "lancedb_results"], writes=["lancedb_results"])
def remove_irrelevant_lancedb_results(
    state: State,
) -> tuple[dict[str, list[str]], State]:
    """
    Ask the assistant to evaluate the relevance of each retrieved document with the user `query`.
    If the assistant thinks the document is relevant, keep it in the `lancedb_results`.
    """
    lancedb_results = state["lancedb_results"]
    if not lancedb_results:
        return {"lancedb_results": lancedb_results}, state
    filtered_results = []
    for lancedb_result in lancedb_results:
        try:
            is_relevant = ask_gemini.create(
                messages=[
                    user_message(
                        evaluator_template(query=state["query"], document=lancedb_result)
                    )  # type: ignore
                ],
                response_model=bool,  # type: ignore
                max_retries=ATTEMPTS,
            )
        except Exception as e:
            print(f"Error in remove_irrelevant_lancedb_results: {e}")
            is_relevant = True
        if is_relevant:
            filtered_results.append(lancedb_result)
    return {"lancedb_results": filtered_results}, state.update(lancedb_results=filtered_results)


@action(reads=["query"], writes=["exa_search_keywords"])
def extract_keywords_for_exa_search(
    state: State, extraction_attempts: int = ATTEMPTS
) -> tuple[dict[str, str], State]:
    """
    Extract 2-5 keywords from the user `query` for a web search.
    These keywords will be used to search the internet for the answer. Instead of the full query.
    """
    query = state["query"]
    try:
        query = str(
            ask_gemini.create(
                messages=[user_message(exa_search_query_template(query=query))],  # type: ignore
                response_model=ExaSearchKeywords,
                max_retries=extraction_attempts,
            )
        )
    except Exception as e:
        print(f"Error in extract_keywords_for_web_search: {e}")
    return {"exa_search_keywords": query}, state.update(exa_search_keywords=query)


@action(reads=["exa_search_keywords", "docs_limit"], writes=["exa_search_results"])
def search_exa(state: State) -> tuple[dict[str, list[str]], State]:
    """
    More details about the Exa API:
        - https://docs.exa.ai/reference/getting-started
        - https://github.com/exa-labs/exa-py
    """
    try:
        exa_search_results = exa.search_and_contents(
            query=state["exa_search_keywords"],
            num_results=state["docs_limit"],
            highlights=True,
        )
        exa_search_results = [res.highlights[0] for res in exa_search_results.results]
    except Exception as e:
        print(f"Error in search_exa: {e}")
        exa_search_results = []
    return {"exa_search_results": exa_search_results}, state.update(
        exa_search_results=exa_search_results
    )


@action(
    reads=["query", "lancedb_results", "exa_search_results", "chat_history"],
    writes=["chat_history", "lancedb_results", "exa_search_results"],
)
def ask_assistant(state: State, attempts: int = ATTEMPTS) -> tuple[dict[str, str], State]:
    """
    Combine the `chat_history`, `query`, `lancedb_results`, and `exa_search_results` to ask the assistant for an answer.
    `chat_history`, `lancedb_results`, and `exa_search_results` are used as context for the assistant and can be empty lists.
    """
    query = state["query"]
    lancedb_results = state.get("lancedb_results", [])
    exa_search_results = state.get("exa_search_results", [])
    messages = state["chat_history"]
    context = lancedb_results + exa_search_results
    if context:
        context = "\n".join(context)
        query = query.strip() + "\n<additional_context>\n" + context + "\n</additional_context>"
    messages.append({"role": "user", "content": query.strip()})
    try:
        response = ask_gemini.create(messages=messages, response_model=str, max_retries=attempts)
    except InstructorRetryException as e:
        print(f"Error in ask_assistant: {e}")
        response = "Sorry, please try again."
    # lancedb_results and exa_search_results have very specific additional context that's relevant only for the latest query
    # that specific context is no longer needed after the assistant responds, so we clear it
    # the assistant will still have the chat_history as overall context
    # chat_history has the user messages and the assistant responses, so it's more than enough
    return (
        {"assistant_response": response},  # type: ignore
        state.append(chat_history=user_message(query))
        .append(chat_history=assistant_message(response))  # type: ignore
        .update(lancedb_results=[], exa_search_results=[]),
    )


@action(reads=["chat_history"], writes=[])
def terminate(state: State) -> tuple[dict[str, list[dict[str, str]]], State]:
    return {"chat_history": state["chat_history"]}, state


def application(
    db: DBConnection,
    app_id: str | None = None,
    username: str | None = None,
    project: str = "AdaptiveCRAG",
) -> Application:
    tracker = LocalTrackingClient(project=project)
    builder = (
        ApplicationBuilder()
        .with_actions(
            router.bind(attempts=ATTEMPTS),
            rewrite_query_for_lancedb.bind(rewrite_attempts=ATTEMPTS),
            search_lancedb,
            remove_irrelevant_lancedb_results,
            extract_keywords_for_exa_search.bind(extraction_attempts=ATTEMPTS),
            search_exa,
            ask_assistant.bind(attempts=ATTEMPTS),
            terminate,
        )
        .with_transitions(
            # if the user wants to exit the conversation
            ("router", "terminate", when(route="terminate")),  # type: ignore
            # if the `query` can be directly answered by the assistant
            ("router", "ask_assistant", when(route="assistant")),  # type: ignore
            # if a web search is needed
            ("router", "extract_keywords_for_exa_search", when(route="web_search")),  # type: ignore
            # the database can have multiple tables for different topics
            # so it makes sense to have `when` conditions for all other routes and consider this as the default route
            # otherwise we would have to add a `when` condition for each table name
            ("router", "rewrite_query_for_lancedb"),
            ("rewrite_query_for_lancedb", "search_lancedb"),
            ("search_lancedb", "remove_irrelevant_lancedb_results"),
            # if there aren't enough relevant documents left after filtering
            # use web search to find more information
            (
                "remove_irrelevant_lancedb_results",
                "extract_keywords_for_exa_search",
                expr("len(lancedb_results) < docs_limit"),  # type: ignore
            ),
            # if there are enough relevant documents even after filtering, ask the assistant for an answer
            ("remove_irrelevant_lancedb_results", "ask_assistant"),
            ("extract_keywords_for_exa_search", "search_exa"),
            ("search_exa", "ask_assistant"),
            # go back to the router every time the assistant is done answering
            ("ask_assistant", "router"),
        )
        .with_tracker("local", project=project)
        .with_identifiers(app_id=app_id, partition_key=username)  # type: ignore
        .initialize_from(
            tracker,
            resume_at_next_action=True,
            default_entrypoint="router",
            default_state=dict(db=db, chat_history=[], docs_limit=DOCS_LIMIT),
        )
    )
    return builder.build()


if __name__ == "__main__":
    lance_model = get_registry().get("sentence-transformers").create(name=EMS_MODEL, device=DEVICE)

    # define the schema of your data using Pydantic
    class LanceDoc(LanceModel):
        text: str = lance_model.SourceField()
        vector: Vector(dim=lance_model.ndims()) = lance_model.VectorField()  # type: ignore
        file_name: str

    lance_db = lancedb.connect(LANCE_URI)

    burr_docs = load_burr_docs(burr_docs_dir=BURR_DOCS_DIR)
    burr_table = add_table(db=lance_db, table_name="burr_docs", data=burr_docs, schema=LanceDoc)

    app = application(db=lance_db)
    app.visualize(
        output_file_path="statemachine",
        include_conditions=True,
        include_state=False,
        format="png",
    )
