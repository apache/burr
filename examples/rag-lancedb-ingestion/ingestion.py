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

import re
from typing import Generator

import dlt
import feedparser
import requests
import utils
from bs4 import BeautifulSoup


def split_text(text):
    """Split text on punction (., !, ?)."""
    sentence_endings = r"[.!?]+"
    for sentence in re.split(sentence_endings, text):
        sentence = sentence.strip()
        if sentence:
            yield sentence


def contextualize(chunks: list[str], window=5, stride=3, min_window_size=2):
    """Rolling window operation to join consecutive sentences into larger chunks."""
    n_chunks = len(chunks)
    for start_i in range(0, n_chunks, stride):
        if (start_i + window <= n_chunks) or (n_chunks - start_i >= min_window_size):
            yield " ".join(chunks[start_i : min(start_i + window, n_chunks)])


@dlt.resource(name="substack", write_disposition="merge", primary_key="id")
def rss_entries(substack_url: str) -> Generator:
    """Substack blog entries retrieved from a RSS feed"""
    FIELDS_TO_EXCLUDE = [
        "published_parsed",
        "title_detail",
        "summary_detail",
        "author_detail",
        "guidislink",
        "authors",
        "links",
    ]

    r = requests.get(f"{substack_url}/feed")
    rss_feed = feedparser.parse(r.content)
    for entry in rss_feed["entries"]:
        for field in FIELDS_TO_EXCLUDE:
            entry.pop(field)

        yield entry


@dlt.transformer(primary_key="id")
def parsed_html(rss_entry: dict):
    """Parse the HTML from the RSS entry"""
    soup = BeautifulSoup(rss_entry["content"][0]["value"], "html.parser")
    parsed_text = soup.get_text(separator=" ", strip=True)
    yield {"id": rss_entry["id"], "text": parsed_text}


@dlt.transformer(primary_key="chunk_id")
def chunks(parsed_html: dict) -> list[dict]:
    """Chunk text"""
    return [
        dict(
            document_id=parsed_html["id"],
            chunk_id=idx,
            text=text,
        )
        for idx, text in enumerate(split_text(parsed_html["text"]))
    ]


# order is important for reduce / rolling step
# default to order of the batch or specifying sorting key
@dlt.transformer(primary_key="context_id")
def contexts(chunks: list[dict]) -> Generator:
    """Assemble consecutive chunks into larger context windows"""
    # first handle the m-to-n relationship
    # set of foreign keys (i.e., "chunk_id")
    chunk_id_set = set(chunk["chunk_id"] for chunk in chunks)
    context_id = utils.hash_set(chunk_id_set)

    # create a table only containing the keys
    for chunk_id in chunk_id_set:
        yield dlt.mark.with_table_name(
            {"chunk_id": chunk_id, "context_id": context_id},
            "chunks_to_contexts_keys",
        )

    # main transformation logic
    for contextualized in contextualize([chunk["text"] for chunk in chunks]):
        yield dlt.mark.with_table_name(
            {"context_id": context_id, "text": contextualized}, "contexts"
        )


if __name__ == "__main__":
    import dlt
    from dlt.destinations.adapters import lancedb_adapter

    utils.set_environment_variables()

    pipeline = dlt.pipeline(
        pipeline_name="substack-blog", destination="lancedb", dataset_name="apache_burr"
    )

    blog_url = "https://blog.dagworks.io/"

    full_entries = lancedb_adapter(rss_entries(blog_url), embed="summary")
    chunked_entries = rss_entries(blog_url) | parsed_html | chunks
    contextualized_chunks = lancedb_adapter(chunked_entries | contexts, embed="text")

    load_info = pipeline.run([full_entries, chunked_entries, contextualized_chunks])
    print(load_info)
