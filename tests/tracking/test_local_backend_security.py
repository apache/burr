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

import pytest
from fastapi import HTTPException

from burr.tracking.server.backend import LocalBackend, _safe_join, _validate_identifier


class TestValidateIdentifier:
    def test_valid_identifiers(self):
        assert _validate_identifier("hello_world") == "hello_world"
        assert _validate_identifier("hello-world") == "hello-world"
        assert _validate_identifier("Hello:World_123") == "Hello:World_123"

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

        with pytest.raises(HTTPException) as exc:
            _validate_identifier("hello..world")
        assert exc.value.status_code == 400


class TestSafeJoin:
    def test_safe_join_within_base(self, tmp_path):
        base = str(tmp_path)
        assert _safe_join(base, "project1") == str(tmp_path / "project1")
        assert _safe_join(base, "project1", "app1") == str(tmp_path / "project1" / "app1")

    def test_safe_join_blocks_traversal(self, tmp_path):
        base = str(tmp_path)
        with pytest.raises(HTTPException) as exc:
            _safe_join(base, "..", "etc")
        assert exc.value.status_code == 400

        with pytest.raises(HTTPException) as exc:
            _safe_join(base, "project", "..", "..", "etc")
        assert exc.value.status_code == 400

    def test_safe_join_allows_exact_base(self, tmp_path):
        base = str(tmp_path)
        # Joining with nothing should return the base itself
        assert _safe_join(base) == base


class TestLocalBackendPathTraversal:
    def test_get_annotation_path_rejects_traversal(self, tmp_path):
        backend = LocalBackend(path=str(tmp_path))
        with pytest.raises(HTTPException) as exc:
            backend._get_annotation_path("../etc")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_list_apps_rejects_traversal(self, tmp_path):
        backend = LocalBackend(path=str(tmp_path))
        with pytest.raises(HTTPException) as exc:
            await backend.list_apps(None, "../../../etc", None)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_application_logs_rejects_traversal_project(self, tmp_path):
        backend = LocalBackend(path=str(tmp_path))
        with pytest.raises(HTTPException) as exc:
            await backend.get_application_logs(None, "../etc", "app1", None)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_application_logs_rejects_traversal_app(self, tmp_path):
        backend = LocalBackend(path=str(tmp_path))
        with pytest.raises(HTTPException) as exc:
            await backend.get_application_logs(None, "project1", "../etc", None)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_application_logs_allows_valid(self, tmp_path):
        backend = LocalBackend(path=str(tmp_path))
        # Create the expected directory structure
        app_dir = tmp_path / "project1" / "app1"
        app_dir.mkdir(parents=True)
        # Use a minimal valid graph.json matching ApplicationModel schema
        (app_dir / "graph.json").write_text(
            '{"entrypoint": "counter", "actions": [{"name": "counter", "reads": [], "writes": ["counter"], "code": "pass"}], "transitions": []}'
        )
        (app_dir / "log.jsonl").write_text("")
        (app_dir / "metadata.json").write_text("{}")

        result = await backend.get_application_logs(None, "project1", "app1", None)
        assert result is not None
