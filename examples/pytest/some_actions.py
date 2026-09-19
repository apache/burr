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
This is an example module that defines a Burr application.

It hypothetically transcribes audio and then runs a hypothesis on the transcription to determine a medical diagnosis.
"""

from typing import Any, Callable, Dict, Generator, List, Tuple

import openai

from burr import core
from burr.core import Action, ApplicationContext, GraphBuilder, State, action
from burr.core.parallelism import MapStates, RunnableGraph
from burr.tracking import LocalTrackingClient


@action(reads=["audio"], writes=["transcription"])
def transcribe_audio(state: State) -> State:
    """Action to transcribe audio."""
    # here we fake transcription. For this example the audio is text already...
    return state.update(transcription=state["audio"])


@action(reads=["hypothesis", "transcription"], writes=["diagnosis"])
def run_hypothesis(state: State) -> State:
    """Action to run a hypothesis on a transcription."""
    client = openai.Client()  # here for simplicity because clients and SERDE don't mix well.
    hypothesis = state["hypothesis"]
    transcription = state["transcription"]
    prompt = (
        "Given the following diagnosis hypothesis and medical transcription:\n\n"
        f"Diagnosis hypothesis:{hypothesis}\n\n"
        f"Transcription:\n```{transcription}```\n\n"
        "Answer 'yes' if you believe the hypothesis has a strong reason to hold given the content of the transcription. "
        "Answer 'no' if you do not believe the hypothesis holds given the content of the transcription. "
        "Answer 'unsure' if you are unsure and need more details. "
    )
    response = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "You are a doctor diagnosing illnesses that is methodical"
                " in determining whether a diagnosis hypothesis is supported by a transcription.",
            },
            {"role": "user", "content": prompt},
        ],
        model="gpt-4o-mini",
    )
    return state.update(diagnosis=response.choices[0].message.content)


class TestMultipleHypotheses(MapStates):
    """Parallel action to test multiple hypotheses."""

    def action(self, state: State, inputs: Dict[str, Any]) -> Action | Callable | RunnableGraph:
        """which action to run for each state."""
        return run_hypothesis

    def states(
        self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
    ) -> Generator[State, None, None]:
        """Generate the states to run the action on.
        You could easily have a list_hypotheses upstream action that writes to "hypothesis" in state
        And loop through those
        This hardcodes for simplicity
        """
        for hypothesis in [
            "Common cold",
            "Sprained ankle",
            "Broken arm",
        ]:
            yield state.update(hypothesis=hypothesis)

    def reduce(self, state: State, states: Generator[State, None, None]) -> State:
        """Combine the outputs of the parallel action."""
        all_diagnoses_outputs = []
        for _sub_state in states:
            all_diagnoses_outputs.append(
                {"hypothesis": _sub_state["hypothesis"], "diagnosis": _sub_state["diagnosis"]}
            )
        return state.update(diagnosis_outputs=all_diagnoses_outputs)

    @property
    def reads(self) -> List[str]:
        return ["transcription"]

    @property
    def writes(self) -> List[str]:
        return ["diagnosis_outputs"]


@action(reads=["diagnosis_outputs"], writes=["final_diagnosis"])
def determine_diagnosis(state: State) -> State:
    """Action to determine the final diagnosis."""
    # could also get an LLM to decide here, or have a human decide, etc.
    possible_hypotheses = [d for d in state["diagnosis_outputs"] if d["diagnosis"].lower() == "yes"]
    if len(possible_hypotheses) == 1:
        return state.update(final_diagnosis=possible_hypotheses[0]["hypothesis"])
    elif len(possible_hypotheses) > 1:
        return state.update(
            final_diagnosis="Need further clarification. Multiple diagnoses possible."
        )
    else:
        return state.update(final_diagnosis="Healthy individual")


def build_graph() -> core.Graph:
    """Builds the graph for the application"""
    graph = (
        GraphBuilder()
        .with_actions(
            transcribe_audio=transcribe_audio,
            hypotheses=TestMultipleHypotheses(),
            determine_diagnosis=determine_diagnosis,
        )
        .with_transitions(
            ("transcribe_audio", "hypotheses"),
            ("hypotheses", "determine_diagnosis"),
        )
        .build()
    )
    return graph


def build_application(
    app_id,
    graph,
    initial_state,
    initial_entrypoint,
    partition_key,
    tracker,
    use_otel_tracing: bool = False,
) -> core.Application:
    """Builds an application with the given parameters.

    :param app_id:
    :param graph:
    :param initial_state:
    :param initial_entrypoint:
    :param partition_key:
    :param tracker:
    :param use_otel_tracing:
    :return:
    """
    app_builder = (
        core.ApplicationBuilder()
        .with_graph(graph)
        .with_state(**initial_state)
        .with_entrypoint(initial_entrypoint)
        .with_identifiers(partition_key=partition_key, app_id=app_id)
    )
    if tracker:
        app_builder = app_builder.with_tracker(tracker, use_otel_tracing=use_otel_tracing)
    app = app_builder.build()
    return app


def run_my_agent(
    input_audio: str, partition_key: str = None, app_id: str = None, tracking_project: str = None
) -> Tuple[str, str]:
    """Runs the agent with the given input audio (in this case a string transcription...).
    :param input_audio: we fake it here, and ask for a string...
    :param partition_key:
    :param app_id:
    :param tracking_project:
    :return:
    """
    graph = build_graph()
    tracker = None
    if tracking_project:
        tracker = LocalTrackingClient(project=tracking_project)
    # we fake the input audio to be a string here rather than a waveform.
    app = build_application(
        app_id, graph, {"audio": input_audio}, "transcribe_audio", partition_key, tracker=tracker
    )
    # app.visualize("diagnosis.png", include_conditions=True, view=False, format="png")
    last_action, _, agent_state = app.run(
        halt_after=["determine_diagnosis"],
        inputs={"audio": input_audio},
    )
    return input_audio, agent_state["final_diagnosis"]


if __name__ == "__main__":
    print(run_my_agent("Patient exhibits mucus dripping from nostrils and coughing."))
    print(run_my_agent("Patient has a limp and is unable to flex right ankle. Ankle is swollen."))
    print(
        run_my_agent(
            "Patient fell off and landed on their right arm. Their right wrist is swollen, they can still move their "
            "fingers, and there is only minor pain or discomfort when the wrist is moved or touched."
        )
    )
