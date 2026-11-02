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
import os
import textwrap

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from burr.tracking.server import workspace  # noqa: E402


@pytest.fixture
def root(tmp_path, monkeypatch):
    """An allowed workspace root, with link storage isolated under tmp_path."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv(workspace.WORKSPACE_ROOTS_ENV, str(allowed))
    monkeypatch.setattr(workspace, "_LINKS_PATH", str(tmp_path / "burr" / "workspace_links.json"))
    monkeypatch.setattr(workspace, "_links_cache", None)
    monkeypatch.setattr(workspace, "_processes", {})
    return allowed


@pytest.fixture
def client(root):
    app = FastAPI()
    app.include_router(workspace.router, prefix="/api/v0/workspace")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def linked(client, root):
    """A workspace under the allowed root, linked to project 'proj'."""
    ws = root / "ws"
    ws.mkdir()
    resp = client.post(
        "/api/v0/workspace/link", json={"project_id": "proj", "workspace_path": str(ws)}
    )
    assert resp.status_code == 200, resp.text
    return ws


def _sse_events(text: str) -> list:
    return [json.loads(line[len("data: ") :]) for line in text.splitlines() if line.strip()]


# --- opt-in ---


def _route_paths(app) -> set:
    return set(app.openapi()["paths"])


def test_workspace_routes_are_off_by_default(monkeypatch):
    pytest.importorskip("aiofiles")
    monkeypatch.delenv(workspace.ENABLE_WORKSPACE_ENV, raising=False)
    from burr.tracking.server import run

    app = run.create_burr_ui_app(serve_static=False)
    assert not any(p.startswith("/api/v0/workspace") for p in _route_paths(app))
    with TestClient(app) as c:
        assert c.get("/api/v0/metadata/app_spec").json()["supports_workspace"] is False


def test_workspace_routes_mount_when_enabled(monkeypatch):
    pytest.importorskip("aiofiles")
    from burr.tracking.server import run

    app = run.create_burr_ui_app(serve_static=False, enable_workspace=True)
    assert "/api/v0/workspace/run" in _route_paths(app)
    with TestClient(app) as c:
        assert c.get("/api/v0/metadata/app_spec").json()["supports_workspace"] is True


def test_is_enabled_reads_env(monkeypatch):
    monkeypatch.setenv(workspace.ENABLE_WORKSPACE_ENV, "true")
    assert workspace.is_enabled()
    monkeypatch.setenv(workspace.ENABLE_WORKSPACE_ENV, "false")
    assert not workspace.is_enabled()


# --- /link validation ---


def test_link_inside_root(client, linked):
    resp = client.get("/api/v0/workspace/link", params={"project_id": "proj"})
    assert resp.json()["workspace_path"] == os.path.realpath(linked)


def test_link_outside_root_is_rejected(client, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    resp = client.post(
        "/api/v0/workspace/link", json={"project_id": "proj", "workspace_path": str(outside)}
    )
    assert resp.status_code == 403


def test_link_filesystem_root_is_rejected(client):
    resp = client.post(
        "/api/v0/workspace/link", json={"project_id": "proj", "workspace_path": os.sep}
    )
    assert resp.status_code == 403


def test_link_root_prefix_sibling_is_rejected(client, root):
    sibling = root.parent / (root.name + "-sibling")
    sibling.mkdir()
    resp = client.post(
        "/api/v0/workspace/link", json={"project_id": "proj", "workspace_path": str(sibling)}
    )
    assert resp.status_code == 403


def test_link_symlink_escaping_root_is_rejected(client, root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside)
    resp = client.post(
        "/api/v0/workspace/link",
        json={"project_id": "proj", "workspace_path": str(root / "escape")},
    )
    assert resp.status_code == 403


def test_link_missing_directory(client, root):
    resp = client.post(
        "/api/v0/workspace/link",
        json={"project_id": "proj", "workspace_path": str(root / "nope")},
    )
    assert resp.status_code == 400


@pytest.mark.parametrize("project_id", ["", "a/b", "a\\b", "a\nb", "x" * 300])
def test_link_invalid_project_id(client, root, project_id):
    resp = client.post(
        "/api/v0/workspace/link", json={"project_id": project_id, "workspace_path": str(root)}
    )
    assert resp.status_code == 400


@pytest.mark.parametrize("method", ["get", "delete"])
def test_link_lookup_invalid_project_id(client, method):
    resp = getattr(client, method)("/api/v0/workspace/link", params={"project_id": "a/b"})
    assert resp.status_code == 400


def test_open_outside_root_is_rejected(client, tmp_path):
    resp = client.post("/api/v0/workspace/open", json={"path": str(tmp_path)})
    assert resp.status_code == 403


def test_stale_link_outside_root_is_rejected(client, root, tmp_path, monkeypatch):
    """A links file written under a wider root config no longer grants access."""
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace._write_links({"proj": str(outside)})
    resp = client.get("/api/v0/workspace/tree", params={"workspace": str(outside)})
    assert resp.status_code == 403


# --- files ---


def test_unlinked_workspace_is_rejected(client, root):
    resp = client.get("/api/v0/workspace/tree", params={"workspace": str(root)})
    assert resp.status_code == 403


def test_tree_and_file(client, linked):
    (linked / "app.py").write_text("from burr.core import ApplicationBuilder\n")
    tree = client.get("/api/v0/workspace/tree", params={"workspace": str(linked)}).json()
    assert [(e["name"], e["has_burr_app"]) for e in tree] == [("app.py", True)]
    resp = client.get(
        "/api/v0/workspace/file", params={"workspace": str(linked), "relative_path": "app.py"}
    )
    assert resp.json()["language"] == "python"


def test_file_path_traversal_is_rejected(client, linked):
    resp = client.get(
        "/api/v0/workspace/file",
        params={"workspace": str(linked), "relative_path": "../../etc/passwd"},
    )
    assert resp.status_code == 403


# --- run + stream ---


def _run(client, ws, script: str, body: str) -> int:
    (ws / script).write_text(textwrap.dedent(body))
    resp = client.post("/api/v0/workspace/run", json={"workspace": str(ws), "script": script})
    assert resp.status_code == 200, resp.text
    return resp.json()["pid"]


def test_stream_output_keeps_lines_after_quiet_gaps(client, linked):
    """Regression: output after a >100ms gap used to be dropped."""
    pid = _run(
        client,
        linked,
        "gaps.py",
        """
        import sys, time
        print("first", flush=True)
        time.sleep(0.4)
        print("second", flush=True)
        print("err", file=sys.stderr, flush=True)
        time.sleep(0.3)
        print("third", flush=True)
        sys.exit(3)
        """,
    )
    events = _sse_events(client.get(f"/api/v0/workspace/run/{pid}/output").text)
    stdout = [e["data"].strip() for e in events if e["type"] == "stdout"]
    stderr = [e["data"].strip() for e in events if e["type"] == "stderr"]
    assert stdout == ["first", "second", "third"]
    assert stderr == ["err"]
    assert events[-1] == {"type": "exit", "data": "3"}


def test_stream_output_twice_is_rejected(client, linked):
    pid = _run(client, linked, "quick.py", "print('hi')\n")
    client.get(f"/api/v0/workspace/run/{pid}/output")
    assert client.get(f"/api/v0/workspace/run/{pid}/output").status_code == 409


def test_run_uses_server_interpreter(client, linked):
    import sys

    pid = _run(client, linked, "which.py", "import sys; print(sys.executable)\n")
    events = _sse_events(client.get(f"/api/v0/workspace/run/{pid}/output").text)
    assert events[0]["data"].strip() == sys.executable


def test_run_non_python_is_rejected(client, linked):
    (linked / "run.sh").write_text("echo hi\n")
    resp = client.post("/api/v0/workspace/run", json={"workspace": str(linked), "script": "run.sh"})
    assert resp.status_code == 400


def test_list_and_stop_processes(client, linked):
    pid = _run(client, linked, "sleepy.py", "import time; time.sleep(30)\n")
    procs = client.get("/api/v0/workspace/processes", params={"workspace": str(linked)}).json()
    assert [p["pid"] for p in procs] == [pid]
    resp = client.post(f"/api/v0/workspace/run/{pid}/stop")
    assert resp.json()["status"] == "exited"


def test_cleanup_processes_terminates_children(client, linked):
    pid = _run(client, linked, "sleepy.py", "import time; time.sleep(30)\n")
    proc = workspace._processes[pid]["process"]
    # the subprocess belongs to the client's event loop, so clean up on that loop
    client.portal.call(workspace.cleanup_processes)
    assert proc.returncode is not None
    assert workspace._processes == {}
