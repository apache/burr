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

pytest.importorskip("loguru")

from burr.cli import __main__ as cli_main  # noqa: E402


def test_open_when_ready_bounds_readiness_request(monkeypatch):
    calls = []

    class Response:
        status_code = 200

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    opened = []
    monkeypatch.setattr(cli_main.requests, "get", fake_get)
    monkeypatch.setattr(cli_main.webbrowser, "open", opened.append)

    cli_main.open_when_ready("http://localhost:7241/health", "http://localhost:7241")

    assert calls == [
        (
            "http://localhost:7241/health",
            {"timeout": cli_main.OPEN_WHEN_READY_TIMEOUT_SECONDS},
        )
    ]
    assert opened == ["http://localhost:7241"]


def test_open_when_ready_retries_read_timeout(monkeypatch):
    calls, opened, sleeps = [], [], []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            raise cli_main.requests.exceptions.ReadTimeout("server did not answer")
        return type("Response", (), {"status_code": 200})()

    monkeypatch.setattr(cli_main.requests, "get", fake_get)
    monkeypatch.setattr(cli_main.webbrowser, "open", opened.append)
    monkeypatch.setattr(cli_main.time, "sleep", sleeps.append)
    cli_main.open_when_ready("http://localhost:7241/health", "http://localhost:7241")

    assert (
        calls
        == [("http://localhost:7241/health", {"timeout": cli_main.OPEN_WHEN_READY_TIMEOUT_SECONDS})]
        * 2
    )
    assert sleeps == [1]
    assert opened == ["http://localhost:7241"]
