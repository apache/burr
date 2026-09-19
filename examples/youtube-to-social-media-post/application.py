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

import textwrap
from typing import Union

import instructor
import openai
from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema
from youtube_transcript_api import YouTubeTranscriptApi

from burr.core import Application, ApplicationBuilder, State, action
from burr.core.persistence import SQLLitePersister


class Concept(BaseModel):
    term: str = Field(description="A key term or concept mentioned.")
    definition: str = Field(description="A brief definition or explanation of the term.")
    timestamp: float = Field(description="Timestamp when the concept is explained.")

    def display(self):
        minutes, seconds = divmod(self.timestamp, 60)
        return f"{int(minutes)}:{int(seconds)} - {self.term}: {self.definition}"


class SocialMediaPost(BaseModel):
    """A social media post about a YouTube video generated its transcript"""

    topic: str = Field(description="Main topic discussed.")
    hook: str = Field(
        description="Statement to grab the attention of the reader and announce the topic."
    )
    body: str = Field(
        description="The body of the social media post. It should be informative and make the reader curious about viewing the video."
    )
    concepts: list[Concept] = Field(
        description="Important concepts about Hamilton or Burr mentioned in this post.",
        min_items=1,
        max_items=3,
    )
    key_takeaways: list[str] = Field(
        description="A list of informative key takeways for the reader.",
        min_items=1,
        max_items=4,
    )
    youtube_url: SkipJsonSchema[Union[str, None]] = None

    def display(self) -> str:
        formatted_takeways = " ".join([t for t in self.key_takeaways])
        formatted_concepts = "CONCEPTS\n" + "\n".join([c.display() for c in self.concepts])
        link = f"link: {self.youtube_url}\n\n" if self.youtube_url else ""

        return textwrap.dedent(f"""\
            TOPIC: {self.topic}

            {self.hook}

            {self.body}

            {formatted_takeways}

            """) + link + formatted_concepts


@action(reads=[], writes=["transcript"])
def get_youtube_transcript(state: State, youtube_url: str) -> State:
    """Get the official YouTube transcript for a video given it's URL"""
    _, _, video_id = youtube_url.partition("?v=")

    transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
    full_transcript = " ".join([f"ts={entry['start']} - {entry['text']}" for entry in transcript])

    # store the transcript in state
    return state.update(transcript=full_transcript)


@action(reads=["transcript"], writes=["post"])
def generate_post(state: State, llm_client) -> State:
    """Use the Instructor LLM client to generate `SocialMediaPost` from the YouTube transcript."""

    # read the transcript from state
    transcript = state["transcript"]

    response = llm_client.chat.completions.create(
        model="gpt-4o-mini",
        response_model=SocialMediaPost,
        messages=[
            {
                "role": "system",
                "content": "Analyze the given YouTube transcript and generate a compelling social media post.",
            },
            {"role": "user", "content": transcript},
        ],
    )

    # store the chapters in state
    return state.update(post=response)


@action(reads=["post"], writes=["post"])
def rewrite_post(state: State, llm_client, user_prompt: str):
    post = state["post"]

    response = llm_client.chat.completions.create(
        model="gpt-4o-mini",
        response_model=SocialMediaPost,
        messages=[
            {
                "role": "system",
                "content": f"Take the previously generated social media post and modify it according to the following instructions: {user_prompt}",
            },
            {"role": "user", "content": post.model_dump_json()},
        ],
    )

    # pass the youtube_url from the previous post version
    response.youtube_url = post.youtube_url

    return state.update(post=response)


def build_application() -> Application:
    llm_client = instructor.from_openai(openai.OpenAI())
    return (
        ApplicationBuilder()
        .with_actions(
            get_youtube_transcript,
            generate_post.bind(llm_client=llm_client),
            rewrite_post.bind(llm_client=llm_client),
        )
        .with_transitions(
            ("get_youtube_transcript", "generate_post"),
            ("generate_post", "rewrite_post"),
            ("rewrite_post", "rewrite_post"),
        )
        .with_state_persister(SQLLitePersister(db_path=".burr.db", table_name="state"))
        .with_entrypoint("get_youtube_transcript")
        .with_tracker(project="youtube-post")
        .build()
    )


if __name__ == "__main__":
    app = build_application()
    app.visualize(output_file_path="statemachine.png")

    _, _, state = app.run(
        halt_after=["generate_post"],
        inputs={"youtube_url": "https://www.youtube.com/watch?v=hqutVJyd3TI"},
    )
