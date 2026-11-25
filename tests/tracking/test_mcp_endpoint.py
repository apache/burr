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

import importlib.metadata
import logging
import os

import pytest

pytest.importorskip("mcp.server.mcpserver", reason="the MCP endpoint needs mcp>=2")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mcp import Client  # noqa: E402

from burr.core import ApplicationBuilder, State, action, default, expr  # noqa: E402
from burr.tracking import LocalTrackingClient  # noqa: E402
from burr.tracking.server.backend import BackendBase, LocalBackend  # noqa: E402
from burr.tracking.server.mcp_endpoint import create_mcp_server  # noqa: E402

# The module-level app serves the built UI, which a source checkout does not have
os.environ.setdefault("BURR_SERVE_STATIC", "false")

from burr.tracking.server import run  # noqa: E402

PROJECT = "support-bot"
LONG_ANSWER = "x" * 9000  # over the 8000-character state budget on its own
MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


@action(reads=[], writes=["prompt"])
def receive(state: State, prompt: str) -> State:
    return state.update(prompt=prompt)


@action(reads=["prompt"], writes=["safe"])
def check_safety(state: State) -> State:
    if state["prompt"] == "crash":
        raise ValueError("safety service unavailable")
    return state.update(safe="password" not in state["prompt"])


@action(reads=["prompt"], writes=["answer"])
def answer(state: State) -> State:
    return state.update(answer=LONG_ANSWER)


@action(reads=[], writes=[])
def refuse(state: State) -> State:
    return state


def _run_app(storage_dir: str, app_id: str, prompts: list) -> None:
    app = (
        ApplicationBuilder()
        .with_actions(receive, check_safety, answer, refuse)
        .with_transitions(
            ("receive", "check_safety"),
            ("check_safety", "answer", expr("safe")),
            ("check_safety", "refuse", default),
            (["answer", "refuse"], "receive"),
        )
        .with_entrypoint("receive")
        .with_identifiers(app_id=app_id)
        .with_tracker(LocalTrackingClient(project=PROJECT, storage_dir=storage_dir))
        .build()
    )
    for prompt in prompts:
        app.run(halt_after=["answer", "refuse"], inputs={"prompt": prompt})


@pytest.fixture
def data_dir(tmp_path):
    """Two tracked runs, plus one that fails in check_safety.

    conv-refused: 0 receive, 1 check_safety (safe), 2 answer, 3 receive, 4 check_safety (unsafe),
    5 refuse.
    """
    storage_dir = str(tmp_path)
    _run_app(storage_dir, "conv-refused", ["hi", "find my password"])
    _run_app(storage_dir, "conv-ok", ["hello"])
    with pytest.raises(ValueError):
        _run_app(storage_dir, "conv-error", ["crash"])
    return storage_dir


@pytest.fixture
def backend(data_dir):
    return LocalBackend(path=data_dir)


async def _call(client: Client, tool: str, **arguments):
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content[0].text
    content = result.structured_content
    # Tools that return a list are wrapped as {"result": [...]}
    return content["result"] if list(content) == ["result"] else content


async def _error(client: Client, tool: str, **arguments) -> str:
    result = await client.call_tool(tool, arguments)
    assert result.is_error
    return result.content[0].text


@pytest.mark.asyncio
async def test_inspect_tools(backend):
    async with Client(create_mcp_server(backend)) as client:
        projects = await _call(client, "list_projects")
        assert [(p["project_id"], p["num_apps"]) for p in projects] == [(PROJECT, 3)]

        apps = await _call(client, "list_apps", project_id=PROJECT)
        assert apps["total"] == 3
        assert {a["app_id"] for a in apps["apps"]} == {"conv-refused", "conv-ok", "conv-error"}

        app = await _call(client, "get_app", project_id=PROJECT, app_id="conv-refused")
        assert app["num_steps"] == 6
        assert app["entrypoint"] == "receive"
        assert {"from": "check_safety", "to": "answer", "condition": "safe"} in app["transitions"]
        assert [(s["action"], s["status"]) for s in app["steps"]] == [
            ("receive", "ok"),
            ("check_safety", "ok"),
            ("answer", "ok"),
            ("receive", "ok"),
            ("check_safety", "ok"),
            ("refuse", "ok"),
        ]

        step = await _call(
            client, "get_step", project_id=PROJECT, app_id="conv-refused", sequence_id=4
        )
        assert step["action"] == "check_safety"
        assert step["exception"] is None
        assert step["state"]["safe"] is False
        assert not any(k.startswith("__") for k in step["state"])

        diff = await _call(
            client,
            "diff_state",
            project_id=PROJECT,
            app_id="conv-refused",
            from_sequence_id=3,
            to_sequence_id=4,
        )
        assert diff == {
            "added": {},
            "removed": [],
            "changed": {"safe": {"before": True, "after": False}},
        }

        history = await _call(
            client, "key_history", project_id=PROJECT, app_id="conv-refused", key="safe"
        )
        assert history["total_changes"] == 2
        assert [(c["sequence_id"], c["value"]) for c in history["changes"]] == [
            (1, True),
            (4, False),
        ]


@pytest.mark.asyncio
async def test_failed_step_shows_up_as_error(backend):
    async with Client(create_mcp_server(backend)) as client:
        app = await _call(client, "get_app", project_id=PROJECT, app_id="conv-error")
        assert app["steps"][-1] == {
            "sequence_id": 1,
            "action": "check_safety",
            "status": "error: ValueError: safety service unavailable",
        }
        case = await _call(
            client, "export_test_case", project_id=PROJECT, app_id="conv-error", sequence_id=1
        )
        # A failed step has no expected state to record, as with burr-test-case create
        assert case["input_state"]["prompt"] == "crash"
        assert case["expected_state"] == {"TODO:": "fill this in"}


@pytest.mark.asyncio
async def test_export_test_case(backend):
    async with Client(create_mcp_server(backend)) as client:
        case = await _call(
            client, "export_test_case", project_id=PROJECT, app_id="conv-refused", sequence_id=4
        )
    assert case["action"] == "check_safety"
    assert case["name"] == "check_safety_conv-ref_4"
    assert case["input_state"]["prompt"] == "find my password"
    assert (case["input_state"]["safe"], case["expected_state"]["safe"]) == (True, False)
    assert not any(k.startswith("__") for k in case["input_state"])


@pytest.mark.asyncio
async def test_get_app_pages_steps(backend):
    async with Client(create_mcp_server(backend)) as client:
        last = await _call(client, "get_app", project_id=PROJECT, app_id="conv-refused", limit=2)
        middle = await _call(
            client, "get_app", project_id=PROJECT, app_id="conv-refused", start=1, limit=2
        )
    assert [s["sequence_id"] for s in last["steps"]] == [4, 5]
    assert [s["sequence_id"] for s in middle["steps"]] == [1, 2]
    assert last["num_steps"] == middle["num_steps"] == 6


@pytest.mark.asyncio
async def test_long_values_are_previewed_unless_asked_for(backend):
    ids = {"project_id": PROJECT, "app_id": "conv-refused", "sequence_id": 2}
    async with Client(create_mcp_server(backend)) as client:
        previewed = await _call(client, "get_step", **ids, keys=["answer"])
        full = await _call(client, "get_step", **ids, keys=["answer"], max_chars=None)
    assert previewed["state"]["answer"]["truncated"] is True
    assert previewed["state"]["answer"]["size"] == len(LONG_ANSWER) + 2  # JSON quotes
    assert len(previewed["state"]["answer"]["preview"]) == 2000
    assert full["state"]["answer"] == LONG_ANSWER


@pytest.mark.asyncio
async def test_large_state_returns_key_sizes(backend):
    ids = {"project_id": PROJECT, "app_id": "conv-refused", "sequence_id": 2}
    async with Client(create_mcp_server(backend)) as client:
        # The answer fits in max_chars, but the state is over the budget
        summary = await _call(client, "get_step", **ids, max_chars=10000)
        full = await _call(client, "get_step", **ids, max_chars=None)
    assert summary["state"] is None
    assert summary["state_sizes"]["answer"] == len(LONG_ANSWER) + 2
    assert "keys=" in summary["note"]
    assert full["state"]["answer"] == LONG_ANSWER


@pytest.mark.asyncio
async def test_server_side_limit_cannot_be_raised(backend):
    ids = {"project_id": PROJECT, "app_id": "conv-refused", "sequence_id": 2}
    async with Client(create_mcp_server(backend, max_chars_limit=100)) as client:
        unlimited = await _call(client, "get_step", **ids, keys=["answer"], max_chars=None)
        smaller = await _call(client, "get_step", **ids, keys=["answer"], max_chars=10)
        history = await _call(
            client, "key_history", project_id=PROJECT, app_id="conv-refused", key="answer"
        )
        instructions = client.instructions
    assert len(unlimited["state"]["answer"]["preview"]) == 100
    assert len(smaller["state"]["answer"]["preview"]) == 10
    assert len(history["changes"][0]["value"]["preview"]) == 100
    assert "at most 100 characters" in instructions


@pytest.mark.asyncio
async def test_missing_apps_and_steps_are_tool_errors(backend):
    async with Client(create_mcp_server(backend)) as client:
        # The backend's HTTP error comes back as a tool error with the same message
        assert "not found" in await _error(client, "get_app", project_id=PROJECT, app_id="nope")
        assert "No step with sequence_id=99" in await _error(
            client, "get_step", project_id=PROJECT, app_id="conv-ok", sequence_id=99
        )


@pytest.mark.asyncio
async def test_tool_groups(backend):
    inspect_tools = {
        "list_projects",
        "list_apps",
        "get_app",
        "get_step",
        "diff_state",
        "key_history",
        "export_test_case",
    }
    async with Client(create_mcp_server(backend)) as client:
        default_tools = (await client.list_tools()).tools
    async with Client(create_mcp_server(backend, ["annotate"])) as client:
        annotate_tools = (await client.list_tools()).tools
    assert {t.name for t in default_tools} == inspect_tools
    assert all(t.annotations.read_only_hint for t in default_tools)
    assert {t.name: t.annotations.read_only_hint for t in annotate_tools} == {
        "annotate_step": False,
        "list_annotations": True,
    }
    with pytest.raises(ValueError, match="bogus"):
        create_mcp_server(backend, ["inspect", "bogus"])


@pytest.mark.asyncio
async def test_annotate_step(backend):
    async with Client(create_mcp_server(backend, ["inspect", "annotate"])) as client:
        created = await _call(
            client,
            "annotate_step",
            project_id=PROJECT,
            app_id="conv-refused",
            sequence_id=4,
            note="flagged a password request",
            tags=["safety"],
            thumbs_up=True,
        )
        listed = await _call(client, "list_annotations", project_id=PROJECT, app_id="conv-refused")
    assert created == {"annotation_id": 0, "step": "check_safety"}
    assert listed == [
        {
            "annotation_id": 0,
            "app_id": "conv-refused",
            "sequence_id": 4,
            "step": "check_safety",
            "tags": ["safety"],
            "notes": ["flagged a password request"],
        }
    ]
    # The same annotation the UI reads over the REST API
    (stored,) = await backend.get_annotations(PROJECT, app_id="conv-refused")
    assert stored.observations[0].thumbs_up_thumbs_down is True


@pytest.fixture
def ui_backend(backend, monkeypatch):
    monkeypatch.setattr(run, "backend", backend)
    for name in ("BURR_MCP_ENABLED", "BURR_MCP_GROUPS", "BURR_MCP_MAX_CHARS"):
        monkeypatch.delenv(name, raising=False)
    return backend


def _tool_names(response) -> list:
    assert response.status_code == 200, response.text
    return [t["name"] for t in response.json()["result"]["tools"]]


def test_ui_app_serves_mcp(ui_backend):
    app = run.create_burr_ui_app(serve_static=False)
    # The lifespan runs twice here, as it does when tests reuse an app
    for _ in range(2):
        with TestClient(app, base_url="http://localhost:7241") as client:
            assert "get_step" in _tool_names(
                client.post("/mcp", json=TOOLS_LIST, headers=MCP_HEADERS)
            )
            # A browser visiting the URL gets a hint instead of an SSE stream that never ends
            get = client.get("/mcp")
            assert get.status_code == 405
            assert "claude mcp add --transport http burr" in get.json()["detail"]
            # The REST API still works next to it
            assert client.get("/api/v0/projects").status_code == 200


def test_mount_burr_ui_serves_mcp(ui_backend):
    # mount_burr_ui() runs the UI's lifespan inside the parent's, and the MCP transport with it
    parent = FastAPI()
    run.mount_burr_ui(parent, path="/burr", serve_static=False)
    with TestClient(parent, base_url="http://localhost:7241") as client:
        assert "get_step" in _tool_names(
            client.post("/burr/mcp", json=TOOLS_LIST, headers=MCP_HEADERS)
        )


def test_mcp_rejects_other_hosts(ui_backend):
    # DNS-rebinding protection from the MCP SDK: only localhost Host headers by default
    with TestClient(
        run.create_burr_ui_app(serve_static=False), base_url="http://evil.example"
    ) as client:
        response = client.post("/mcp", json=TOOLS_LIST, headers=MCP_HEADERS)
    assert response.status_code == 421


def test_settings_pick_groups_and_limit(ui_backend, monkeypatch):
    monkeypatch.setenv("BURR_MCP_GROUPS", "inspect, annotate")
    monkeypatch.setenv("BURR_MCP_MAX_CHARS", "500")
    with TestClient(
        run.create_burr_ui_app(serve_static=False), base_url="http://localhost:7241"
    ) as client:
        names = _tool_names(client.post("/mcp", json=TOOLS_LIST, headers=MCP_HEADERS))
    assert {"get_step", "annotate_step", "list_annotations"} <= set(names)


def test_disabled(ui_backend, monkeypatch):
    monkeypatch.setenv("BURR_MCP_ENABLED", "false")
    with TestClient(
        run.create_burr_ui_app(serve_static=False), base_url="http://localhost:7241"
    ) as client:
        assert client.post("/mcp", json=TOOLS_LIST, headers=MCP_HEADERS).status_code == 404


@pytest.mark.parametrize(
    "env, match",
    [
        ({"BURR_MCP_ENABLED": "yes"}, "BURR_MCP_ENABLED"),
        ({"BURR_MCP_GROUPS": " , "}, "BURR_MCP_GROUPS is empty"),
        ({"BURR_MCP_GROUPS": "inspect,bogus"}, "bogus"),
        ({"BURR_MCP_MAX_CHARS": "lots"}, "BURR_MCP_MAX_CHARS"),
        ({"BURR_MCP_MAX_CHARS": "0"}, "BURR_MCP_MAX_CHARS"),
    ],
)
def test_bad_settings_fail_at_startup(ui_backend, monkeypatch, env, match):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=match):
        run.create_burr_ui_app(serve_static=False)


def _fake_mcp_version(monkeypatch, found):
    def version(name):
        if name != "mcp":
            return importlib.metadata.version(name)
        if found is None:
            raise importlib.metadata.PackageNotFoundError(name)
        return found

    monkeypatch.setattr(run.importlib.metadata, "version", version)


def test_auto_skips_old_mcp_with_a_warning(ui_backend, monkeypatch, caplog):
    _fake_mcp_version(monkeypatch, "1.27.0")
    with caplog.at_level(logging.WARNING, logger=run.logger.name):
        app = run.create_burr_ui_app(serve_static=False)
    assert "found mcp 1.27.0" in caplog.text
    with TestClient(app, base_url="http://localhost:7241") as client:
        assert client.post("/mcp", json=TOOLS_LIST, headers=MCP_HEADERS).status_code == 404


def test_auto_without_mcp_changes_nothing(ui_backend, monkeypatch, caplog):
    _fake_mcp_version(monkeypatch, None)
    with caplog.at_level(logging.WARNING, logger=run.logger.name):
        run.create_burr_ui_app(serve_static=False)
    assert caplog.text == ""


@pytest.mark.parametrize("found", [None, "1.27.0"])
def test_enabled_requires_mcp_2(ui_backend, monkeypatch, found):
    _fake_mcp_version(monkeypatch, found)
    monkeypatch.setenv("BURR_MCP_ENABLED", "true")
    with pytest.raises(RuntimeError, match="needs mcp>=2"):
        run.create_burr_ui_app(serve_static=False)


class _NoAnnotationsBackend(BackendBase):
    """Like the S3 backend: no AnnotationsBackendMixin."""

    def __init__(self, backend: LocalBackend):
        self._backend = backend

    async def list_projects(self, request):
        return await self._backend.list_projects(request)

    async def list_apps(self, request, project_id, partition_key, limit=100, offset=0):
        return await self._backend.list_apps(request, project_id, partition_key, limit, offset)

    async def get_application_logs(self, request, project_id, app_id, partition_key):
        return await self._backend.get_application_logs(request, project_id, app_id, partition_key)

    @classmethod
    def settings_model(cls):
        return LocalBackend.settings_model()


def test_annotate_needs_an_annotations_backend(ui_backend, monkeypatch, caplog):
    monkeypatch.setattr(run, "backend", _NoAnnotationsBackend(ui_backend))
    monkeypatch.setenv("BURR_MCP_GROUPS", "inspect,annotate")
    with caplog.at_level(logging.WARNING, logger=run.logger.name):
        app = run.create_burr_ui_app(serve_static=False)
    assert "Not serving the annotate tools: _NoAnnotationsBackend has no annotations" in caplog.text
    with TestClient(app, base_url="http://localhost:7241") as client:
        names = _tool_names(client.post("/mcp", json=TOOLS_LIST, headers=MCP_HEADERS))
    assert "get_step" in names and "annotate_step" not in names
