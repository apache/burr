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

"""Mounting of the demo routers.

The demo routers (counter, chatbot, ...) each build a local tracking client on ``~/.burr``,
so they are mounted only when ``BURR_SERVER_DEMOS`` asks for them: a plain ``burr`` server
exposes just the UI routes, and the ``burr-demo`` entry point turns the demos on.

Whether a demo router is mounted is checked over HTTP rather than by inspecting
``app.routes``, whose entries for included routers differ between FastAPI versions.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

# A POST-only demo route. A GET on it is 404 when the router is not mounted and 405 (method
# not allowed) when it is, so the check never reaches the handler or touches the demo's
# storage directory.
COUNTER_CREATE = "/api/v0/counter/create/proj/app"
MOUNTED, NOT_MOUNTED = 405, 404


@pytest.fixture
def run(monkeypatch):
    """The server module, imported with static serving off and a local backend configured."""
    monkeypatch.setenv("BURR_SERVE_STATIC", "false")
    monkeypatch.setenv("BURR_BACKEND_IMPL", "burr.tracking.server.backend.LocalBackend")
    return importlib.import_module("burr.tracking.server.run")


def _demo_status(app) -> int:
    return TestClient(app).get(COUNTER_CREATE).status_code


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " Yes "])
def test_demos_mounted_when_env_is_truthy(run, monkeypatch, value):
    monkeypatch.setenv("BURR_SERVER_DEMOS", value)
    assert _demo_status(run.create_burr_ui_app(serve_static=False)) == MOUNTED


@pytest.mark.parametrize("value", [None, "", "0", "false", "no", "off"])
def test_demos_not_mounted_otherwise(run, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("BURR_SERVER_DEMOS", raising=False)
    else:
        monkeypatch.setenv("BURR_SERVER_DEMOS", value)
    app = run.create_burr_ui_app(serve_static=False)
    assert _demo_status(app) == NOT_MOUNTED
    # the UI's own routes are unaffected
    assert TestClient(app).get("/api/v0/projects").status_code == 200


def test_explicit_argument_overrides_env(run, monkeypatch):
    monkeypatch.delenv("BURR_SERVER_DEMOS", raising=False)
    assert _demo_status(run.create_burr_ui_app(serve_static=False, mount_demos=True)) == MOUNTED
    monkeypatch.setenv("BURR_SERVER_DEMOS", "true")
    app = run.create_burr_ui_app(serve_static=False, mount_demos=False)
    assert _demo_status(app) == NOT_MOUNTED


def test_demo_route_is_absent_without_env_and_listed_with_it(run, monkeypatch):
    monkeypatch.delenv("BURR_SERVER_DEMOS", raising=False)
    client = TestClient(run.create_burr_ui_app(serve_static=False))
    assert client.get(COUNTER_CREATE).status_code == NOT_MOUNTED
    assert (
        "/api/v0/counter/create/{project_id}/{app_id}"
        not in client.get("/openapi.json").json()["paths"]
    )

    monkeypatch.setenv("BURR_SERVER_DEMOS", "true")
    client = TestClient(run.create_burr_ui_app(serve_static=False))
    assert client.get(COUNTER_CREATE).status_code == MOUNTED
    assert (
        "/api/v0/counter/create/{project_id}/{app_id}"
        in client.get("/openapi.json").json()["paths"]
    )


def test_mount_burr_ui_passes_the_flag_through(run, monkeypatch):
    from fastapi import FastAPI

    monkeypatch.delenv("BURR_SERVER_DEMOS", raising=False)
    parent = FastAPI()
    run.mount_burr_ui(parent, path="/plain", serve_static=False)
    run.mount_burr_ui(parent, path="/with-demos", serve_static=False, mount_demos=True)
    client = TestClient(parent)
    assert client.get("/plain" + COUNTER_CREATE).status_code == NOT_MOUNTED
    assert client.get("/with-demos" + COUNTER_CREATE).status_code == MOUNTED


class TestCli:
    """``burr`` leaves the demos off; ``burr-demo`` turns them on through the environment."""

    @pytest.fixture
    def cli_main(self):
        # the CLI module needs the `cli` extra, which not every test environment installs
        pytest.importorskip("loguru", reason="the cli extra is not installed")
        return importlib.import_module("burr.cli.__main__")

    def test_run_server_sets_the_flag_only_on_request(self, cli_main, monkeypatch):
        captured = {}

        def fake_command(command, capture_output, addl_env=None):
            captured.clear()
            captured.update(addl_env or {})

        monkeypatch.setattr(cli_main, "_command", fake_command)
        # no_open and no_copy_demo_data keep the call from opening a browser or copying data
        cli_main._run_server(7241, False, True, True)
        assert "BURR_SERVER_DEMOS" not in captured
        cli_main._run_server(7241, False, True, True, demos=True)
        assert captured["BURR_SERVER_DEMOS"] == "true"

    def test_commands_are_wired_to_the_flag(self, cli_main, monkeypatch):
        from click.testing import CliRunner

        calls = []
        monkeypatch.setattr(cli_main, "_run_server", lambda *args, **kwargs: calls.append(kwargs))

        result = CliRunner().invoke(cli_main.cli, ["run-server", "--no-open"])
        assert result.exit_code == 0, result.output
        assert calls[-1].get("demos", False) is False

        result = CliRunner().invoke(cli_main.cli, ["demo-server"])
        assert result.exit_code == 0, result.output
        assert calls[-1]["demos"] is True

    def test_help_mentions_the_flag(self, cli_main):
        from click.testing import CliRunner

        for command in ["run-server", "demo-server"]:
            result = CliRunner().invoke(cli_main.cli, [command, "--help"])
            assert result.exit_code == 0, result.output
            assert "BURR_SERVER_DEMOS" in result.output
