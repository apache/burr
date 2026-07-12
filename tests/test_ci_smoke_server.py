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

import importlib.util
import sys
from pathlib import Path


def _load_smoke_module():
    module_path = Path(__file__).resolve().parent.parent / "scripts" / "ci_smoke_server.py"
    spec = importlib.util.spec_from_file_location("ci_smoke_server", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke_module()


# ---------------------------------------------------------------------------
# _should_cleanup: pure function mapping (explicit flag, env) → bool
# ---------------------------------------------------------------------------


def test_should_cleanup_defaults_true_outside_ci(monkeypatch):
    """When GITHUB_ACTIONS is not set, default is to clean up (saves disk space)."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert smoke._should_cleanup(explicit=None) is True


def test_should_cleanup_defaults_false_in_ci(monkeypatch):
    """When GITHUB_ACTIONS=true, default is to preserve workspace for artifact upload."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert smoke._should_cleanup(explicit=None) is False


def test_should_cleanup_explicit_true_overrides_ci(monkeypatch):
    """--cleanup flag forces cleanup even inside GitHub Actions."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert smoke._should_cleanup(explicit=True) is True


def test_should_cleanup_explicit_false_overrides_local(monkeypatch):
    """--no-cleanup flag preserves workspace even outside CI."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert smoke._should_cleanup(explicit=False) is False


# ---------------------------------------------------------------------------
# _build_parser: argument parsing for --cleanup / --no-cleanup
# ---------------------------------------------------------------------------


def test_parser_cleanup_flag_sets_true():
    """--cleanup sets args.cleanup to True."""
    parser = smoke._build_parser()
    args = parser.parse_args(["--wheel", "fake.whl", "--cleanup"])
    assert args.cleanup is True


def test_parser_no_cleanup_flag_sets_false():
    """--no-cleanup sets args.cleanup to False."""
    parser = smoke._build_parser()
    args = parser.parse_args(["--wheel", "fake.whl", "--no-cleanup"])
    assert args.cleanup is False


def test_parser_cleanup_defaults_to_none():
    """Without either flag, args.cleanup is None (deferred to _should_cleanup)."""
    parser = smoke._build_parser()
    args = parser.parse_args(["--wheel", "fake.whl"])
    assert args.cleanup is None


# ---------------------------------------------------------------------------
# _poll_projects: polls /api/v0/projects until named project appears
# ---------------------------------------------------------------------------


def test_poll_projects_returns_true_when_project_found(monkeypatch):
    """Returns True immediately once the target project name appears in the response."""
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)

        class FakeResp:
            status = 200

            def read(self):
                import json

                return json.dumps([{"name": "ci-smoke-test"}, {"name": "other"}]).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        return FakeResp()

    monkeypatch.setattr(smoke.urllib.request, "urlopen", fake_urlopen)
    result = smoke._poll_projects("http://127.0.0.1:9999", "ci-smoke-test", timeout_s=5)
    assert result is True
    assert len(calls) == 1


def test_poll_projects_returns_false_on_timeout(monkeypatch):
    """Returns False when the project never appears before the deadline."""

    def fake_urlopen(url, timeout=None):
        raise smoke.urllib.error.URLError("connection refused")

    monkeypatch.setattr(smoke.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)
    monkeypatch.setattr(smoke.time, "time", _make_deadline_clock(budget=0.0))

    result = smoke._poll_projects("http://127.0.0.1:9999", "ci-smoke-test", timeout_s=1)
    assert result is False


def test_poll_projects_returns_false_when_server_proc_exits(monkeypatch):
    """Returns False immediately if the server process has already exited."""

    class FakeProc:
        def poll(self):
            return 1  # non-None → process is dead

    monkeypatch.setattr(
        smoke.urllib.request,
        "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not reach urlopen")),
    )

    result = smoke._poll_projects(
        "http://127.0.0.1:9999", "ci-smoke-test", timeout_s=5, server_proc=FakeProc()
    )
    assert result is False


def test_poll_projects_keeps_trying_until_project_appears(monkeypatch):
    """Retries when project is absent, then succeeds once it appears."""
    import json

    responses = [
        json.dumps([]).encode(),
        json.dumps([{"name": "other"}]).encode(),
        json.dumps([{"name": "ci-smoke-test"}]).encode(),
    ]
    call_count = [0]

    def fake_urlopen(url, timeout=None):
        class FakeResp:
            status = 200

            def read(self):
                idx = min(call_count[0], len(responses) - 1)
                call_count[0] += 1
                return responses[idx]

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        return FakeResp()

    monkeypatch.setattr(smoke.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)

    result = smoke._poll_projects("http://127.0.0.1:9999", "ci-smoke-test", timeout_s=30)
    assert result is True
    assert call_count[0] == 3


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_deadline_clock(budget: float):
    """Return a fake time.time() that expires after `budget` seconds of calls."""
    start = [0.0]

    def _fake_time():
        val = start[0]
        start[0] += budget + 1.0
        return val

    return _fake_time
