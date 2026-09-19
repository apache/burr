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

"""This module shows example tests for testing actions and agents."""

import pytest
import some_actions

from burr.core import state
from burr.tracking import LocalTrackingClient


def test_example1(result_collector):
    """Example test that uses a custom fixture."""
    result_collector.append("Test result 1")
    result_collector.append("Test result 2")
    assert True


def test_example2(results_bag):
    """Example that uses pytest-harvest results_bag fixture."""
    # the following become columns in the final results
    results_bag.input = "..."
    results_bag.actual = "foo"
    results_bag.expected = "foo bar baz"
    results_bag.cosine = 0.3
    results_bag.jaccard = 0.2
    assert True


def test_example3(module_results_df):
    """Example that shows how to access the module_results_df fixture."""
    # note pytest runs these tests in order - so in practice this
    # would be placed at the end of the test file
    print(module_results_df.columns)


def test_run_hypothesis(results_bag):
    """Tests the run_hypothesis action for a single case"""
    input = "Patient has a limp and is unable to flex right ankle. Ankle is swollen."
    hypothesis = "Common cold"
    expected = "no"
    results_bag.input = input
    results_bag.expected = expected
    results_bag.test_function = "test_run_hypothesis"
    input_state = state.State({"hypothesis": hypothesis, "transcription": input})
    end_state = some_actions.run_hypothesis(input_state)
    results_bag.actual = end_state["diagnosis"]
    results_bag.exact_match = end_state["diagnosis"].lower() == expected
    # results_bag.jaccard = ... # other measures here
    # e.g. LLM as judge if applicable
    # place asserts at end
    assert end_state["diagnosis"] is not None
    assert end_state["diagnosis"] != ""


@pytest.mark.parametrize(
    "input,hypothesis,expected",
    [
        ("Patient exhibits mucus dripping from nostrils and coughing.", "Common cold", "yes"),
        (
            "Patient has a limp and is unable to flex right ankle. Ankle is swollen.",
            "Sprained ankle",
            "yes",
        ),
        (
            "Patient fell off and landed on their right arm. Their right wrist is swollen, "
            "they can still move their fingers, and there is only minor pain or discomfort when the wrist is moved or "
            "touched.",
            "Broken arm",
            "no",
        ),
    ],
    ids=["common_cold", "sprained_ankle", "broken_arm"],
)
def test_run_hypothesis_parameterized(input, hypothesis, expected, results_bag):
    """Example showing how to parameterize this."""
    results_bag.input = input
    results_bag.hypothesis = hypothesis
    results_bag.expected = expected
    results_bag.test_function = "test_run_hypothesis_parameterized"
    input_state = state.State({"hypothesis": hypothesis, "transcription": input})
    end_state = some_actions.run_hypothesis(input_state)
    results_bag.actual = end_state["diagnosis"]
    results_bag.exact_match = end_state["diagnosis"].lower() == expected
    # results_bag.jaccard = ... # other measures here
    # e.g. LLM as judge if applicable
    # place asserts at end
    assert end_state["diagnosis"] is not None
    assert end_state["diagnosis"] != ""


# the following is required to run file based parameterized tests
from burr.testing import pytest_generate_tests  # noqa: F401


@pytest.mark.file_name(
    "hypotheses_test_cases.json"
)  # our fixture file with the expected inputs and outputs
def test_run_hypothesis_burr_fixture(input_state, expected_state, results_bag):
    """This example shows how to scale parameterized with a file of inputs and expected outputs using Burr's."""
    input_state = state.State.deserialize(input_state)
    expected_state = state.State.deserialize(expected_state)
    results_bag.input = input_state["transcription"]
    results_bag.hypothesis = input_state["hypothesis"]
    results_bag.expected = expected_state["diagnosis"]
    results_bag.test_function = "test_run_hypothesis_parameterized"
    input_state = state.State(
        {"hypothesis": input_state["hypothesis"], "transcription": input_state["transcription"]}
    )
    end_state = some_actions.run_hypothesis(input_state)
    results_bag.actual = end_state["diagnosis"]
    results_bag.exact_match = end_state["diagnosis"].lower() == expected_state["diagnosis"]
    print(results_bag)
    # results_bag.jaccard = ... # other measures here
    # e.g. LLM as judge if applicable
    # place asserts at end
    assert end_state["diagnosis"] is not None
    assert end_state["diagnosis"] != ""


@pytest.mark.file_name(
    "e2e_test_cases.json"
)  # our fixture file with the expected inputs and outputs
def test_run_hypothesis_burr_fixture_e2e_with_tracker(input_state, expected_state, results_bag):
    """This example shows a parameterized example of running the agent end-to-end with a tracker."""
    from opentelemetry.instrumentation.openai import OpenAIInstrumentor

    # this will auto instrument the openAI client. No swapping of imports required!
    OpenAIInstrumentor().instrument()
    tracker = LocalTrackingClient(project="pytest-example")
    graph = some_actions.build_graph()
    input_state = state.State.deserialize(input_state)
    app = some_actions.build_application(
        app_id=None,
        graph=graph,
        initial_state=input_state,
        initial_entrypoint="transcribe_audio",
        partition_key="pytest_example",
        tracker=tracker,
        use_otel_tracing=True,
    )
    expected_state = state.State.deserialize(expected_state)
    results_bag.input = input_state["audio"]
    results_bag.expected = expected_state["final_diagnosis"]
    results_bag.test_function = "test_run_hypothesis_burr_fixture_e2e_with_tracker"
    last_action, _, agent_state = app.run(
        halt_after=["determine_diagnosis"],
    )

    results_bag.actual = agent_state["final_diagnosis"]
    results_bag.exact_match = (
        agent_state["final_diagnosis"].lower() == expected_state["final_diagnosis"].lower()
    )
    print(results_bag)
    # results_bag.jaccard = ... # other measures here
    # e.g. LLM as judge if applicable
    # place asserts at end
    assert agent_state["final_diagnosis"] is not None
    assert agent_state["final_diagnosis"] != ""


def test_print_results(module_results_df, git_info):
    """This is an example using pytest-harvest and our custom git fixture to return results to a central location.
    You could use other plugins, or create your own fixtures (e.g. see conftest.py for a simpler custom fixture).
    """
    module_results_df["git_commit"] = git_info["commit"]
    module_results_df["git_branch"] = git_info["branch"]
    print(module_results_df.columns)
    print(module_results_df.head())
    # compute statistics
    # this is where you could use pandas to compute statistics like accuracy, etc.
    tests_of_interest = module_results_df[
        module_results_df["test_function"].fillna("").str.startswith("test_run_hypothesis")
    ]
    accuracy = sum(tests_of_interest["exact_match"]) / len(tests_of_interest)
    # save to CSV
    tests_of_interest[
        [
            "test_function",
            "git_branch",
            "git_commit",
            "duration_ms",
            "status",
            "input",
            "hypothesis",
            "expected",
            "actual",
            "exact_match",
        ]
    ].to_csv("results.csv", index=True, quoting=1)
    # upload to google sheets or other storage, etc.

    assert accuracy > 0.9  # and then assert on the computed statistics
