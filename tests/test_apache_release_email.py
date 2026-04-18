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
from datetime import datetime, timezone
from pathlib import Path
from subprocess import CompletedProcess


def _load_apache_release_module():
    module_path = Path(__file__).resolve().parent.parent / "scripts" / "apache_release.py"
    spec = importlib.util.spec_from_file_location("apache_release", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


apache_release = _load_apache_release_module()


def test_vote_email_parser_supports_flag_based_command():
    parser = apache_release._build_parser()

    args = parser.parse_args(["vote-email", "--version", "0.41.0", "--rc", "1", "--copy"])

    assert args.command == "vote-email"
    assert args.version == "0.41.0"
    assert args.rc_num == "1"
    assert args.copy is True


def test_vote_email_template_renders_expected_release_details():
    context = apache_release._build_vote_email_context(
        version="0.41.0",
        rc_num="2",
        svn_url="https://example.invalid/svn",
        pypi_url="https://example.invalid/pypi",
        keys_url="https://example.invalid/KEYS",
        changelog_summary="- Added release email tooling",
        deadline=datetime(2026, 4, 21, 12, 30, tzinfo=timezone.utc),
    )

    content = apache_release._render_template("vote_email.j2", context)

    assert "[VOTE] Release Apache burr 0.41.0-incubating (RC2)" in content
    assert "https://example.invalid/svn" in content
    assert "https://example.invalid/pypi" in content
    assert "https://example.invalid/KEYS" in content
    assert "- Added release email tooling" in content
    assert "2026-04-21 12:30 UTC" in content
    assert "{{" not in content


def test_result_email_template_includes_vote_tally():
    content = apache_release._generate_result_email(
        version="0.41.0",
        rc_num="1",
        binding_yes=3,
        non_binding_yes=2,
        abstain=1,
        no_votes=0,
        vote_thread_url="https://lists.apache.org/thread/example",
    )

    assert "[RESULT][VOTE] Release Apache burr 0.41.0-incubating (RC1)" in content
    assert "Binding +1 votes: 3" in content
    assert "Non-binding +1 votes: 2" in content
    assert "Abstain / +0 votes: 1" in content
    assert "-1 votes: 0" in content
    assert "https://lists.apache.org/thread/example" in content


def test_announce_email_template_includes_release_links_and_summary():
    content = apache_release._generate_announcement_email(
        version="0.41.0",
        pypi_url="https://example.invalid/pypi/0.41.0",
        downloads_url="https://example.invalid/downloads",
        changelog_summary="- Better release tooling",
    )

    assert "[ANNOUNCE] Apache burr 0.41.0-incubating released" in content
    assert "https://example.invalid/downloads" in content
    assert "https://example.invalid/pypi/0.41.0" in content
    assert "- Better release tooling" in content


def test_build_changelog_summary_uses_previous_release_tag(monkeypatch):
    def fake_run(cmd, check, capture_output, text):
        if cmd[:3] == ["git", "tag", "--list"]:
            return CompletedProcess(cmd, 0, stdout="v0.40.2\nv0.41.0\n", stderr="")
        if cmd[:2] == ["git", "log"]:
            assert cmd[2] == "v0.40.2..v0.41.0"
            return CompletedProcess(
                cmd,
                0,
                stdout="fix: tighten release docs\nfeat: add email templates\n",
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(apache_release.subprocess, "run", fake_run)

    summary = apache_release._build_changelog_summary("0.41.0")

    assert "- fix: tighten release docs" in summary
    assert "- feat: add email templates" in summary
