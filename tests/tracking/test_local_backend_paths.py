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

"""Identifier validation and path containment for the local tracking backend.

Project and app identifiers arrive as URL path parameters and are used as path
components under the storage directory. These tests check that only plain
identifiers are accepted, that every resolved path stays inside the storage
directory, and that the server reports rejected identifiers as HTTP 400.
"""

import importlib
import os
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

from burr import system
from burr.tracking.server.backend import LocalBackend, _safe_join, _validate_identifier

# Minimal valid graph.json matching the ApplicationModel schema
GRAPH_JSON = (
    '{"entrypoint": "counter", "actions": [{"name": "counter", "reads": [], '
    '"writes": ["counter"], "code": "pass"}], "transitions": []}'
)

ANNOTATION = {
    "span_id": None,
    "step_name": "counter",
    "tags": ["review"],
    "observations": [
        {"data_fields": {"note": "looks fine"}, "thumbs_up_thumbs_down": True, "data_pointers": []}
    ],
}

# ".." sent percent-encoded: the HTTP client collapses a literal ".." segment before the
# request leaves, while the server decodes %2E%2E back to ".." and hands it to the handler.
PARENT = "%2E%2E"


def _make_app(storage: Path, project_id: str, app_id: str) -> Path:
    """Creates the on-disk layout the local tracking client writes for one app."""
    app_dir = storage / project_id / app_id
    app_dir.mkdir(parents=True)
    (app_dir / "graph.json").write_text(GRAPH_JSON)
    (app_dir / "log.jsonl").write_text("")
    (app_dir / "metadata.json").write_text("{}")
    return app_dir


class TestValidateIdentifier:
    def test_valid_identifiers(self):
        assert _validate_identifier("hello_world") == "hello_world"
        assert _validate_identifier("hello-world") == "hello-world"
        assert _validate_identifier("Hello:World_123") == "Hello:World_123"

    def test_accepts_everything_the_client_produces(self):
        # default app ids are uuid4; project names are [a-zA-Z0-9_-] plus ":" off Windows
        app_id = str(uuid.uuid4())
        assert _validate_identifier(app_id, "app_id") == app_id
        assert _validate_identifier("my-project_1", "project_id") == "my-project_1"
        assert _validate_identifier("a" * 255) == "a" * 255
        # dots are ordinary filename characters as long as the value is not "." or ".."
        assert _validate_identifier("v1.2.3", "app_id") == "v1.2.3"
        assert _validate_identifier("hello..world", "app_id") == "hello..world"
        if not system.IS_WINDOWS:
            assert _validate_identifier("demo:chatbot", "project_id") == "demo:chatbot"

    def test_invalid_identifiers(self):
        with pytest.raises(HTTPException) as exc:
            _validate_identifier("../etc/passwd")
        assert exc.value.status_code == 400

        with pytest.raises(HTTPException) as exc:
            _validate_identifier("hello/world")
        assert exc.value.status_code == 400

        with pytest.raises(HTTPException) as exc:
            _validate_identifier("hello\\world")
        assert exc.value.status_code == 400

    @pytest.mark.parametrize("value", ["", ".", "..", " ", "a b", "/etc/passwd", "C:\\Windows"])
    def test_rejects_empty_dot_and_absolute_identifiers(self, value):
        with pytest.raises(HTTPException) as exc:
            _validate_identifier(value, "project_id")
        assert exc.value.status_code == 400
        assert "project_id" in exc.value.detail

    def test_rejects_over_long_and_non_string_identifiers(self):
        with pytest.raises(HTTPException) as exc:
            _validate_identifier("a" * 256)
        assert exc.value.status_code == 400

        with pytest.raises(HTTPException) as exc:
            _validate_identifier(None)  # type: ignore[arg-type]
        assert exc.value.status_code == 400


class TestSafeJoin:
    def test_safe_join_within_base(self, tmp_path):
        base = str(tmp_path)
        assert _safe_join(base, "project1") == str(tmp_path / "project1")
        assert _safe_join(base, "project1", "app1") == str(tmp_path / "project1" / "app1")

    def test_safe_join_rejects_parent_directory(self, tmp_path):
        base = str(tmp_path)
        with pytest.raises(HTTPException) as exc:
            _safe_join(base, "..", "etc")
        assert exc.value.status_code == 400

        with pytest.raises(HTTPException) as exc:
            _safe_join(base, "project", "..", "..", "etc")
        assert exc.value.status_code == 400

    def test_safe_join_rejects_absolute_parts(self, tmp_path):
        # os.path.join discards everything before an absolute component
        with pytest.raises(HTTPException) as exc:
            _safe_join(str(tmp_path), "/etc/passwd")
        assert exc.value.status_code == 400

        with pytest.raises(HTTPException) as exc:
            _safe_join(str(tmp_path), "project", os.sep + "etc")
        assert exc.value.status_code == 400

    def test_safe_join_refuses_exact_base(self, tmp_path):
        # identifier paths must be strictly inside the storage directory, never the root itself
        with pytest.raises(HTTPException) as exc:
            _safe_join(str(tmp_path))
        assert exc.value.status_code == 400

    def test_safe_join_follows_symlinks(self, tmp_path):
        storage = tmp_path / "storage"
        storage.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (storage / "inside").mkdir()
        (storage / "to-outside").symlink_to(outside, target_is_directory=True)
        (storage / "to-inside").symlink_to(storage / "inside", target_is_directory=True)

        # a link under the storage directory that resolves elsewhere is rejected ...
        with pytest.raises(HTTPException) as exc:
            _safe_join(str(storage), "to-outside")
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException) as exc:
            _safe_join(str(storage), "to-outside", "annotations.jsonl")
        assert exc.value.status_code == 400

        # ... while one that stays inside is accepted (the plain join is returned)
        assert _safe_join(str(storage), "to-inside", "app") == str(storage / "to-inside" / "app")

    def test_safe_join_accepts_symlinked_base(self, tmp_path):
        real_base = tmp_path / "real"
        real_base.mkdir()
        linked_base = tmp_path / "linked"
        linked_base.symlink_to(real_base, target_is_directory=True)
        assert _safe_join(str(linked_base), "project") == str(linked_base / "project")


class TestLocalBackendPathContainment:
    def test_get_annotation_path_rejects_parent_directory(self, tmp_path):
        backend = LocalBackend(path=str(tmp_path))
        with pytest.raises(HTTPException) as exc:
            backend._get_annotation_path("../etc")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_list_apps_rejects_parent_directory(self, tmp_path):
        backend = LocalBackend(path=str(tmp_path))
        with pytest.raises(HTTPException) as exc:
            await backend.list_apps(None, "../../../etc", None)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_application_logs_rejects_parent_directory_in_project(self, tmp_path):
        backend = LocalBackend(path=str(tmp_path))
        with pytest.raises(HTTPException) as exc:
            await backend.get_application_logs(None, "../etc", "app1", None)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_application_logs_rejects_parent_directory_in_app(self, tmp_path):
        backend = LocalBackend(path=str(tmp_path))
        with pytest.raises(HTTPException) as exc:
            await backend.get_application_logs(None, "project1", "../etc", None)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_application_logs_allows_valid(self, tmp_path):
        backend = LocalBackend(path=str(tmp_path))
        _make_app(tmp_path, "project1", "app1")
        result = await backend.get_application_logs(None, "project1", "app1", None)
        assert result is not None


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A TestClient for the tracking server with a LocalBackend on a fresh directory.

    ``burr.tracking.server.run`` builds its backend and FastAPI app at import time from the
    environment, so the environment is prepared before the import and the module-level
    backend is swapped afterwards (the endpoints look it up on every call).
    """
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setenv("BURR_SERVE_STATIC", "false")
    monkeypatch.setenv("BURR_BACKEND_IMPL", "burr.tracking.server.backend.LocalBackend")
    monkeypatch.setenv("burr_path", str(storage))
    run = importlib.import_module("burr.tracking.server.run")
    monkeypatch.setattr(run, "backend", LocalBackend(path=str(storage)))

    from fastapi.testclient import TestClient

    return TestClient(run.app), storage


class TestServerEndpoints:
    def test_list_apps_rejects_parent_directory(self, server):
        client, _ = server
        response = client.get(f"/api/v0/{PARENT}/__none__/apps")
        assert response.status_code == 400
        assert "project_id" in response.json()["detail"]

    def test_application_logs_reject_parent_directory(self, server):
        client, storage = server
        _make_app(storage, "proj", "app-1")
        assert client.get(f"/api/v0/{PARENT}/app-1/__none__/apps").status_code == 400
        assert client.get(f"/api/v0/proj/{PARENT}/__none__/apps").status_code == 400

    @pytest.mark.parametrize("project_id", ["..%5C..%5Cetc", "my%20project", "a" * 256])
    def test_rejects_other_malformed_identifiers(self, server, project_id):
        client, _ = server
        assert client.get(f"/api/v0/{project_id}/__none__/apps").status_code == 400

    def test_separators_never_reach_a_handler(self, server):
        # The router splits on "/" whether or not it is percent-encoded, so an identifier
        # containing one cannot match any identifier route; the function-level tests above
        # cover these values directly.
        client, _ = server
        assert client.get("/api/v0/..%2F..%2Fetc/__none__/apps").status_code == 404
        assert client.get("/api/v0/%2Fetc%2Fpasswd/__none__/apps").status_code == 404

    def test_annotation_endpoints_reject_parent_directory(self, server):
        client, storage = server
        assert client.get(f"/api/v0/{PARENT}/annotations").status_code == 400
        response = client.post(f"/api/v0/{PARENT}/app-1/__none__/0/annotations", json=ANNOTATION)
        assert response.status_code == 400
        response = client.put(f"/api/v0/{PARENT}/0/update_annotations", json=ANNOTATION)
        assert response.status_code == 400
        # nothing was written next to the storage directory
        assert not (storage.parent / "annotations.jsonl").exists()

    def test_symlinked_project_outside_storage_is_rejected(self, server, tmp_path):
        client, storage = server
        outside = tmp_path / "outside"
        outside.mkdir()
        (storage / "linked").symlink_to(outside, target_is_directory=True)

        response = client.get("/api/v0/linked/__none__/apps")
        assert response.status_code == 400
        # the error does not reveal where the storage directory lives
        assert str(storage) not in response.json()["detail"]
        assert client.get("/api/v0/linked/app-1/__none__/apps").status_code == 400
        assert client.get("/api/v0/linked/annotations").status_code == 400
        response = client.post("/api/v0/linked/app-1/__none__/0/annotations", json=ANNOTATION)
        assert response.status_code == 400
        assert not (outside / "annotations.jsonl").exists()

    def test_accepts_identifiers_the_client_produces(self, server):
        client, storage = server
        project_id = "my-project_1"
        app_id = str(uuid.uuid4())
        _make_app(storage, project_id, app_id)

        response = client.get(f"/api/v0/{project_id}/__none__/apps")
        assert response.status_code == 200
        assert [a["app_id"] for a in response.json()["applications"]] == [app_id]

        response = client.get(f"/api/v0/{project_id}/{app_id}/__none__/apps")
        assert response.status_code == 200
        assert response.json()["application"]["entrypoint"] == "counter"

        # ":" is used by the demo projects on non-Windows hosts; an unknown project is an
        # empty listing rather than a rejection
        if not system.IS_WINDOWS:
            response = client.get("/api/v0/demo:chatbot/__none__/apps")
            assert response.status_code == 200
            assert response.json()["applications"] == []

    def test_valid_but_missing_app_is_not_found(self, server):
        client, storage = server
        _make_app(storage, "proj", "app-1")
        assert client.get(f"/api/v0/proj/{uuid.uuid4()}/__none__/apps").status_code == 404

    def test_annotation_round_trip_with_valid_identifiers(self, server):
        client, storage = server
        app_id = str(uuid.uuid4())
        _make_app(storage, "proj", app_id)

        response = client.post(f"/api/v0/proj/{app_id}/__none__/0/annotations", json=ANNOTATION)
        assert response.status_code == 200
        assert (storage / "proj" / "annotations.jsonl").exists()

        response = client.put("/api/v0/proj/0/update_annotations", json=ANNOTATION)
        assert response.status_code == 200

        response = client.get(f"/api/v0/proj/annotations?app_id={app_id}")
        assert response.status_code == 200
        assert [a["app_id"] for a in response.json()] == [app_id]
