#!/usr/bin/env python3
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
#   Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
Apache Artifacts Verification Script

Comprehensive verification tool for Apache release artifacts.
Checks signatures, checksums, archive integrity, license metadata,
reproducible rebuilds, and Apache RAT results.

Usage:
    python scripts/verify_apache_artifacts.py --help
        Show the available verification commands and flags.
    python scripts/verify_apache_artifacts.py signatures
        Verify detached GPG signatures, SHA512 checksums, and basic archive readability.
    python scripts/verify_apache_artifacts.py artifacts
        Verify required LICENSE/NOTICE/DISCLAIMER files in release artifacts.
    python scripts/verify_apache_artifacts.py licenses --rat-jar /path/to/apache-rat.jar
        Run Apache RAT and validate license-report results for extracted tarball contents.
    python scripts/verify_apache_artifacts.py reproducible
        Rebuild from the release source artifact and compare rebuilt outputs to release artifacts.
    python scripts/verify_apache_artifacts.py all --rat-jar /path/to/apache-rat.jar --vote-email
        Run the full verification flow and optionally render a vote email draft from the results.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# Configuration
PROJECT_SHORT_NAME = "burr"
REQUIRED_TEXT_FILES = ("LICENSE", "NOTICE", "DISCLAIMER")
WHEEL_LICENSE_FILES = ("LICENSE-wheel",)
WHEEL_REQUIRED_TEXT_FILES = ("NOTICE", "DISCLAIMER") + WHEEL_LICENSE_FILES
PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass
class CheckResult:
    name: str
    status: str
    details: str = ""


@dataclass
class VerificationSummary:
    results: list[CheckResult] = field(default_factory=list)

    def record(self, name: str, status: str, details: str = "") -> None:
        self.results.append(CheckResult(name=name, status=status, details=details))

    def pass_(self, name: str, details: str = "") -> None:
        self.record(name, PASS, details)

    def fail(self, name: str, details: str = "") -> None:
        self.record(name, FAIL, details)

    def skip(self, name: str, details: str = "") -> None:
        self.record(name, SKIP, details)

    @property
    def ok(self) -> bool:
        return all(result.status != FAIL for result in self.results)

    def render(self) -> str:
        lines = ["Results:"]
        if not self.results:
            lines.append("  (no checks executed)")
            return "\n".join(lines)

        width = max(len(result.name) for result in self.results)
        for result in self.results:
            symbol = {"PASS": "✅", "FAIL": "❌", "SKIP": "⊘"}[result.status]
            line = f"  {result.name:<{width}}  {symbol} {result.status}"
            if result.details:
                line += f"  {result.details}"
            lines.append(line)
        return "\n".join(lines)


def _fail(message: str) -> None:
    print(f"\n❌ {message}")
    sys.exit(1)


def _print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def _sha512_for_file(path: str) -> str:
    sha512_hash = hashlib.sha512()
    with open(path, "rb") as handle:
        while chunk := handle.read(65536):
            sha512_hash.update(chunk)
    return sha512_hash.hexdigest()


def _read_expected_text_files() -> dict[str, bytes]:
    project_root = Path(__file__).resolve().parent.parent
    expected: dict[str, bytes] = {}
    for filename in (*REQUIRED_TEXT_FILES, *WHEEL_LICENSE_FILES):
        expected[filename] = (project_root / filename).read_bytes()
    return expected


def _artifact_files(artifacts_dir: str) -> list[str]:
    all_files = [
        name
        for name in os.listdir(artifacts_dir)
        if os.path.isfile(os.path.join(artifacts_dir, name))
    ]
    return sorted(
        name
        for name in all_files
        if not name.endswith((".asc", ".sha512")) and not name.startswith("rat-report-")
    )


def _top_level_prefix(paths: list[str]) -> str | None:
    parts = [PurePosixPath(path).parts for path in paths if path]
    if not parts:
        return None
    prefix = parts[0][0]
    if all(item and item[0] == prefix for item in parts):
        return prefix
    return None


def _normalize_archive_member_names(names: list[str]) -> dict[str, str]:
    prefix = _top_level_prefix(names)
    normalized = {}
    for name in names:
        pure_name = PurePosixPath(name)
        relative_parts = (
            pure_name.parts[1:] if prefix and pure_name.parts[:1] == (prefix,) else pure_name.parts
        )
        normalized_name = str(PurePosixPath(*relative_parts)) if relative_parts else ""
        normalized[normalized_name] = name
    return normalized


def _tar_file_bytes(artifact_path: str) -> dict[str, bytes]:
    with tarfile.open(artifact_path, "r:gz") as tar:
        file_members = [member for member in tar.getmembers() if member.isfile()]
        mapping = _normalize_archive_member_names([member.name for member in file_members])
        contents: dict[str, bytes] = {}
        for member in file_members:
            normalized_name = next(
                normalized for normalized, original in mapping.items() if original == member.name
            )
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            contents[normalized_name] = extracted.read()
        return contents


def _wheel_file_bytes(artifact_path: str) -> dict[str, bytes]:
    with zipfile.ZipFile(artifact_path, "r") as wheel:
        return {name: wheel.read(name) for name in wheel.namelist() if not name.endswith("/")}


def _find_files_by_basename(file_bytes: dict[str, bytes], basename: str) -> list[str]:
    matches = []
    for path in file_bytes:
        if PurePosixPath(path).name == basename:
            matches.append(path)
    return sorted(matches)


def _verify_artifact_exists(
    artifact_path: str, summary: VerificationSummary, min_size: int = 1000
) -> bool:
    name = f"Artifact exists: {os.path.basename(artifact_path)}"
    if not os.path.exists(artifact_path):
        print(f"  ✗ Artifact not found: {os.path.basename(artifact_path)}")
        summary.fail(name, "missing file")
        return False

    file_size = os.path.getsize(artifact_path)
    if file_size < min_size:
        print(
            f"  ✗ Artifact is suspiciously small ({file_size} bytes): {os.path.basename(artifact_path)}"
        )
        summary.fail(name, f"size {file_size} bytes")
        return False

    print(f"  ✓ Artifact exists: {os.path.basename(artifact_path)} ({file_size:,} bytes)")
    summary.pass_(name, f"{file_size:,} bytes")
    return True


def _verify_artifact_signature(
    artifact_path: str, signature_path: str, summary: VerificationSummary
) -> bool:
    check_name = f"GPG signature: {os.path.basename(artifact_path)}"
    print(f"  Verifying GPG signature: {os.path.basename(signature_path)}")

    if not os.path.exists(signature_path):
        print("    ✗ Signature file not found")
        summary.fail(check_name, "missing .asc")
        return False

    try:
        result = subprocess.run(
            ["gpg", "--verify", signature_path, artifact_path],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        print(f"    ✗ Error running GPG: {exc}")
        summary.fail(check_name, f"gpg unavailable: {exc}")
        return False

    if result.returncode == 0:
        print("    ✓ GPG signature is valid")
        summary.pass_(check_name)
        return True

    print("    ✗ GPG signature verification failed")
    if result.stderr:
        print(f"    Error: {result.stderr.decode()}")
    summary.fail(check_name, result.stderr.decode().strip() or "verification failed")
    return False


def _verify_artifact_checksum(
    artifact_path: str,
    checksum_path: str,
    summary: VerificationSummary,
) -> bool:
    check_name = f"SHA512 checksum: {os.path.basename(artifact_path)}"
    print(f"  Verifying SHA512 checksum: {os.path.basename(checksum_path)}")

    if not os.path.exists(checksum_path):
        print("    ✗ Checksum file not found")
        summary.fail(check_name, "missing .sha512")
        return False

    with open(checksum_path, "r", encoding="utf-8") as handle:
        expected_checksum = handle.read().strip().split()[0]

    actual_checksum = _sha512_for_file(artifact_path)
    if actual_checksum == expected_checksum:
        print("    ✓ SHA512 checksum is valid")
        summary.pass_(check_name)
        return True

    print("    ✗ SHA512 checksum mismatch!")
    print(f"    Expected: {expected_checksum}")
    print(f"    Actual:   {actual_checksum}")
    summary.fail(check_name, "checksum mismatch")
    return False


def _verify_tar_gz_readable(artifact_path: str, summary: VerificationSummary) -> bool:
    check_name = f"Readable tar.gz: {os.path.basename(artifact_path)}"
    print(f"  Checking archive readability: {os.path.basename(artifact_path)}")

    try:
        with tarfile.open(artifact_path, "r:gz") as tar:
            members = tar.getmembers()
            if not members:
                print("    ✗ Archive is empty (no files)")
                summary.fail(check_name, "archive is empty")
                return False
            print(f"    ✓ Archive is readable and contains {len(members)} files")
            summary.pass_(check_name, f"{len(members)} members")
            return True
    except tarfile.TarError as exc:
        print(f"    ✗ Archive is corrupted or unreadable: {exc}")
        summary.fail(check_name, str(exc))
        return False
    except Exception as exc:  # pragma: no cover - defensive
        print(f"    ✗ Error reading archive: {exc}")
        summary.fail(check_name, str(exc))
        return False


def _verify_wheel_readable(wheel_path: str, summary: VerificationSummary) -> bool:
    check_name = f"Readable wheel: {os.path.basename(wheel_path)}"
    print(f"  Checking wheel readability: {os.path.basename(wheel_path)}")

    try:
        with zipfile.ZipFile(wheel_path, "r") as wheel:
            file_list = wheel.namelist()
            if not file_list:
                print("    ✗ Wheel is empty (no files)")
                summary.fail(check_name, "wheel is empty")
                return False

            metadata_files = [name for name in file_list if "METADATA" in name or "WHEEL" in name]
            if not metadata_files:
                print("    ✗ Wheel missing required metadata files")
                summary.fail(check_name, "missing METADATA/WHEEL")
                return False

            print(f"    ✓ Wheel is readable and contains {len(file_list)} files")
            summary.pass_(check_name, f"{len(file_list)} members")
            return True
    except zipfile.BadZipFile as exc:
        print("    ✗ Wheel is corrupted or not a valid ZIP file")
        summary.fail(check_name, str(exc))
        return False
    except Exception as exc:  # pragma: no cover - defensive
        print(f"    ✗ Error reading wheel: {exc}")
        summary.fail(check_name, str(exc))
        return False


def _verify_required_text_files(
    artifact_name: str,
    file_bytes: dict[str, bytes],
    required_files: tuple[str, ...],
    expected_files: dict[str, bytes],
    summary: VerificationSummary,
) -> bool:
    all_valid = True
    for required_name in required_files:
        check_name = f"{artifact_name} contains {required_name}"
        matches = _find_files_by_basename(file_bytes, required_name)
        if not matches:
            print(f"    ✗ Missing {required_name}")
            summary.fail(check_name, "missing")
            all_valid = False
            continue

        matched_path = matches[0]
        if file_bytes[matched_path] != expected_files[required_name]:
            print(f"    ✗ {required_name} content mismatch ({matched_path})")
            summary.fail(check_name, f"content mismatch at {matched_path}")
            all_valid = False
            continue

        print(f"    ✓ {required_name} present and matches repository copy ({matched_path})")
        summary.pass_(check_name, matched_path)
    return all_valid


def verify_artifact_contents(
    artifacts_dir: str, summary: VerificationSummary | None = None
) -> bool:
    _print_section("Verifying Artifact Metadata Files")

    if summary is None:
        summary = VerificationSummary()

    if not os.path.exists(artifacts_dir):
        _fail(f"Artifacts directory not found: {artifacts_dir}")

    artifacts = _artifact_files(artifacts_dir)
    if not artifacts:
        print(f"⚠️  No artifacts found in {artifacts_dir}")
        summary.fail("Artifact metadata verification", "no artifacts found")
        return False

    expected_files = _read_expected_text_files()
    all_valid = True

    for artifact_name in artifacts:
        artifact_path = os.path.join(artifacts_dir, artifact_name)
        print(f"Inspecting metadata files: {artifact_name}")
        print("-" * 80)

        if artifact_name.endswith(".tar.gz"):
            file_bytes = _tar_file_bytes(artifact_path)
            if not _verify_required_text_files(
                artifact_name,
                file_bytes,
                REQUIRED_TEXT_FILES,
                expected_files,
                summary,
            ):
                all_valid = False
        elif artifact_name.endswith(".whl"):
            file_bytes = _wheel_file_bytes(artifact_path)
            if not _verify_required_text_files(
                artifact_name,
                file_bytes,
                WHEEL_REQUIRED_TEXT_FILES,
                expected_files,
                summary,
            ):
                all_valid = False
        else:
            print(f"    ⚠️  Skipping unsupported artifact type: {artifact_name}")
            summary.skip(f"Artifact metadata: {artifact_name}", "unsupported type")
        print()

    return all_valid


def verify_signatures(artifacts_dir: str, summary: VerificationSummary | None = None) -> bool:
    _print_section("Verifying Signatures and Checksums")

    if summary is None:
        summary = VerificationSummary()

    if not os.path.exists(artifacts_dir):
        _fail(f"Artifacts directory not found: {artifacts_dir}")

    artifacts = _artifact_files(artifacts_dir)
    if not artifacts:
        print(f"⚠️  No artifacts found in {artifacts_dir}")
        summary.fail("Signature verification", "no artifacts found")
        return False

    print(f"Found {len(artifacts)} artifact(s) to verify:\n")

    all_valid = True
    for artifact_name in artifacts:
        artifact_path = os.path.join(artifacts_dir, artifact_name)
        print(f"Verifying: {artifact_name}")
        print("-" * 80)

        if not _verify_artifact_exists(artifact_path, summary):
            all_valid = False
            continue

        if not _verify_artifact_signature(artifact_path, f"{artifact_path}.asc", summary):
            all_valid = False

        if not _verify_artifact_checksum(artifact_path, f"{artifact_path}.sha512", summary):
            all_valid = False

        if artifact_name.endswith(".tar.gz"):
            if not _verify_tar_gz_readable(artifact_path, summary):
                all_valid = False
        elif artifact_name.endswith(".whl"):
            if not _verify_wheel_readable(artifact_path, summary):
                all_valid = False

        print()

    return all_valid


def _safe_extract_tar(tar_handle: tarfile.TarFile, extract_dir: str) -> None:
    try:
        tar_handle.extractall(extract_dir, filter="data")
    except TypeError:
        tar_handle.extractall(extract_dir)


def _build_rat_command(
    rat_jar_path: str,
    extract_dir: str,
    rat_excludes: str | None,
    output_style: str | None = None,
) -> list[str]:
    command = ["java", "-jar", rat_jar_path]
    if output_style:
        command.extend(["--output-style", output_style])
    if rat_excludes:
        command.extend(["--input-exclude-file", rat_excludes])
    command.extend(["--", extract_dir])
    return command


def _rat_scan_target(extract_dir: str) -> tuple[str, str]:
    extracted_root = Path(extract_dir)
    entries = [entry for entry in extracted_root.iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        return str(extracted_root), entries[0].name
    return str(extracted_root), "."


def _load_rat_xml_root(rat_report_xml: str) -> ET.Element:
    raw_xml = Path(rat_report_xml).read_text(encoding="utf-8")
    start_tag = "<rat-report"
    end_tag = "</rat-report>"
    xml_start = raw_xml.find(start_tag)
    if xml_start == -1:
        raise ValueError("RAT XML report does not contain XML content")

    xml_end = raw_xml.find(end_tag, xml_start)
    if xml_end == -1:
        raise ValueError("RAT XML report is missing closing </rat-report> tag")

    xml_content = raw_xml[xml_start : xml_end + len(end_tag)].strip()
    if not xml_content:
        raise ValueError("RAT XML report is empty")

    return ET.fromstring(xml_content)


def _rat_license_state(resource: ET.Element) -> tuple[str, str]:
    approval = resource.find("license-approval")
    family = resource.find("license-family")
    if approval is not None or family is not None:
        license_approval = approval.get("name", "true") if approval is not None else "true"
        license_family = family.get("name", "") if family is not None else ""
        return license_approval, license_family

    license_elem = resource.find("license")
    if license_elem is not None:
        license_approval = license_elem.get("approval", "true")
        license_family = license_elem.get("family", "") or license_elem.get("name", "")
        return license_approval, license_family

    return "true", ""


def _check_licenses_with_rat(
    artifact_path: str,
    rat_jar_path: str,
    report_name: str,
    summary: VerificationSummary,
    report_only: bool = False,
) -> bool:
    check_name = f"Apache RAT: {os.path.basename(artifact_path)}"
    print(f"\nRunning Apache RAT on: {os.path.basename(artifact_path)}")
    print("-" * 80)

    report_dir = "dist"
    os.makedirs(report_dir, exist_ok=True)

    rat_report_xml = os.path.join(report_dir, f"rat-report-{report_name}.xml")
    rat_report_txt = os.path.join(report_dir, f"rat-report-{report_name}.txt")

    with tempfile.TemporaryDirectory() as temp_dir:
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir)

        print("  Extracting archive...")
        try:
            with tarfile.open(artifact_path, "r:gz") as tar:
                _safe_extract_tar(tar, extract_dir)
            print("    ✓ Extracted to temp directory")
        except Exception as exc:
            print(f"    ✗ Error extracting archive: {exc}")
            summary.fail(check_name, f"extract failed: {exc}")
            return False

        rat_excludes = ".rat-excludes"
        if not os.path.exists(rat_excludes):
            print(f"    ⚠️  Warning: {rat_excludes} not found, running without excludes")
            rat_excludes = None
        else:
            rat_excludes = os.path.abspath(rat_excludes)

        rat_cwd, rat_target = _rat_scan_target(extract_dir)

        print("  Running Apache RAT (XML format for parsing)...")
        rat_cmd_xml = _build_rat_command(
            rat_jar_path,
            rat_target,
            rat_excludes,
            output_style="xml",
        )

        try:
            with open(rat_report_xml, "w", encoding="utf-8") as report_file:
                result = subprocess.run(
                    rat_cmd_xml,
                    cwd=rat_cwd,
                    stdout=report_file,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
            if result.returncode != 0:
                # A nonzero exit means RAT crashed mid-scan (e.g. on a broken
                # symlink). The XML report it produced will be truncated and
                # parsing it gives a falsely clean result, so fail hard here.
                print(f"    ✗ RAT exited with code {result.returncode}")
                if result.stderr:
                    print("    --- RAT stderr ---")
                    for line in result.stderr.splitlines()[-25:]:
                        print(f"      {line}")
                summary.fail(check_name, f"RAT exited with code {result.returncode}")
                return False
            print(f"    ✓ RAT XML report: {rat_report_xml}")
        except Exception as exc:
            print(f"    ✗ Error running RAT (XML): {exc}")
            summary.fail(check_name, f"RAT execution failed: {exc}")
            return False

        print("  Running Apache RAT (text format for review)...")
        rat_cmd_txt = _build_rat_command(rat_jar_path, rat_target, rat_excludes)

        try:
            with open(rat_report_txt, "w", encoding="utf-8") as report_file:
                subprocess.run(
                    rat_cmd_txt,
                    cwd=rat_cwd,
                    stdout=report_file,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
            print(f"    ✓ RAT text report: {rat_report_txt}")
        except Exception as exc:
            print(f"    ⚠️  Warning: Could not generate text report: {exc}")

        print("  Parsing RAT report...")
        try:
            root = _load_rat_xml_root(rat_report_xml)
            unapproved_licenses = []
            unknown_licenses = []

            for resource in root.findall(".//resource"):
                name = resource.get("name", "unknown")
                license_approval, license_family = _rat_license_state(resource)

                if license_approval == "false" or license_family == "Unknown license":
                    if license_family == "Unknown license" or not license_family:
                        unknown_licenses.append(name)
                    else:
                        unapproved_licenses.append(name)

            issues_count = len(unapproved_licenses) + len(unknown_licenses)
            total_files = len(root.findall(".//resource"))
            print(f"    ✓ Scanned {total_files} files")
            print(f"    ✓ Found {issues_count} files with license issues")

            if issues_count == 0:
                print("    ✅ All files have approved licenses")
                summary.pass_(check_name, "no RAT issues")
                return True

            if unknown_licenses:
                print(f"\n    Unknown/Missing Licenses ({len(unknown_licenses)} files):")
                for file_name in unknown_licenses[:10]:
                    print(f"      - {file_name}")
            if unapproved_licenses:
                print(f"\n    Unapproved Licenses ({len(unapproved_licenses)} files):")
                for file_name in unapproved_licenses[:10]:
                    print(f"      - {file_name}")

            if report_only:
                print("\n  ℹ️  Report-only mode: continuing despite license issues")
                summary.pass_(check_name, f"report-only with {issues_count} issue(s)")
                return True

            print("\n  ❌ License check failed!")
            summary.fail(check_name, f"{issues_count} RAT issue(s)")
            return False
        except Exception as exc:
            print(f"    ✗ Error parsing RAT report: {exc}")
            if report_only:
                print("    ℹ️  Report-only mode: continuing despite parse error")
                summary.pass_(check_name, "report-only despite parse error")
                return True
            summary.fail(check_name, f"report parse failed: {exc}")
            return False


def verify_licenses(
    artifacts_dir: str,
    rat_jar_path: str,
    summary: VerificationSummary | None = None,
    report_only: bool = False,
) -> bool:
    _print_section("Verifying Licenses with Apache RAT")

    if summary is None:
        summary = VerificationSummary()

    if not os.path.exists(artifacts_dir):
        _fail(f"Artifacts directory not found: {artifacts_dir}")

    if not rat_jar_path or not os.path.exists(rat_jar_path):
        _fail(
            f"Apache RAT JAR not found: {rat_jar_path}\nDownload from: https://creadur.apache.org/rat/download_rat.cgi"
        )

    if shutil.which("java") is None:
        _fail("Java not found. Required for Apache RAT.")

    tar_artifacts = [name for name in _artifact_files(artifacts_dir) if name.endswith(".tar.gz")]
    if not tar_artifacts:
        print(f"⚠️  No tar.gz artifacts found in {artifacts_dir}")
        summary.fail("Apache RAT", "no tar.gz artifacts found")
        return False

    print(f"Found {len(tar_artifacts)} tar.gz artifact(s) to check:\n")

    all_valid = True
    for artifact_name in tar_artifacts:
        artifact_path = os.path.join(artifacts_dir, artifact_name)
        report_name = artifact_name.replace(".tar.gz", "").replace(".", "-")
        if not _check_licenses_with_rat(
            artifact_path,
            rat_jar_path,
            report_name,
            summary,
            report_only,
        ):
            all_valid = False

    return all_valid


def _release_artifact_map(artifacts_dir: str) -> dict[str, list[str]]:
    artifacts = _artifact_files(artifacts_dir)
    return {
        "source": [name for name in artifacts if name.endswith("-src.tar.gz")],
        "sdist": [name for name in artifacts if name.endswith("-sdist.tar.gz")],
        "wheel": [name for name in artifacts if name.endswith(".whl")],
    }


def _extract_project_root(source_artifact: str, destination: str) -> Path:
    with tarfile.open(source_artifact, "r:gz") as tar:
        _safe_extract_tar(tar, destination)

    entries = [entry for entry in Path(destination).iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return Path(destination)


def _load_apache_release_module(project_root: Path):
    module_path = project_root / "scripts" / "apache_release.py"
    spec = importlib.util.spec_from_file_location("apache_release_for_verify", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load release helper from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_reproducible_wheel(
    project_root: Path, version: str, output_dir: str, source_epoch: int
) -> tuple[bool, str]:
    command = [
        sys.executable,
        "-c",
        (
            "import importlib.util, pathlib, sys; "
            "project_root = pathlib.Path(sys.argv[1]); "
            "version = sys.argv[2]; "
            "output_dir = sys.argv[3]; "
            "module_path = project_root / 'scripts' / 'apache_release.py'; "
            "spec = importlib.util.spec_from_file_location('apache_release_for_verify', module_path); "
            "module = importlib.util.module_from_spec(spec); "
            "spec.loader.exec_module(module); "
            "module._build_wheel_from_current_dir(version, output_dir)"
        ),
        str(project_root),
        version,
        output_dir,
    ]
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = str(source_epoch)
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        command,
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    output = "\n".join(item for item in [result.stdout, result.stderr] if item)
    return result.returncode == 0, output


def _build_reproducible_artifacts(source_artifact: str, output_dir: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        project_root = _extract_project_root(source_artifact, temp_dir)
        source_epoch = int(os.path.getmtime(source_artifact))
        version_match = re.search(r"(\d+\.\d+\.\d+)", os.path.basename(source_artifact))
        if version_match is None:
            return False, f"unable to determine version from {os.path.basename(source_artifact)}"
        version = version_match.group(1)

        dist_dir = os.path.join(project_root, "dist")
        if os.path.exists(dist_dir):
            shutil.rmtree(dist_dir)

        env = os.environ.copy()
        env["FLIT_USE_VCS"] = "0"
        env["SOURCE_DATE_EPOCH"] = str(source_epoch)
        env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
        sdist_result = subprocess.run(
            ["flit", "build", "--format", "sdist"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if sdist_result.returncode != 0:
            return False, sdist_result.stderr or sdist_result.stdout

        wheel_ok, wheel_output = _build_reproducible_wheel(
            project_root, version, output_dir, source_epoch
        )
        if not wheel_ok:
            return False, wheel_output

        os.makedirs(output_dir, exist_ok=True)
        for built_artifact in Path(dist_dir).glob("*"):
            shutil.copy2(built_artifact, Path(output_dir) / built_artifact.name)

        combined_output = "\n".join(
            item for item in [sdist_result.stdout, sdist_result.stderr, wheel_output] if item
        )
        return True, combined_output


def _compare_rebuilt_artifacts(
    artifacts_dir: str,
    rebuilt_dir: str,
    release_artifacts: dict[str, list[str]],
    summary: VerificationSummary,
) -> bool:
    all_valid = True

    if release_artifacts["sdist"]:
        release_sdist = os.path.join(artifacts_dir, release_artifacts["sdist"][0])
        rebuilt_sdists = sorted(glob.glob(os.path.join(rebuilt_dir, "*.tar.gz")))
        if not rebuilt_sdists:
            summary.fail("Rebuilt sdist checksum", "no rebuilt sdist produced")
            all_valid = False
        else:
            rebuilt_sdist = rebuilt_sdists[0]
            if _sha512_for_file(release_sdist) == _sha512_for_file(rebuilt_sdist):
                summary.pass_("Rebuilt sdist checksum", os.path.basename(rebuilt_sdist))
            else:
                summary.fail("Rebuilt sdist checksum", "rebuilt sdist differs from release")
                all_valid = False
    else:
        summary.skip("Rebuilt sdist checksum", "no release sdist found")

    if release_artifacts["wheel"]:
        release_wheels = [os.path.join(artifacts_dir, name) for name in release_artifacts["wheel"]]
        rebuilt_wheels = sorted(glob.glob(os.path.join(rebuilt_dir, "*.whl")))
        if len(rebuilt_wheels) != len(release_wheels):
            summary.fail(
                "Rebuilt wheel checksum",
                f"expected {len(release_wheels)} wheel(s), found {len(rebuilt_wheels)} rebuilt wheel(s)",
            )
            return False

        for release_wheel in release_wheels:
            release_name = os.path.basename(release_wheel)
            matching_wheels = [
                rebuilt for rebuilt in rebuilt_wheels if os.path.basename(rebuilt) == release_name
            ]
            if not matching_wheels:
                summary.fail(
                    f"Rebuilt wheel checksum: {release_name}", "matching rebuilt wheel not found"
                )
                all_valid = False
                continue
            rebuilt_wheel = matching_wheels[0]
            if _sha512_for_file(release_wheel) == _sha512_for_file(rebuilt_wheel):
                summary.pass_(f"Rebuilt wheel checksum: {release_name}")
            else:
                summary.fail(
                    f"Rebuilt wheel checksum: {release_name}", "rebuilt wheel differs from release"
                )
                all_valid = False
    else:
        summary.skip("Rebuilt wheel checksum", "no release wheel found")

    return all_valid


def verify_reproducible_build(
    artifacts_dir: str,
    summary: VerificationSummary | None = None,
) -> bool:
    _print_section("Verifying Reproducible Build")

    if summary is None:
        summary = VerificationSummary()

    if not os.path.exists(artifacts_dir):
        _fail(f"Artifacts directory not found: {artifacts_dir}")

    release_artifacts = _release_artifact_map(artifacts_dir)
    source_candidates = release_artifacts["source"] or release_artifacts["sdist"]
    if not source_candidates:
        summary.fail("Rebuild source artifact", "no source or sdist tarball found")
        return False

    if shutil.which("flit") is None:
        summary.fail("Reproducible rebuild", "flit is required to rebuild release artifacts")
        return False

    source_artifact = os.path.join(artifacts_dir, source_candidates[0])
    summary.pass_("Rebuild source artifact", os.path.basename(source_artifact))

    with tempfile.TemporaryDirectory() as rebuilt_dir:
        print(f"Rebuilding from: {os.path.basename(source_artifact)}")
        ok, output = _build_reproducible_artifacts(source_artifact, rebuilt_dir)
        if not ok:
            summary.fail("Reproducible rebuild", output.strip() or "build failed")
            return False

        summary.pass_("Reproducible rebuild", "build completed")
        return _compare_rebuilt_artifacts(artifacts_dir, rebuilt_dir, release_artifacts, summary)


def _extract_version_from_artifacts(artifacts_dir: str) -> str:
    version_pattern = re.compile(r"(\d+\.\d+\.\d+)")
    for artifact_name in _artifact_files(artifacts_dir):
        match = version_pattern.search(artifact_name)
        if match:
            return match.group(1)
    return "UNKNOWN_VERSION"


def render_vote_email(artifacts_dir: str, summary: VerificationSummary) -> str:
    version = _extract_version_from_artifacts(artifacts_dir)
    pass_count = sum(result.status == PASS for result in summary.results)
    fail_count = sum(result.status == FAIL for result in summary.results)
    skip_count = sum(result.status == SKIP for result in summary.results)
    vote = "+1" if summary.ok else "-1"

    result_lines = []
    for result in summary.results:
        result_lines.append(
            f"- [{result.status}] {result.name}" + (f": {result.details}" if result.details else "")
        )

    return textwrap.dedent(
        f"""\
        Subject: [{vote}] Release Apache Burr (incubating) {version}

        I verified the Apache Burr (incubating) {version} release artifacts.

        Verification summary:
        {os.linesep.join(result_lines)}

        Totals:
        - PASS: {pass_count}
        - FAIL: {fail_count}
        - SKIP: {skip_count}

        Vote:
        {vote} approve the release based on the checks above.
        """
    ).strip()


def _maybe_output_vote_email(args: argparse.Namespace, summary: VerificationSummary) -> None:
    if not getattr(args, "vote_email", False):
        return

    email_text = render_vote_email(args.artifacts_dir, summary)
    _print_section("Vote Email Draft")
    print(email_text)

    output_path = getattr(args, "vote_email_output", None)
    if output_path:
        Path(output_path).write_text(email_text + "\n", encoding="utf-8")
        print(f"\nSaved vote email draft to: {output_path}")


def _list_tar_gz_contents(artifact_path: str) -> None:
    print(f"\nContents of: {os.path.basename(artifact_path)}")
    print("=" * 80)

    try:
        with tarfile.open(artifact_path, "r:gz") as tar:
            members = tar.getmembers()
            print(f"Total files: {len(members)}\n")

            files = [member for member in members if member.isfile()]
            dirs = [member for member in members if member.isdir()]
            symlinks = [member for member in members if member.issym() or member.islnk()]
            print(f"Files: {len(files)}, Directories: {len(dirs)}, Symlinks: {len(symlinks)}\n")
            print("Files:\n")

            for member in members:
                size = f"{member.size:>12,}" if member.isfile() else "        <dir>"
                prefix = "  "
                if member.issym() or member.islnk():
                    prefix = "→ "
                    if member.linkname:
                        print(f"{prefix}{member.name} -> {member.linkname}")
                        continue
                print(f"{prefix}{member.name:<70} {size}")
    except Exception as exc:
        print(f"Error reading archive: {exc}")


def _list_wheel_contents(wheel_path: str) -> None:
    print(f"\nContents of: {os.path.basename(wheel_path)}")
    print("=" * 80)

    try:
        with zipfile.ZipFile(wheel_path, "r") as wheel:
            file_list = wheel.namelist()
            print(f"Total files: {len(file_list)}\n")

            top_level_dirs: dict[str, int] = {}
            for file_name in file_list:
                top_dir = file_name.split("/")[0]
                top_level_dirs[top_dir] = top_level_dirs.get(top_dir, 0) + 1

            print("Top-level structure:")
            for dir_name, count in sorted(top_level_dirs.items()):
                print(f"  {dir_name:<50} ({count} files)")

            print("\nFiles:\n")
            for filename in sorted(file_list):
                info = wheel.getinfo(filename)
                size = f"{info.file_size:>12,}" if not filename.endswith("/") else "        <dir>"
                print(f"  {filename:<70} {size}")
    except Exception as exc:
        print(f"Error reading wheel: {exc}")


def list_contents(artifact_path: str) -> None:
    _print_section("Listing Artifact Contents")

    if not os.path.exists(artifact_path):
        _fail(f"Artifact not found: {artifact_path}")

    if artifact_path.endswith(".tar.gz"):
        _list_tar_gz_contents(artifact_path)
    elif artifact_path.endswith(".whl"):
        _list_wheel_contents(artifact_path)
    else:
        _fail(f"Unsupported file type: {artifact_path}\nSupported: .tar.gz, .whl")


def cmd_signatures(args: argparse.Namespace) -> bool:
    summary = VerificationSummary()
    verify_signatures(args.artifacts_dir, summary)
    _print_section("Verification Summary")
    print(summary.render())
    return summary.ok


def cmd_artifacts(args: argparse.Namespace) -> bool:
    summary = VerificationSummary()
    verify_artifact_contents(args.artifacts_dir, summary)
    _print_section("Verification Summary")
    print(summary.render())
    return summary.ok


def cmd_licenses(args: argparse.Namespace) -> bool:
    if not args.rat_jar:
        _fail("--rat-jar is required for license verification")

    summary = VerificationSummary()
    verify_licenses(args.artifacts_dir, args.rat_jar, summary, args.report_only)
    _print_section("Verification Summary")
    print(summary.render())
    return summary.ok


def cmd_reproducible(args: argparse.Namespace) -> bool:
    summary = VerificationSummary()
    verify_reproducible_build(args.artifacts_dir, summary)
    _print_section("Verification Summary")
    print(summary.render())
    _maybe_output_vote_email(args, summary)
    return summary.ok


def cmd_all(args: argparse.Namespace) -> bool:
    _print_section("Complete Apache Artifacts Verification")
    summary = VerificationSummary()

    print("\n[1/4] Verifying signatures and checksums...")
    verify_signatures(args.artifacts_dir, summary)

    print("\n[2/4] Verifying required metadata files...")
    verify_artifact_contents(args.artifacts_dir, summary)

    print("\n[3/4] Verifying reproducible rebuild...")
    verify_reproducible_build(args.artifacts_dir, summary)

    if args.rat_jar:
        print("\n[4/4] Verifying licenses with Apache RAT...")
        verify_licenses(args.artifacts_dir, args.rat_jar, summary, args.report_only)
    else:
        summary.skip("Apache RAT", "no --rat-jar provided")

    _print_section("Verification Summary")
    print(summary.render())
    _maybe_output_vote_email(args, summary)
    return summary.ok


def cmd_list_contents(args: argparse.Namespace) -> None:
    list_contents(args.artifact)


def cmd_twine_check(args: argparse.Namespace) -> bool:
    _print_section("Verifying Wheel Metadata with Twine")

    summary = VerificationSummary()
    wheel_pattern = f"{args.artifacts_dir}/apache_burr-*.whl"
    wheel_files = glob.glob(wheel_pattern)

    if not wheel_files:
        print(f"❌ No wheel found matching: {wheel_pattern}")
        summary.fail("Twine metadata check", "no wheel found")
        _print_section("Verification Summary")
        print(summary.render())
        return False

    for wheel_path in wheel_files:
        print(f"\nChecking {os.path.basename(wheel_path)}...")
        try:
            subprocess.run(
                ["twine", "check", wheel_path],
                check=True,
                capture_output=True,
                text=True,
            )
            print(f"  ✓ {os.path.basename(wheel_path)} metadata is valid")
            summary.pass_(f"Twine metadata: {os.path.basename(wheel_path)}")
        except subprocess.CalledProcessError as exc:
            print(f"  ✗ Twine check failed: {exc.stderr}")
            summary.fail(f"Twine metadata: {os.path.basename(wheel_path)}", exc.stderr.strip())

    _print_section("Verification Summary")
    print(summary.render())
    return summary.ok


def _add_vote_email_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--vote-email",
        action="store_true",
        help="Render a vote email draft using the collected verification results",
    )
    parser.add_argument(
        "--vote-email-output",
        help="Optional path to write the generated vote email draft",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apache Artifacts Verification Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/verify_apache_artifacts.py list-contents dist/apache-burr-0.41.0-incubating-src.tar.gz
  python scripts/verify_apache_artifacts.py signatures
  python scripts/verify_apache_artifacts.py artifacts
  python scripts/verify_apache_artifacts.py reproducible
  python scripts/verify_apache_artifacts.py licenses --rat-jar /path/to/apache-rat.jar
  python scripts/verify_apache_artifacts.py all --rat-jar /path/to/apache-rat.jar --vote-email
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list-contents", help="List contents of a specific artifact"
    )
    list_parser.add_argument("artifact", help="Path to artifact file (.tar.gz or .whl)")

    sig_parser = subparsers.add_parser(
        "signatures", help="Verify GPG signatures and SHA512 checksums"
    )
    sig_parser.add_argument(
        "--artifacts-dir", default="dist", help="Directory containing artifacts (default: dist)"
    )

    artifacts_parser = subparsers.add_parser(
        "artifacts",
        help="Verify required LICENSE/NOTICE/DISCLAIMER metadata in artifacts",
    )
    artifacts_parser.add_argument(
        "--artifacts-dir", default="dist", help="Directory containing artifacts (default: dist)"
    )

    lic_parser = subparsers.add_parser("licenses", help="Verify licenses with Apache RAT")
    lic_parser.add_argument(
        "--artifacts-dir", default="dist", help="Directory containing artifacts (default: dist)"
    )
    lic_parser.add_argument("--rat-jar", required=True, help="Path to Apache RAT JAR file")
    lic_parser.add_argument(
        "--report-only", action="store_true", help="Generate report but don't fail on issues"
    )

    reproducible_parser = subparsers.add_parser(
        "reproducible",
        help="Rebuild from release source and compare rebuilt artifacts against release artifacts",
    )
    reproducible_parser.add_argument(
        "--artifacts-dir", default="dist", help="Directory containing artifacts (default: dist)"
    )
    _add_vote_email_args(reproducible_parser)

    all_parser = subparsers.add_parser(
        "all",
        help="Verify signatures, metadata files, reproducibility, and optionally Apache RAT results",
    )
    all_parser.add_argument(
        "--artifacts-dir", default="dist", help="Directory containing artifacts (default: dist)"
    )
    all_parser.add_argument("--rat-jar", help="Path to Apache RAT JAR file (optional)")
    all_parser.add_argument(
        "--report-only", action="store_true", help="Generate report but don't fail on RAT issues"
    )
    _add_vote_email_args(all_parser)

    twine_parser = subparsers.add_parser("twine-check", help="Verify wheel metadata with twine")
    twine_parser.add_argument(
        "--artifacts-dir", default="dist", help="Directory containing artifacts (default: dist)"
    )

    args = parser.parse_args()

    success = False
    try:
        if args.command == "list-contents":
            cmd_list_contents(args)
            sys.exit(0)
        if args.command == "signatures":
            success = cmd_signatures(args)
        elif args.command == "artifacts":
            success = cmd_artifacts(args)
        elif args.command == "licenses":
            success = cmd_licenses(args)
        elif args.command == "reproducible":
            success = cmd_reproducible(args)
        elif args.command == "all":
            success = cmd_all(args)
        elif args.command == "twine-check":
            success = cmd_twine_check(args)
        else:
            _fail(f"Unknown command: {args.command}")
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as exc:
        print(f"\n❌ Unexpected error: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    if success:
        print("\n✅ Verification completed successfully!")
        sys.exit(0)

    print("\n❌ Verification failed.")
    sys.exit(1)


if __name__ == "__main__":
    main()
