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

import hashlib
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


def test_promotion_target_url_appends_version_subdir():
    assert (
        release._promotion_target_url(
            "0.42.0", "https://dist.apache.org/repos/dist/release/incubator/burr"
        )
        == "https://dist.apache.org/repos/dist/release/incubator/burr/0.42.0"
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


def test_cmd_promote_rejects_already_promoted_release(monkeypatch):
    monkeypatch.setattr(release, "_verify_project_root", lambda: None)
    monkeypatch.setattr(release, "_svn_target_exists", lambda url: True)

    args = Namespace(
        rc_label="0.42.0-RC1",
        apache_id="hari",
        dry_run=False,
        dev_svn_root="https://dist.apache.org/repos/dist/dev/incubator/burr",
        release_svn_root="https://dist.apache.org/repos/dist/release/incubator/burr",
    )

    with pytest.raises(SystemExit):
        release.cmd_promote(args)


def test_cmd_promote_dry_run_uses_server_copy_without_committing(monkeypatch, tmp_path):
    calls = {"checkout": [], "promote": None}

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
            f"{rc_checkout_dir}/apache-burr-0.42.0-incubating-sdist.tar.gz",
            f"{rc_checkout_dir}/apache_burr-0.42.0-py3-none-any.whl",
        ]

    def fake_promote(source_url, target_url, message, apache_id, dry_run=False):
        calls["promote"] = (source_url, target_url, message, apache_id, dry_run)
        return True

    monkeypatch.setattr(release, "_verify_project_root", lambda: None)
    monkeypatch.setattr(release.tempfile, "TemporaryDirectory", lambda prefix=None: _TempDir())
    monkeypatch.setattr(release, "_svn_target_exists", lambda url: False)
    monkeypatch.setattr(release, "_svn_checkout", fake_checkout)
    monkeypatch.setattr(release, "_validate_promotion_artifacts", fake_validate)
    monkeypatch.setattr(release, "_promote_with_server_copy", fake_promote)

    args = Namespace(
        rc_label="0.42.0-RC1",
        apache_id="hari",
        dry_run=True,
        dev_svn_root="https://dist.apache.org/repos/dist/dev/incubator/burr",
        release_svn_root="https://dist.apache.org/repos/dist/release/incubator/burr",
    )

    assert release.cmd_promote(args) is True
    # only the RC is checked out; the release tree is never downloaded
    assert len(calls["checkout"]) == 1

    assert calls["checkout"][0][0].endswith("/0.42.0-incubating-RC1")
    source_url, target_url, message, apache_id, dry_run = calls["promote"]
    assert source_url.endswith("/0.42.0-incubating-RC1")
    assert target_url == "https://dist.apache.org/repos/dist/release/incubator/burr/0.42.0"
    assert apache_id == "hari"
    assert dry_run is True


def test_verify_parser_accepts_skip_signing():
    parser = release._build_parser()
    args = parser.parse_args(["verify", "0.42.0", "0", "--skip-signing"])
    assert args.skip_signing is True


def test_cmd_verify_skip_signing_succeeds_without_asc_files(tmp_path):
    version = "0.42.0"
    content = b"fake artifact content"
    sha = hashlib.sha512(content).hexdigest()

    artifact_name = f"apache-burr-{version}-incubating-src.tar.gz"
    (tmp_path / artifact_name).write_bytes(content)
    (tmp_path / f"{artifact_name}.sha512").write_text(f"{sha}  {artifact_name}\n")
    # No .asc file — simulates a --skip-signing build

    args = Namespace(version=version, rc_num="0", artifacts_dir=str(tmp_path), skip_signing=True)
    assert release.cmd_verify(args) is True
