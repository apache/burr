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

"""Tests for the coding agent example.

The agent is driven by a `ScriptedClient`, so the whole state machine -- tool
dispatch, error recovery and the step budget -- is exercised without an API key.
"""

import json

import pytest
import tools
from application import ScriptedClient, application


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    """Points the tools at an isolated directory for each test.

    ``tools.WORKSPACE`` is read when a tool is called, so patching the module
    attribute is enough -- tests never touch the real ``./workspace``.
    """
    monkeypatch.setattr(tools, "WORKSPACE", str(tmp_path))
    return tmp_path


def run(task: str, script: list[dict], max_steps: int = 15, tmp_path=None):
    """Runs the agent with a fixed script and returns the final state."""
    client = ScriptedClient(script)
    app = application(max_steps=max_steps, client=client)
    _, _, state = app.run(halt_after=["respond"], inputs={"task": task})
    return state


def tool_result(state: dict, index: int = -1) -> dict:
    """Returns the JSON payload of the `index`-th tool message in the history."""
    tool_messages = [m for m in state["messages"] if m["role"] == "tool"]
    return json.loads(tool_messages[index]["content"])


def test_happy_path_runs_to_completion(tmp_path, monkeypatch):
    """A scripted run calls tools, then stops when the model requests no tool."""
    monkeypatch.chdir(tmp_path)
    script = [
        {
            "content": None,
            "tool_calls": [{"id": "c1", "name": "list_files", "args": {}}],
        },
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "c2",
                    "name": "write_file",
                    "args": {"path": "hello.py", "contents": "print('hi')\n"},
                }
            ],
        },
        {"content": "Done.", "tool_calls": []},
    ]
    state = run("write hello.py", script)

    assert state["done"] is True
    assert state["final_answer"] == "Done."
    # three model calls, each counted once
    assert state["steps"] == 3
    assert (tmp_path / "hello.py").read_text() == "print('hi')\n"
    # every tool call got exactly one result message
    assert len([m for m in state["messages"] if m["role"] == "tool"]) == 2


def test_step_budget_terminates_the_run(tmp_path, monkeypatch):
    """The agent stops once `max_steps` is reached instead of looping forever."""
    monkeypatch.chdir(tmp_path)
    # a script that would never terminate on its own
    script = [
        {
            "content": None,
            "tool_calls": [{"id": f"c{i}", "name": "list_files", "args": {}}],
        }
        for i in range(10)
    ]
    state = run("list forever", script, max_steps=3)

    assert state["steps"] == 3
    assert "without finishing" in state["final_answer"]
    assert "3 steps" in state["final_answer"]


def test_unknown_tool_is_reported_back_to_the_model(tmp_path, monkeypatch):
    """An invented tool name becomes an error result and the loop continues."""
    monkeypatch.chdir(tmp_path)
    script = [
        {
            "content": None,
            "tool_calls": [{"id": "c1", "name": "delete_everything", "args": {}}],
        },
        {"content": "Recovered.", "tool_calls": []},
    ]
    state = run("do something", script)

    assert state["done"] is True
    assert state["final_answer"] == "Recovered."
    assert "unknown tool" in tool_result(state)["error"]
    # the failed call did not abort the run
    assert state["steps"] == 2


def test_malformed_tool_arguments_do_not_crash_the_run(tmp_path, monkeypatch):
    """Arguments that failed to parse surface as an error the model can react to."""
    monkeypatch.chdir(tmp_path)
    script = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "write_file",
                    "args": {},
                    "error": "could not parse tool arguments as JSON",
                }
            ],
        },
        {"content": "Fixed.", "tool_calls": []},
    ]
    state = run("write a file", script)

    assert state["done"] is True
    assert "could not parse" in tool_result(state)["error"]


def test_tool_failure_is_reported_back_to_the_model(tmp_path, monkeypatch):
    """A tool that raises returns an error result rather than killing the run."""
    monkeypatch.chdir(tmp_path)
    script = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "read_file",
                    "args": {"path": "does-not-exist.txt"},
                }
            ],
        },
        {"content": "That file is missing.", "tool_calls": []},
    ]
    state = run("read a file", script)

    assert state["done"] is True
    assert state["final_answer"] == "That file is missing."
    assert "error" in tool_result(state)


@pytest.mark.parametrize(
    "path",
    ["../outside.txt", "sub/../../outside.txt", "/etc/passwd"],
)
def test_reads_are_confined_to_the_workspace(tmp_path, monkeypatch, path):
    """Paths that escape the project directory are refused."""
    monkeypatch.chdir(tmp_path)
    script = [
        {
            "content": None,
            "tool_calls": [{"id": "c1", "name": "read_file", "args": {"path": path}}],
        },
        {"content": "Stopped.", "tool_calls": []},
    ]
    state = run("read outside", script)

    result = tool_result(state)
    assert "error" in result
    assert (
        "outside" in result["error"].lower() or "workspace" in result["error"].lower()
    )


def test_writes_are_confined_to_the_workspace(tmp_path, monkeypatch):
    """A write aimed outside the project directory is refused, and lands nowhere."""
    monkeypatch.chdir(tmp_path)
    script = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "write_file",
                    "args": {"path": "../escaped.txt", "contents": "nope"},
                }
            ],
        },
        {"content": "Stopped.", "tool_calls": []},
    ]
    state = run("write outside", script)

    assert "error" in tool_result(state)
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_tool_results_are_fed_back_to_the_model(tmp_path, monkeypatch):
    """The scripted client sees each tool result before deciding what to do next."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data.txt").write_text("hello")
    seen = []

    class RecordingClient:
        def __init__(self):
            self.index = 0

        def __call__(self, messages):
            seen.append([m["role"] for m in messages])
            self.index += 1
            if self.index == 1:
                return {
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "name": "read_file", "args": {"path": "data.txt"}}
                    ],
                }
            return {"content": "Read it.", "tool_calls": []}

    app = application(client=RecordingClient())
    _, _, state = app.run(halt_after=["respond"], inputs={"task": "read data.txt"})

    assert state["final_answer"] == "Read it."
    # the second model call must include the tool result from the first
    assert "tool" in seen[1]
    assert tool_result(state)["contents"] == "hello"
