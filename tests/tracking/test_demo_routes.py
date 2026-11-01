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

"""Identifier handling on the demo routes.

The demo routers (counter, chatbot, ...) build their own local tracking client, so the
project and app ids they receive from the URL go through the same single-path-segment
rule as everything else. These tests check that a rejected id comes back as HTTP 400
with nothing written to disk, and that an accepted id is written under the demos'
storage directory.
"""

import importlib
import os
import uuid
from pathlib import Path

import pytest

from burr.tracking.server.backend import LocalBackend

# ".." sent percent-encoded: the HTTP client collapses a literal ".." segment before the
# request leaves, while the server decodes %2E%2E back to ".." and hands it to the handler.
PARENT = "%2E%2E"


def _entries_under(root: Path) -> set:
    """Every file and directory below ``root``, as paths relative to ``root``."""
    found = set()
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            found.add(os.path.relpath(os.path.join(dirpath, name), root))
    return found


@pytest.fixture
def demo_server(tmp_path, monkeypatch):
    """A TestClient for the tracking server with the demo routers mounted and a throwaway
    home directory, so the demos' ``~/.burr`` storage lands under ``tmp_path``.

    ``burr.tracking.server.run`` reads its environment at import time, so the environment
    is prepared before the import and the module-level backend is swapped afterwards, as
    the other server tests do. The app is built here (rather than reusing ``run.app``) so
    the demo routers are mounted regardless of which test imported the module first.
    """
    home = tmp_path / "home"
    home.mkdir()
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # what expanduser reads on Windows
    monkeypatch.setenv("BURR_SERVE_STATIC", "false")
    monkeypatch.setenv("BURR_SERVER_DEMOS", "true")
    monkeypatch.setenv("BURR_BACKEND_IMPL", "burr.tracking.server.backend.LocalBackend")
    monkeypatch.setenv("burr_path", str(storage))
    run = importlib.import_module("burr.tracking.server.run")
    monkeypatch.setattr(run, "backend", LocalBackend(path=str(storage)))
    # the counter demo caches applications by (project, app) id; start each test cold
    counter = importlib.import_module("burr.examples.hello-world-counter.server")
    counter._get_application.cache_clear()

    from fastapi.testclient import TestClient

    return TestClient(run.create_burr_ui_app(serve_static=False)), tmp_path


class TestCounterDemoRoutes:
    def test_rejected_app_id_is_a_400_and_writes_nothing(self, demo_server):
        client, root = demo_server
        before = _entries_under(root)
        response = client.post(f"/api/v0/counter/create/demo-counter-{uuid.uuid4()}/{PARENT}")
        assert response.status_code == 400
        assert "app_id" in response.json()["detail"]
        assert _entries_under(root) == before

    def test_rejected_project_id_is_a_400_and_writes_nothing(self, demo_server):
        client, root = demo_server
        before = _entries_under(root)
        response = client.post(f"/api/v0/counter/create/{PARENT}/{uuid.uuid4()}")
        assert response.status_code == 400
        assert "project" in response.json()["detail"]
        assert _entries_under(root) == before

    @pytest.mark.parametrize("app_id", [str(uuid.uuid4()), "user@example.com", "chat session 1"])
    def test_accepted_app_id_is_written_under_the_demo_storage(self, demo_server, app_id):
        client, root = demo_server
        project_id = f"demo-counter-{uuid.uuid4()}"
        response = client.post(f"/api/v0/counter/create/{project_id}/{app_id}")
        assert response.status_code == 200
        assert response.json() == app_id
        app_dir = root / "home" / ".burr" / project_id / app_id
        assert (app_dir / "log.jsonl").exists()
        assert (app_dir / "graph.json").exists()
        assert (app_dir / "metadata.json").exists()
