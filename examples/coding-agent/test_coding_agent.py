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
import os
import sys

import pytest
import tools
from application import OpenAIClient, ScriptedClient, application


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


# --- OpenAIClient argument parsing -----------------------------------------
# The scripted-client tests above hand `application` an already-parsed call,
# which means the parsing code itself was never exercised. These tests drive
# `OpenAIClient` with a stand-in `openai` module so the real path is covered.


class _FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.function = _FakeFunction(name, arguments)


def _fake_openai(tool_calls):
    """Builds a minimal stand-in for the `openai` module."""

    class _Completions:
        @staticmethod
        def create(**_kwargs):
            message = type(
                "Message", (), {"content": None, "tool_calls": tool_calls}
            )()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    chat = type("Chat", (), {"completions": _Completions()})()
    return type("Module", (), {"chat": chat})()


@pytest.mark.parametrize(
    "arguments, expected",
    [
        # json.loads(None) raises TypeError -- the crash this code exists to stop
        (None, "expected a JSON string, got NoneType"),
        ("{not json}", "could not parse tool arguments as JSON"),
        ('{"path": "a.txt"}', None),
    ],
)
def test_openai_client_survives_unparseable_arguments(
    monkeypatch, arguments, expected
):
    """Bad tool arguments become an error result instead of killing the run."""
    monkeypatch.setitem(
        sys.modules,
        "openai",
        _fake_openai([_FakeToolCall("c1", "write_file", arguments)]),
    )

    call = OpenAIClient()([{"role": "user", "content": "hi"}])["tool_calls"][0]

    assert call["id"] == "c1" and call["name"] == "write_file"
    if expected is None:
        assert "error" not in call
        assert call["args"] == {"path": "a.txt"}
    else:
        assert expected in call["error"]
        assert call["args"] == {}


# --- workspace confinement edges -------------------------------------------


@pytest.mark.parametrize(
    ("root", "full", "expected"),
    [
        # the root itself counts as inside
        ("/ws", "/ws", True),
        # a plain descendant
        ("/ws", "/ws/sub", True),
        # a sibling sharing a name prefix must NOT pass — this is what a naive
        # `startswith(root + os.sep)` test got right but `<ws>-sibling` + `..`
        # tricks could still confuse
        ("/ws", "/ws-sibling", False),
        ("/ws", "/ws-sibling/sub", False),
        # escaping upwards
        ("/ws", "/", False),
        ("/ws/sub", "/ws", False),
        # unrelated trees have no common ancestor
        ("C:\\ws", "D:\\ws\\sub", False),
    ],
)
def test_is_within_compares_path_components(root, full, expected):
    """Containment is decided per path component, not per character.

    Tested through `_is_within` rather than `_resolve` so the assertions do not
    depend on the case behaviour of the filesystem this suite runs on — the
    old test went through `_resolve` and was therefore a false positive on
    macOS, where `realpath` already normalises case and `normcase` never ran.
    """
    assert tools._is_within(root, full) is expected


@pytest.mark.skipif(os.name != "nt", reason="drive-letter comparison is Windows-only")
def test_is_within_is_case_insensitive_on_windows():
    """On Windows the containment check must ignore case.

    `ntpath.commonpath` normcases before comparing, which is the only reason
    the case difference below is tolerated.
    """
    assert tools._is_within("C:\\WS", "c:\\ws\\sub") is True


def test_resolve_accepts_the_workspace_root(tmp_path, monkeypatch):
    """The workspace itself is inside the workspace."""
    monkeypatch.setattr(tools, "WORKSPACE", str(tmp_path))
    assert tools._resolve(".") == os.path.realpath(str(tmp_path))


def test_resolve_rejects_a_sibling_with_a_shared_prefix(tmp_path, monkeypatch):
    """`<ws>-sibling` must not pass a naive prefix test against `<ws>`."""
    monkeypatch.setattr(tools, "WORKSPACE", str(tmp_path))
    sibling = tmp_path.parent / (tmp_path.name + "-sibling")
    sibling.mkdir()

    with pytest.raises(ValueError, match="escapes workspace"):
        tools._resolve(os.path.relpath(sibling, tmp_path))


def test_resolve_tolerates_case_differences(tmp_path, monkeypatch):
    """`realpath` may report a different case than WORKSPACE.

    This exercises the real filesystem, so it is skipped where the filesystem is
    case-sensitive. Note what it does NOT prove: on macOS `realpath` already
    returns the on-disk case, so this passes there without any normalisation
    (see `test_is_within_*` for the containment rule itself).
    """
    swapped = str(tmp_path).swapcase()
    if swapped == str(tmp_path) or not os.path.isdir(swapped):
        pytest.skip("needs a case-insensitive filesystem")

    monkeypatch.setattr(tools, "WORKSPACE", swapped)
    assert tools._resolve("sub") == os.path.join(os.path.realpath(str(tmp_path)), "sub")
