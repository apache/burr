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
from argparse import Namespace
from pathlib import Path

import pytest


def _load_release_module():
    module_path = Path(__file__).resolve().parent.parent / "scripts" / "apache_release.py"
    spec = importlib.util.spec_from_file_location("apache_release", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release = _load_release_module()


def _write_artifact_set(directory: Path, version: str, wheel_name: str = None) -> None:
    wheel_name = wheel_name or f"apache_burr-{version}-py3-none-any.whl"
    artifact_names = [
        f"apache-burr-{version}-incubating-src.tar.gz",
        f"apache-burr-{version}-incubating-sdist.tar.gz",
        wheel_name,
    ]
    for artifact_name in artifact_names:
        artifact_path = directory / artifact_name
        artifact_path.write_bytes(b"artifact")
        artifact_path.with_name(f"{artifact_name}.asc").write_text("sig", encoding="utf-8")
        artifact_path.with_name(f"{artifact_name}.sha512").write_text("sha", encoding="utf-8")


def test_parse_rc_label_accepts_supported_formats():
    assert release._parse_rc_label("0.42.0-RC1") == ("0.42.0", "1")
    assert release._parse_rc_label("0.42.0-incubating-RC1") == ("0.42.0", "1")


def test_parse_rc_label_rejects_invalid_format():
    with pytest.raises(SystemExit):
        release._parse_rc_label("0.42.0")


def test_validate_promotion_artifacts_requires_expected_set(tmp_path):
    _write_artifact_set(tmp_path, "0.42.0")

    artifacts = release._validate_promotion_artifacts(str(tmp_path), "0.42.0")

    assert len(artifacts) == 9
    assert any(path.endswith("apache-burr-0.42.0-incubating-src.tar.gz") for path in artifacts)
    assert any(path.endswith("apache-burr-0.42.0-incubating-sdist.tar.gz") for path in artifacts)
    assert any(path.endswith("apache_burr-0.42.0-py3-none-any.whl") for path in artifacts)


def test_validate_promotion_artifacts_fails_when_companion_missing(tmp_path):
    _write_artifact_set(tmp_path, "0.42.0")
    (tmp_path / "apache-burr-0.42.0-incubating-src.tar.gz.asc").unlink()

    with pytest.raises(SystemExit):
        release._validate_promotion_artifacts(str(tmp_path), "0.42.0")


def test_promoted_artifact_name_removes_rc_suffix():
    assert (
        release._promoted_artifact_name("apache-burr-0.42.0-RC1.txt", "1")
        == "apache-burr-0.42.0.txt"
    )
    assert release._promoted_artifact_name("apache_burr-0.42.0-py3-none-any.whl", "1") == (
        "apache_burr-0.42.0-py3-none-any.whl"
    )


def test_twine_upload_command_includes_only_sdist_and_wheel():
    command = release._twine_upload_command(
        [
            "apache-burr-0.42.0-incubating-src.tar.gz",
            "apache-burr-0.42.0-incubating-src.tar.gz.asc",
            "apache-burr-0.42.0-incubating-sdist.tar.gz",
            "apache_burr-0.42.0-py3-none-any.whl",
        ]
    )

    assert command == (
        "twine upload apache-burr-0.42.0-incubating-sdist.tar.gz "
        "apache_burr-0.42.0-py3-none-any.whl"
    )


def test_release_checkout_entries_preserves_keys(tmp_path):
    (tmp_path / ".svn").mkdir()
    (tmp_path / "KEYS").write_text("keys", encoding="utf-8")
    (tmp_path / "apache-burr-0.41.0-incubating-src.tar.gz").write_text("artifact", encoding="utf-8")

    entries = release._release_checkout_entries(str(tmp_path))

    assert entries == [str(tmp_path / "apache-burr-0.41.0-incubating-src.tar.gz")]


def test_remove_existing_release_entries_keeps_keys(monkeypatch, tmp_path):
    (tmp_path / ".svn").mkdir()
    (tmp_path / "KEYS").write_text("keys", encoding="utf-8")
    artifact = tmp_path / "apache-burr-0.41.0-incubating-src.tar.gz"
    artifact.write_text("artifact", encoding="utf-8")

    commands = []

    def fake_run_command(*args, **kwargs):
        commands.append(args[0])
        return None

    monkeypatch.setattr(release, "_run_command", fake_run_command)

    removed = release._remove_existing_release_entries(str(tmp_path))

    assert removed == ["apache-burr-0.41.0-incubating-src.tar.gz"]
    assert commands == [["svn", "rm", "--force", str(artifact)]]
    assert (tmp_path / "KEYS").exists()


def test_cmd_promote_dry_run_plans_without_committing(monkeypatch, tmp_path):
    calls = {"checkout": [], "remove": None, "copy": None, "commit": None}

    class _TempDir:
        def __enter__(self):
            return str(tmp_path)

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_checkout(url: str, checkout_dir: str):
        calls["checkout"].append((url, checkout_dir))
        Path(checkout_dir).mkdir(parents=True, exist_ok=True)

    def fake_validate(rc_checkout_dir: str, version: str):
        assert version == "0.42.0"
        return [
            f"{rc_checkout_dir}/apache-burr-0.42.0-incubating-src.tar.gz",
            f"{rc_checkout_dir}/apache-burr-0.42.0-incubating-src.tar.gz.asc",
            f"{rc_checkout_dir}/apache-burr-0.42.0-incubating-src.tar.gz.sha512",
            f"{rc_checkout_dir}/apache-burr-0.42.0-incubating-sdist.tar.gz",
            f"{rc_checkout_dir}/apache-burr-0.42.0-incubating-sdist.tar.gz.asc",
            f"{rc_checkout_dir}/apache-burr-0.42.0-incubating-sdist.tar.gz.sha512",
            f"{rc_checkout_dir}/apache_burr-0.42.0-py3-none-any.whl",
            f"{rc_checkout_dir}/apache_burr-0.42.0-py3-none-any.whl.asc",
            f"{rc_checkout_dir}/apache_burr-0.42.0-py3-none-any.whl.sha512",
        ]

    def fake_remove(release_checkout_dir: str, dry_run: bool = False):
        calls["remove"] = (release_checkout_dir, dry_run)
        return ["old-release"]

    def fake_copy(
        rc_checkout_dir: str,
        release_checkout_dir: str,
        artifacts: list[str],
        rc_num: str,
        dry_run: bool = False,
    ):
        calls["copy"] = (rc_checkout_dir, release_checkout_dir, list(artifacts), rc_num, dry_run)
        return [Path(artifact).name for artifact in artifacts]

    def fake_commit(
        release_checkout_dir: str,
        version: str,
        rc_num: str,
        apache_id: str,
        dry_run: bool = False,
    ):
        calls["commit"] = (release_checkout_dir, version, rc_num, apache_id, dry_run)
        return True

    monkeypatch.setattr(release.tempfile, "TemporaryDirectory", lambda prefix=None: _TempDir())
    monkeypatch.setattr(release, "_svn_checkout", fake_checkout)
    monkeypatch.setattr(release, "_validate_promotion_artifacts", fake_validate)
    monkeypatch.setattr(release, "_remove_existing_release_entries", fake_remove)
    monkeypatch.setattr(release, "_copy_promoted_artifacts", fake_copy)
    monkeypatch.setattr(release, "_commit_promoted_release", fake_commit)

    args = Namespace(
        rc_label="0.42.0-RC1",
        apache_id="hari",
        dry_run=True,
        dev_svn_root="https://dist.apache.org/repos/dist/dev/incubator/burr",
        release_svn_root="https://dist.apache.org/repos/dist/release/incubator/burr",
    )

    assert release.cmd_promote(args) is True
    assert calls["checkout"][0][0].endswith("/0.42.0-incubating-RC1")
    assert calls["checkout"][1][0] == "https://dist.apache.org/repos/dist/release/incubator/burr"
    assert calls["remove"][1] is True
    assert calls["copy"][3] == "1"
    assert calls["copy"][4] is True
    assert calls["commit"] == (str(tmp_path / "release"), "0.42.0", "1", "hari", True)
