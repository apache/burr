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
import tarfile
import tempfile
import zipfile
from pathlib import Path


def _load_verify_module():
    module_path = Path(__file__).resolve().parent.parent / "scripts" / "verify_apache_artifacts.py"
    spec = importlib.util.spec_from_file_location("verify_apache_artifacts", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify = _load_verify_module()


def _reference_text(filename: str) -> bytes:
    return (Path(__file__).resolve().parent.parent / filename).read_bytes()


def _write_tar_gz(path: Path, root: str, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for relative_name, content in files.items():
            with tempfile.NamedTemporaryFile(delete=False, dir=path.parent) as temp_file:
                temp_path = Path(temp_file.name)
                temp_path.write_bytes(content)
            tar.add(temp_path, arcname=f"{root}/{relative_name}")
            temp_path.unlink()


def _write_wheel(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as wheel:
        for name, content in files.items():
            wheel.writestr(name, content)


def test_verify_artifact_contents_passes_for_tarball_and_wheel():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts_dir = Path(temp_dir) / "dist"
        artifacts_dir.mkdir()

        tar_path = artifacts_dir / "apache-burr-0.41.0-incubating-src.tar.gz"
        wheel_path = artifacts_dir / "apache_burr-0.41.0-py3-none-any.whl"

        _write_tar_gz(
            tar_path,
            "apache-burr-0.41.0-incubating-src",
            {
                "LICENSE": _reference_text("LICENSE"),
                "NOTICE": _reference_text("NOTICE"),
                "DISCLAIMER": _reference_text("DISCLAIMER"),
                "README.md": b"example",
            },
        )
        _write_wheel(
            wheel_path,
            {
                "apache_burr/__init__.py": b"__version__ = '0.41.0'\n",
                "apache_burr-0.41.0.dist-info/METADATA": b"Metadata-Version: 2.1\n",
                "apache_burr-0.41.0.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
                "apache_burr-0.41.0.dist-info/licenses/NOTICE": _reference_text("NOTICE"),
                "apache_burr-0.41.0.dist-info/licenses/DISCLAIMER": _reference_text("DISCLAIMER"),
                "apache_burr-0.41.0.dist-info/licenses/LICENSE-wheel": _reference_text(
                    "LICENSE-wheel"
                ),
            },
        )

        summary = verify.VerificationSummary()
        assert verify.verify_artifact_contents(str(artifacts_dir), summary) is True
        assert summary.ok is True


def test_verify_artifact_contents_fails_when_wheel_license_file_is_missing():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts_dir = Path(temp_dir) / "dist"
        artifacts_dir.mkdir()

        wheel_path = artifacts_dir / "apache_burr-0.41.0-py3-none-any.whl"
        _write_wheel(
            wheel_path,
            {
                "apache_burr/__init__.py": b"__version__ = '0.41.0'\n",
                "apache_burr-0.41.0.dist-info/METADATA": b"Metadata-Version: 2.1\n",
                "apache_burr-0.41.0.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
                "apache_burr-0.41.0.dist-info/licenses/NOTICE": _reference_text("NOTICE"),
                "apache_burr-0.41.0.dist-info/licenses/DISCLAIMER": _reference_text("DISCLAIMER"),
            },
        )

        summary = verify.VerificationSummary()
        assert verify.verify_artifact_contents(str(artifacts_dir), summary) is False
        assert any(
            result.name.endswith("contains LICENSE-wheel") and result.status == verify.FAIL
            for result in summary.results
        )


def test_verify_reproducible_build_compares_rebuilt_outputs(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts_dir = Path(temp_dir) / "dist"
        artifacts_dir.mkdir()

        source_tar = artifacts_dir / "apache-burr-0.41.0-incubating-src.tar.gz"
        release_sdist = artifacts_dir / "apache-burr-0.41.0-incubating-sdist.tar.gz"
        release_wheel = artifacts_dir / "apache_burr-0.41.0-py3-none-any.whl"

        _write_tar_gz(source_tar, "apache-burr-0.41.0-incubating-src", {"README.md": b"source"})
        _write_tar_gz(release_sdist, "apache_burr-0.41.0", {"README.md": b"rebuilt"})
        _write_wheel(
            release_wheel,
            {
                "apache_burr-0.41.0.dist-info/METADATA": b"Metadata-Version: 2.1\n",
                "apache_burr-0.41.0.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
            },
        )

        def _fake_build(source_artifact: str, output_dir: str):
            assert Path(source_artifact) == source_tar
            rebuilt_sdist = Path(output_dir) / "apache_burr-0.41.0.tar.gz"
            rebuilt_wheel = Path(output_dir) / release_wheel.name
            rebuilt_sdist.write_bytes(release_sdist.read_bytes())
            rebuilt_wheel.write_bytes(release_wheel.read_bytes())
            return True, "ok"

        monkeypatch.setattr(verify, "_build_reproducible_artifacts", _fake_build)
        # The rebuild itself is stubbed above, so flit need not be installed in
        # the test environment; stub the presence check so the guard passes.
        monkeypatch.setattr(verify.shutil, "which", lambda name: "/usr/bin/flit")

        summary = verify.VerificationSummary()
        assert verify.verify_reproducible_build(str(artifacts_dir), summary) is True
        assert any(
            result.name == "Rebuilt sdist checksum" and result.status == verify.PASS
            for result in summary.results
        )
        assert any(
            result.name == f"Rebuilt wheel checksum: {release_wheel.name}"
            and result.status == verify.PASS
            for result in summary.results
        )


def test_render_vote_email_includes_status_counts():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts_dir = Path(temp_dir) / "dist"
        artifacts_dir.mkdir()
        (artifacts_dir / "apache-burr-0.41.0-incubating-src.tar.gz").write_bytes(b"artifact")

        summary = verify.VerificationSummary()
        summary.pass_("Signatures")
        summary.fail("Apache RAT", "2 issue(s)")
        summary.skip("Reproducible rebuild", "build tool unavailable")

        email = verify.render_vote_email(str(artifacts_dir), summary)

        assert "Subject: [-1] Release Apache Burr (incubating) 0.41.0" in email
        assert "- PASS: 1" in email
        assert "- FAIL: 1" in email
        assert "- SKIP: 1" in email
        assert "- [FAIL] Apache RAT: 2 issue(s)" in email


def test_load_rat_xml_root_skips_log_preamble():
    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "rat.xml"
        report_path.write_text(
            "INFO: Apache Creadur RAT 0.18\n"
            "WARN: deprecated flag\n"
            '<rat-report timestamp="2026-04-18T14:56:12-07:00"></rat-report>\n',
            encoding="utf-8",
        )

        root = verify._load_rat_xml_root(str(report_path))

        assert root.tag == "rat-report"


def test_load_rat_xml_root_ignores_trailing_summary_lines():
    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "rat.xml"
        report_path.write_text(
            "INFO: Apache Creadur RAT 0.18 (Apache Software Foundation)\n"
            '<rat-report timestamp="2026-04-18T15:27:12-07:00">\n'
            "  <statistics>\n"
            '    <statistic approval="true" count="0" name="Approved"/>\n'
            "  </statistics>\n"
            "</rat-report>\n"
            "INFO: RAT summary:\n"
            "INFO:   Approved:  0\n",
            encoding="utf-8",
        )

        root = verify._load_rat_xml_root(str(report_path))

        assert root.tag == "rat-report"


def test_rat_license_state_supports_old_and_new_xml_shapes():
    old_resource = verify.ET.fromstring(
        """
        <resource name="/tmp/old">
          <license-approval name="false" />
          <license-family name="Unknown license" />
        </resource>
        """
    )
    new_resource = verify.ET.fromstring(
        """
        <resource name="/tmp/new">
          <license approval="false" family="Unknown license" name="Unknown license" />
        </resource>
        """
    )

    assert verify._rat_license_state(old_resource) == ("false", "Unknown license")
    assert verify._rat_license_state(new_resource) == ("false", "Unknown license")


def test_rat_scan_target_prefers_single_extracted_project_dir():
    with tempfile.TemporaryDirectory() as temp_dir:
        extract_dir = Path(temp_dir) / "extracted"
        extract_dir.mkdir()
        (extract_dir / "apache-burr-0.41.0-incubating-src").mkdir()

        rat_cwd, rat_target = verify._rat_scan_target(str(extract_dir))

        assert rat_cwd == str(extract_dir)
        assert rat_target == "apache-burr-0.41.0-incubating-src"


def test_artifact_files_ignores_rat_reports():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifacts_dir = Path(temp_dir)
        (artifacts_dir / "apache_burr-0.41.0-py3-none-any.whl").write_bytes(b"wheel")
        (artifacts_dir / "rat-report-sample.xml").write_text("report", encoding="utf-8")
        (artifacts_dir / "rat-report-sample.txt").write_text("report", encoding="utf-8")

        artifact_files = verify._artifact_files(str(artifacts_dir))

        assert artifact_files == ["apache_burr-0.41.0-py3-none-any.whl"]
