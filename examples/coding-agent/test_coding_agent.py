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

"""Tests for the coding agent harness.

Everything here runs against ScriptedClient, so no API key is needed and the
suite is safe to run in CI.
"""

import json
import os

import pytest
import tools
from application import ScriptedClient, application


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    """Point the tools at a throwaway directory for each test."""
    monkeypatch.setattr(tools, "WORKSPACE", str(tmp_path))
    return tmp_path


def run(script, task="do the thing", **kwargs):
    """Run the agent against a fixed script and return the final state."""
    app = application(client=ScriptedClient(script), **kwargs)
    _, _, state = app.run(halt_after=["respond"], inputs={"task": task})
    return state


def tool_messages(state):
    return [m for m in state["messages"] if m["role"] == "tool"]


# --- the happy path --------------------------------------------------------


def test_scripted_run_completes(workspace):
    state = run(
        [
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "write_file",
                        "args": {"path": "hello.py", "contents": "print('hi')\n"},
                    }
                ],
            },
            {"content": "Wrote hello.py.", "tool_calls": []},
        ]
    )
    assert state["final_answer"] == "Wrote hello.py."
    assert state["done"] is True
    assert (workspace / "hello.py").read_text() == "print('hi')\n"


def test_create_prompt_runs_before_every_call():
    """The prompt seam must run on each turn, not only the first."""
    seen = []
    app = application(
        client=ScriptedClient(
            [
                {
                    "content": None,
                    "tool_calls": [{"id": "c1", "name": "list_files", "args": {}}],
                },
                {"content": "done", "tool_calls": []},
            ]
        )
    )
    for action, _, _ in app.iterate(halt_after=["respond"], inputs={"task": "t"}):
        seen.append(action.name)
    assert seen.count("create_prompt") == 2, seen


# --- termination -----------------------------------------------------------


def test_step_budget_terminates_the_loop():
    """An agent that never finishes stops at max_steps."""
    forever = [
        {"content": None, "tool_calls": [{"id": f"c{i}", "name": "list_files", "args": {}}]}
        for i in range(20)
    ]
    state = run(forever, max_steps=4)
    assert state["steps"] >= 4
    assert "Stopped after" in state["final_answer"]


# --- recovery --------------------------------------------------------------


def test_unknown_tool_is_reported_back_to_the_model():
    state = run(
        [
            {"content": None, "tool_calls": [{"id": "c1", "name": "nope", "args": {}}]},
            {"content": "Picked a real tool.", "tool_calls": []},
        ]
    )
    assert state["final_answer"] == "Picked a real tool."
    errors = [json.loads(m["content"]) for m in tool_messages(state)]
    assert any("unknown tool" in e.get("error", "") for e in errors)


def test_bad_argument_names_do_not_crash_the_run():
    state = run(
        [
            {
                "content": None,
                "tool_calls": [{"id": "c1", "name": "read_file", "args": {"filename": "x.txt"}}],
            },
            {"content": "Recovered.", "tool_calls": []},
        ]
    )
    assert state["final_answer"] == "Recovered."
    errors = [json.loads(m["content"]) for m in tool_messages(state)]
    assert any("bad arguments" in e.get("error", "") for e in errors)


def test_tool_failure_is_returned_not_raised():
    state = run(
        [
            {
                "content": None,
                "tool_calls": [{"id": "c1", "name": "read_file", "args": {"path": "missing.txt"}}],
            },
            {"content": "Handled the missing file.", "tool_calls": []},
        ]
    )
    assert state["final_answer"] == "Handled the missing file."
    errors = [json.loads(m["content"]) for m in tool_messages(state)]
    assert any("error" in e for e in errors)


# --- workspace confinement -------------------------------------------------


def test_read_outside_the_workspace_is_refused():
    assert "error" in tools.read_file("../../../etc/passwd")


def test_write_outside_the_workspace_is_refused():
    assert "error" in tools.write_file("../escaped.txt", "nope")


def test_symlink_out_of_the_workspace_is_refused(workspace, tmp_path):
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("classified")
    os.symlink(secret, workspace / "link.txt")
    assert "error" in tools.read_file("link.txt")


def test_run_bash_works_before_anything_is_written(workspace):
    """The workspace must exist even if no tool has written to it yet."""
    result = tools.run_bash("pwd")
    assert result["exit_code"] == 0
