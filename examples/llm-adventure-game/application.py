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

import json
from typing import Optional, Tuple

from openai import Client

import burr.core
from burr.core import Application, State, default, when
from burr.core.action import action

RESTRICTIONS = """You're a small corgi with short legs. You can't jump high,
 you can't run fast, you can't perform feats of athleticism in general
 to achieve any of your goals. You can't open doors, you can't use tools,
 you can't communicate with humans, you can't use your paws to manipulate
 objects, you can't use your mouth to manipulate objects, you can't use
 your mouth to communicate with humans"""


challenges = [
    "There is a dish of dog food on the floor. You want to eat it",
    "There is a dish of dog food on a table. You want to eat it",
    "There is a dish of dog food in a locked car. You want to eat it",
]


@action(reads=[], writes=["current_challenge"])
def start(state: State) -> Tuple[dict, State]:
    result = {"current_challenge": challenges[0]}
    return result, state.update(**result)


@action(reads=["current_challenge"], writes=["attempts"])
def prompt_for_challenge(state: State) -> Tuple[dict, State]:
    response = input(f'{state["current_challenge"]}. What do you do?\n $ ')
    result = {"attempt": response}
    return result, state.append(attempts=result["attempt"])


@action(
    reads=["attempts", "current_challenge"],
    writes=["challenge_solved", "what_happened"],
)
def evaluate_attempt(state: State) -> Tuple[dict, State]:
    result = Client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": f"""You are evaluating responses for
             whether they constitute solutions to the provided challenge in a text
             based game, whose protagonist is a dog subject to the following limitations:
             {RESTRICTIONS}. You respond ONLY with a json object containing two fields: "solved", which is a
             boolean indicating whether the challenge was solved by the attempt, and "what_happened",
             which is a string containing a brief narrative, written in the second person and addressed
             to the player, of what happened during the protagonist's attempt""",
            },
            {
                "role": "user",
                "content": f"The current challenge is: {state['current_challenge']} "
                f"and the player's attempt is: {state['attempts'][-1]}",
            },
        ],
    )
    content = result.choices[0].message.content
    try:
        json_result = json.loads(content)
    except json.JSONDecodeError:
        print("bad json: ", content)
        json_result = {
            "solved": False,
            "what_happened": "Not sure, really. I'm a dog. I can't read json. I can't read at all.",
        }

    result = {"challenge_solved": json_result["solved"], "txt_result": content}

    return result, state.update(
        challenge_solved=result["challenge_solved"],
        what_happened=json_result["what_happened"],
    )


@action(
    reads=["challenge_solved", "current_challenge", "what_happened"],
    writes=["current_challenge", "did_win"],
)
def maybe_progress(state: State) -> Tuple[dict, State]:
    print("What happened:", state["what_happened"])
    if state["challenge_solved"]:
        if state["current_challenge"] == challenges[-1]:
            result = {"did_win": True}
        else:
            result = {
                "current_challenge": challenges[challenges.index(state["current_challenge"]) + 1]
            }
    else:
        result = {"current_challenge": state["current_challenge"]}
    return result, state.update(**result)


@action(reads=[], writes=[])
def win(state: State) -> Tuple[dict, State]:
    # get summary of actions taken from openai
    print("you won")
    return {}, state


def application(
    app_id: Optional[str] = None,
    storage_dir: Optional[str] = "~/.burr",
) -> Application:
    return (
        burr.core.ApplicationBuilder()
        .with_state(did_win=False)
        .with_actions(
            start=start,
            prompt_for_challenge=prompt_for_challenge,
            evaluate_attempt=evaluate_attempt,
            maybe_progress=maybe_progress,
            win=win,
        )
        .with_transitions(
            ("start", "prompt_for_challenge", default),
            ("prompt_for_challenge", "evaluate_attempt", default),
            ("evaluate_attempt", "maybe_progress", default),
            ("maybe_progress", "win", when(did_win=True)),
            ("maybe_progress", "prompt_for_challenge", default),
        )
        .with_entrypoint("start")
        .with_tracker(project="demo_corgi_adventure", params={"storage_dir": storage_dir})
        .with_identifiers(app_id=app_id)
        .build()
    )


if __name__ == "__main__":
    app = application()
    app.visualize(output_file_path="digraph", include_conditions=True, view=False, format="png")
    action, state, result = app.run(halt_after=["win"])
