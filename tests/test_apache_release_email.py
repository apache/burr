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


def test_result_email_parser_requires_binding_yes():
    parser = apache_release._build_parser()

    try:
        parser.parse_args(["result-email", "--version", "0.41.0", "--rc", "1"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("result-email should require --binding-yes")


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

    assert "[VOTE] Release Apache Burr (Incubating) 0.41.0 RC2" in content
    assert "Apache Burr is an effort undergoing incubation" in content
    assert "https://example.invalid/svn" in content
    assert "https://example.invalid/pypi" in content
    assert "https://example.invalid/KEYS" in content
    assert "- Added release email tooling" in content
    assert "2026-04-21 12:30 UTC" in content
    assert "[ ] +1 Release this as Apache Burr 0.41.0" in content
    assert "{{" not in content


def test_result_email_template_includes_vote_tally():
    content = apache_release._generate_result_email(
        version="0.41.0",
        rc_num="1",
        binding_yes=3,
        non_binding_yes=2,
        abstain=1,
        binding_no=0,
        non_binding_no=1,
        vote_thread_url="https://lists.apache.org/thread/example",
    )

    assert "[RESULT][VOTE] Release Apache Burr (Incubating) 0.41.0 RC1" in content
    assert "Apache Burr is an effort undergoing incubation" in content
    assert "+1: 3 (binding), 2 (non-binding)" in content
    assert "+0: 1" in content
    assert "-1: 0 (binding), 1 (non-binding)" in content
    assert "Therefore, the release candidate has passed." in content
    assert "https://lists.apache.org/thread/example" in content


def test_result_email_template_supports_failed_vote_outcome():
    content = apache_release._generate_result_email(
        version="0.41.0",
        rc_num="1",
        binding_yes=2,
        non_binding_yes=4,
        abstain=1,
        binding_no=2,
        non_binding_no=0,
        vote_thread_url="https://lists.apache.org/thread/example",
    )

    assert "Therefore, the release candidate has not passed." in content


def test_result_email_template_ignores_non_binding_no_votes_for_pass_fail():
    content = apache_release._generate_result_email(
        version="0.41.0",
        rc_num="1",
        binding_yes=3,
        non_binding_yes=0,
        abstain=0,
        binding_no=2,
        non_binding_no=3,
        vote_thread_url="https://lists.apache.org/thread/example",
    )

    assert "-1: 2 (binding), 3 (non-binding)" in content
    assert "Therefore, the release candidate has passed." in content


def test_announce_email_template_includes_release_links_and_summary():
    content = apache_release._generate_announcement_email(
        version="0.41.0",
        pypi_url="https://example.invalid/pypi/0.41.0",
        downloads_url="https://example.invalid/downloads",
        changelog_summary="- Better release tooling",
    )

    assert "[ANNOUNCE] Apache Burr (Incubating) release 0.41.0" in content
    assert "I'm pleased to announce the release of Apache Burr 0.41.0!" in content
    assert "Apache Burr is an effort undergoing incubation" in content
    assert "https://example.invalid/downloads" in content
    assert "https://example.invalid/pypi/0.41.0" in content
    assert "- Better release tooling" in content


def test_emit_email_output_prints_status_to_stderr(monkeypatch, capsys):
    monkeypatch.setattr(apache_release, "_copy_to_clipboard", lambda _content: True)

    apache_release._emit_email_output("email body", copy_to_clipboard=True)

    captured = capsys.readouterr()
    assert "email body" in captured.out
    assert "Copied email content to clipboard" in captured.err
    assert "Copied email content to clipboard" not in captured.out


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
