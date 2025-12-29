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
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
Apache Burr Release Script

This script automates the Apache release process with three distinct build steps:
1. Package entire repo (git archive) -> tar.gz for voting
2. Build source distribution (sdist) from tar.gz
3. Build wheel from sdist

Each step produces signed artifacts (GPG + SHA512) that can be uploaded to Apache SVN.

Usage:
    # Full release workflow
    python scripts/apache_release.py all 0.41.0 0 myid

    # Step-by-step workflow
    python scripts/apache_release.py archive 0.41.0 0 --check-licenses
    python scripts/apache_release.py sdist 0.41.0 0
    python scripts/apache_release.py wheel 0.41.0 0
    python scripts/apache_release.py verify 0.41.0 0
    python scripts/apache_release.py upload 0.41.0 0 myid

    # Rebuild just the wheel
    python scripts/apache_release.py wheel 0.41.0 0

    # Dry run
    python scripts/apache_release.py all 0.41.0 0 myid --dry-run

Subcommands:
    archive - Create git archive (voting artifact)
    sdist   - Build source distribution from archive
    wheel   - Build wheel from sdist
    upload  - Upload artifacts to Apache SVN
    all     - Run complete workflow (archive → sdist → wheel → upload)
    verify  - Verify existing artifacts
"""

import argparse
import glob
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from typing import NoReturn, Optional

# These will be used when implementing TODO functions:
# from pathlib import Path

# --- Configuration ---
PROJECT_SHORT_NAME = "burr"
VERSION_FILE = "pyproject.toml"
VERSION_PATTERN = r'version\s*=\s*"(\d+\.\d+\.\d+)"'

# Required examples for sdist and wheel (from pyproject.toml)
REQUIRED_EXAMPLES = [
    "__init__.py",
    "email-assistant",
    "multi-modal-chatbot",
    "streaming-fastapi",
    "deep-researcher",
]


# ============================================================================
# Utility Functions
# ============================================================================


def _fail(message: str) -> NoReturn:
    """Print error message and exit."""
    print(f"\n❌ {message}")
    sys.exit(1)


def _print_section(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def _print_step(step_num: int, total: int, description: str) -> None:
    """Print a formatted step header."""
    print(f"\n[Step {step_num}/{total}] {description}")
    print("-" * 80)


# ============================================================================
# Environment Validation
# ============================================================================


def _validate_environment_for_command(args) -> None:
    """Validate that all required tools are available for the requested command.

    This is called once at the start, after argument parsing but before any command execution.
    It checks all tools needed for the command and fails fast with clear error messages.

    Args:
        args: Parsed command-line arguments (argparse.Namespace)

    Raises:
        SystemExit: If any required tools are missing

    Assumptions:
        - Called after argparse has parsed arguments
        - Checks tools based on args.command
        - Different commands require different tool sets
    """
    print("\n" + "=" * 80)
    print("  Environment Validation")
    print("=" * 80 + "\n")

    # Define required tools for each command
    command_requirements = {
        "archive": ["git", "gpg"],
        "sdist": ["git", "gpg", "flit"],
        "wheel": ["git", "gpg", "flit", "node", "npm"],
        "upload": ["git", "gpg", "svn"],
        "all": ["git", "gpg", "flit", "node", "npm", "svn"],
        "verify": ["git", "gpg"],
    }

    # Get required tools for this command
    required_tools = command_requirements.get(args.command, ["git", "gpg"])

    # Check for RAT if needed (for archive or all commands)
    check_rat = False
    if hasattr(args, "check_licenses") or hasattr(args, "check_licenses_report"):
        check_rat = getattr(args, "check_licenses", False) or getattr(
            args, "check_licenses_report", False
        )

    if check_rat:
        required_tools.append("java")  # RAT requires Java

    # Check each required tool
    missing_tools = []
    print("Checking required tools:")

    for tool in required_tools:
        if shutil.which(tool) is None:
            missing_tools.append(tool)
            print(f"  ✗ '{tool}' not found")
        else:
            print(f"  ✓ '{tool}' found")

    # Check RAT JAR if needed
    if check_rat:
        rat_jar = getattr(args, "rat_jar", None)
        if not rat_jar:
            print(
                "  ✗ --rat-jar is required when using --check-licenses or --check-licenses-report"
            )
            missing_tools.append("rat-jar (argument)")
        elif not os.path.exists(rat_jar):
            print(f"  ✗ Apache RAT JAR not found at: {rat_jar}")
            missing_tools.append("rat-jar (file)")
        else:
            print(f"  ✓ Apache RAT JAR found: {rat_jar}")

    # Fail if any tools are missing
    if missing_tools:
        print("\n❌ Missing required tools:\n")
        for tool in missing_tools:
            if tool == "flit":
                print(f"  • {tool}: Install with 'pip install flit'")
            elif tool in ["node", "npm"]:
                print(f"  • {tool}: Install Node.js from https://nodejs.org/")
            elif tool == "svn":
                print(f"  • {tool}: Install with your system package manager")
            elif tool == "java":
                print(f"  • {tool}: Required for Apache RAT - install JDK")
            else:
                print(f"  • {tool}")

        sys.exit(1)

    print("\n✓ All required tools are available\n")


# ============================================================================
# Prerequisite Checks
# ============================================================================


def _check_prerequisites(check_rat: bool = False, rat_jar_path: Optional[str] = None) -> bool:
    """Check for required command-line tools.

    Args:
        check_rat: If True, also check for Apache RAT tool
        rat_jar_path: Path to RAT JAR file (required if check_rat is True)

    Returns:
        True if all prerequisites met, False otherwise
    """
    print("Checking for required tools...")

    required_tools = ["git", "gpg"]
    missing_tools = []

    for tool in required_tools:
        if shutil.which(tool) is None:
            missing_tools.append(tool)
            print(f"  ✗ '{tool}' not found")
        else:
            print(f"  ✓ '{tool}' found")

    if check_rat:
        # Check for java
        if shutil.which("java") is None:
            missing_tools.append("java")
            print("  ✗ 'java' not found (required for Apache RAT)")
        else:
            print("  ✓ 'java' found")

        # Check RAT JAR exists
        if rat_jar_path and not os.path.exists(rat_jar_path):
            print(f"  ✗ Apache RAT JAR not found at: {rat_jar_path}")
            return False
        elif rat_jar_path:
            print(f"  ✓ Apache RAT JAR found: {rat_jar_path}")

    if missing_tools:
        _fail(f"Missing required tools: {', '.join(missing_tools)}")

    print("  ✓ All required tools found\n")
    return True


def _verify_project_root() -> bool:
    """Verify script is running from project root.

    Returns:
        True if in project root, False otherwise
    """
    if not os.path.exists("pyproject.toml"):
        _fail("pyproject.toml not found. Please run this script from the project root.")
    return True


def _get_version_from_file(file_path: str) -> str:
    """Extract version from pyproject.toml.

    Args:
        file_path: Path to pyproject.toml

    Returns:
        Version string (e.g., "0.41.0")
    """
    import re

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    match = re.search(VERSION_PATTERN, content)
    if match:
        return match.group(1)

    _fail(f"Could not find version in {file_path}")


def _validate_version(requested_version: str) -> bool:
    """Validate that requested version matches pyproject.toml.

    Args:
        requested_version: Version string requested by user

    Returns:
        True if versions match, False otherwise
    """
    current_version = _get_version_from_file(VERSION_FILE)

    if current_version != requested_version:
        _fail(
            f"Version mismatch!\n"
            f"  Requested: {requested_version}\n"
            f"  In {VERSION_FILE}: {current_version}\n"
            f"Please update {VERSION_FILE} to {requested_version} before running this script."
        )

    print(f"✓ Version validated: {requested_version}\n")
    return True


def _check_git_working_tree() -> None:
    """Check git working tree status and warn if dirty."""
    try:
        dirty = (
            subprocess.check_output(["git", "status", "--porcelain"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
        if dirty:
            print("⚠️  Warning: Git working tree has uncommitted changes:")
            for line in dirty.splitlines()[:10]:  # Show first 10 lines
                print(f"     {line}")
            if len(dirty.splitlines()) > 10:
                print(f"     ... and {len(dirty.splitlines()) - 10} more files")
            print()
    except subprocess.CalledProcessError:
        # If git status fails, just continue
        pass


# ============================================================================
# Git Operations
# ============================================================================


def _create_or_verify_git_tag(version: str, rc_num: str, dry_run: bool) -> bool:
    """Create or verify RC git tag.

    Args:
        version: Version string (e.g., "0.41.0")
        rc_num: RC number (e.g., "0")
        dry_run: If True, don't actually create tag

    Returns:
        True if tag created/verified, False otherwise
    """
    # TODO: Check if tag exists, prompt user if it does, create if not
    return True


# ============================================================================
# Signing and Verification
# ============================================================================


def _sign_artifact(artifact_path: str) -> tuple[str, str]:
    """Sign artifact with GPG and create SHA512 checksum.

    Args:
        artifact_path: Path to artifact to sign

    Returns:
        Tuple of (signature_path, checksum_path)
    """
    signature_path = f"{artifact_path}.asc"
    checksum_path = f"{artifact_path}.sha512"

    # Sign the artifact with GPG
    try:
        subprocess.run(
            ["gpg", "--armor", "--output", signature_path, "--detach-sig", artifact_path],
            check=True,
        )
        print(f"  ✓ Created GPG signature: {signature_path}")
    except subprocess.CalledProcessError as e:
        _fail(f"Error signing artifact {artifact_path}: {e}")

    # Generate SHA512 checksum
    sha512_hash = hashlib.sha512()
    with open(artifact_path, "rb") as f:
        while True:
            data = f.read(65536)  # Read in 64kb chunks
            if not data:
                break
            sha512_hash.update(data)

    with open(checksum_path, "w", encoding="utf-8") as f:
        f.write(f"{sha512_hash.hexdigest()}\n")
    print(f"  ✓ Created SHA512 checksum: {checksum_path}")

    return (signature_path, checksum_path)


def _verify_artifact_signature(artifact_path: str, signature_path: str) -> bool:
    """Verify GPG signature of artifact.

    Args:
        artifact_path: Path to artifact
        signature_path: Path to .asc signature

    Returns:
        True if signature valid, False otherwise
    """
    print(f"  Verifying GPG signature: {signature_path}")

    if not os.path.exists(signature_path):
        print(f"    ✗ Signature file not found: {signature_path}")
        return False

    try:
        result = subprocess.run(
            ["gpg", "--verify", signature_path, artifact_path],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            print("    ✓ GPG signature is valid")
            return True
        else:
            print("    ✗ GPG signature verification failed")
            print(f"    Error: {result.stderr}")
            return False
    except subprocess.CalledProcessError as e:
        print(f"    ✗ Error verifying signature: {e}")
        return False


def _verify_artifact_checksum(artifact_path: str, checksum_path: str) -> bool:
    """Verify SHA512 checksum of artifact.

    Args:
        artifact_path: Path to artifact
        checksum_path: Path to .sha512 checksum

    Returns:
        True if checksum matches, False otherwise
    """
    print(f"  Verifying SHA512 checksum: {checksum_path}")

    if not os.path.exists(checksum_path):
        print(f"    ✗ Checksum file not found: {checksum_path}")
        return False

    # Read expected checksum from file
    try:
        with open(checksum_path, "r", encoding="utf-8") as f:
            expected_checksum = (
                f.read().strip().split()[0]
            )  # Take first token (handle "hash filename" format)
    except Exception as e:
        print(f"    ✗ Error reading checksum file: {e}")
        return False

    # Calculate actual checksum
    sha512_hash = hashlib.sha512()
    try:
        with open(artifact_path, "rb") as f:
            while True:
                data = f.read(65536)  # Read in 64kb chunks
                if not data:
                    break
                sha512_hash.update(data)

        actual_checksum = sha512_hash.hexdigest()

        if actual_checksum == expected_checksum:
            print("    ✓ SHA512 checksum is valid")
            return True
        else:
            print("    ✗ SHA512 checksum mismatch!")
            print(f"    Expected: {expected_checksum}")
            print(f"    Actual:   {actual_checksum}")
            return False
    except Exception as e:
        print(f"    ✗ Error calculating checksum: {e}")
        return False


# ============================================================================
# Artifact Verification Helpers
# ============================================================================


def _verify_artifact_exists(artifact_path: str, min_size: int = 1000) -> bool:
    """Verify artifact exists and has reasonable size.

    Args:
        artifact_path: Path to artifact
        min_size: Minimum expected file size in bytes (default: 1KB)

    Returns:
        True if artifact exists and has content, False otherwise
    """
    print("  Checking artifact exists and has content...")

    if not os.path.exists(artifact_path):
        print(f"    ✗ Artifact not found: {artifact_path}")
        return False

    file_size = os.path.getsize(artifact_path)
    if file_size < min_size:
        print(f"    ✗ Artifact is too small ({file_size} bytes): {artifact_path}")
        return False

    print(f"    ✓ Artifact exists: {artifact_path} ({file_size:,} bytes)")
    return True


def _verify_tar_gz_readable(artifact_path: str) -> bool:
    """Verify tar.gz archive can be read and contains files.

    Args:
        artifact_path: Path to tar.gz archive

    Returns:
        True if archive is readable and contains files, False otherwise
    """
    print("  Checking archive can be read...")

    try:
        with tarfile.open(artifact_path, "r:gz") as tar:
            members = tar.getmembers()

            if len(members) == 0:
                print("    ✗ Archive is empty (no files)")
                return False

            print(f"    ✓ Archive is readable and contains {len(members)} files")
            return True
    except tarfile.TarError as e:
        print(f"    ✗ Archive is corrupted or unreadable: {e}")
        return False
    except Exception as e:
        print(f"    ✗ Error reading archive: {e}")
        return False


def _verify_artifact_complete(artifact_path: str, check_tar: bool = True) -> bool:
    """Verify artifact and its signature/checksum files.

    Args:
        artifact_path: Path to artifact
        check_tar: If True and artifact is .tar.gz, verify it's readable

    Returns:
        True if artifact and signatures are valid, False otherwise
    """
    print(f"\nVerifying artifact: {os.path.basename(artifact_path)}")

    # Check artifact exists
    if not _verify_artifact_exists(artifact_path):
        return False

    # If it's a tar.gz, verify it can be read
    if check_tar and artifact_path.endswith(".tar.gz"):
        if not _verify_tar_gz_readable(artifact_path):
            return False

    # Verify signature
    signature_path = f"{artifact_path}.asc"
    if not _verify_artifact_signature(artifact_path, signature_path):
        return False

    # Verify checksum
    checksum_path = f"{artifact_path}.sha512"
    if not _verify_artifact_checksum(artifact_path, checksum_path):
        return False

    print(f"  ✓ All checks passed for {os.path.basename(artifact_path)}\n")
    return True


# ============================================================================
# License Checking (RAT)
# ============================================================================


def _check_licenses_with_rat(
    artifact_path: str,
    rat_jar_path: str,
    version: str,
    rc_num: str,
    stage: str = "archive",
    report_only: bool = False,
) -> bool:
    """Run Apache RAT license checker on artifact.

    Args:
        artifact_path: Path to tar.gz to check
        rat_jar_path: Path to Apache RAT JAR file (e.g., /path/to/apache-rat-0.15.jar)
        version: Release version (e.g., "0.41.0")
        rc_num: RC number (e.g., "0")
        stage: Stage name (e.g., "archive", "sdist") for report naming
        report_only: If True, report issues but don't fail

    Returns:
        True if licenses OK (or report_only=True), False if issues found
    """
    print(f"Running Apache RAT on {os.path.basename(artifact_path)}...")

    # Create output directory for reports (in dist/)
    report_dir = "dist"
    os.makedirs(report_dir, exist_ok=True)

    # Name reports with stage, version, and RC number
    rat_report_xml = os.path.join(report_dir, f"rat-report-{stage}-{version}-rc{rc_num}.xml")
    rat_report_txt = os.path.join(report_dir, f"rat-report-{stage}-{version}-rc{rc_num}.txt")

    # Create temp directory for extraction
    with tempfile.TemporaryDirectory() as temp_dir:
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir)

        # Extract tar.gz
        print("  Extracting archive to temp directory...")
        try:
            with tarfile.open(artifact_path, "r:gz") as tar:
                tar.extractall(extract_dir)
            print(f"    ✓ Extracted to {extract_dir}")
        except Exception as e:
            print(f"    ✗ Error extracting archive: {e}")
            return False

        # Locate .rat-excludes file (should be in project root)
        rat_excludes = ".rat-excludes"
        if not os.path.exists(rat_excludes):
            print(f"    ⚠️  Warning: {rat_excludes} not found, running RAT without excludes")
            rat_excludes = None

        # Run RAT with XML output (for parsing)
        print("  Running Apache RAT (XML format for parsing)...")

        rat_cmd_xml = [
            "java",
            "-jar",
            rat_jar_path,
            "-x",  # XML output
            "-d",
            extract_dir,  # Directory to scan
        ]
        if rat_excludes:
            rat_cmd_xml.extend(["-E", rat_excludes])

        try:
            with open(rat_report_xml, "w", encoding="utf-8") as report_file:
                result = subprocess.run(
                    rat_cmd_xml,
                    stdout=report_file,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )

            if result.returncode != 0:
                print(f"    ⚠️  RAT exited with code {result.returncode}")
                if result.stderr:
                    print(f"    Stderr: {result.stderr}")

            print(f"    ✓ RAT XML report: {rat_report_xml}")
        except Exception as e:
            print(f"    ✗ Error running RAT (XML): {e}")
            return False

        # Run RAT with plain text output (for human review)
        print("  Running Apache RAT (plain text format for review)...")

        rat_cmd_txt = [
            "java",
            "-jar",
            rat_jar_path,
            "-d",
            extract_dir,  # Directory to scan
        ]
        if rat_excludes:
            rat_cmd_txt.extend(["-E", rat_excludes])

        try:
            with open(rat_report_txt, "w", encoding="utf-8") as report_file:
                result = subprocess.run(
                    rat_cmd_txt,
                    stdout=report_file,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )

            print(f"    ✓ RAT text report: {rat_report_txt}")
        except Exception as e:
            print(f"    ⚠️  Warning: Could not generate text report: {e}")

        # Parse XML report
        print("  Parsing RAT report...")
        try:
            tree = ET.parse(rat_report_xml)
            root = tree.getroot()

            # Find all resource elements with license issues
            # RAT XML structure typically has <resource> elements with license info
            unapproved_licenses = []
            unknown_licenses = []

            for resource in root.findall(".//resource"):
                name = resource.get("name", "unknown")
                license_approval = resource.get("license-approval", "true")
                license_family = resource.get("license-family-name", "")

                # Check if license is not approved
                if license_approval == "false" or license_family == "Unknown":
                    if license_family == "Unknown" or not license_family:
                        unknown_licenses.append(name)
                    else:
                        unapproved_licenses.append(name)

            # Get summary statistics
            total_files = len(root.findall(".//resource"))
            issues_count = len(unapproved_licenses) + len(unknown_licenses)

            print(f"    ✓ Scanned {total_files} files")
            print(f"    ✓ Found {issues_count} files with license issues")

            # Report findings
            if issues_count > 0:
                print("\n  ⚠️  License Issues Found:")

                if unknown_licenses:
                    print(f"\n    Unknown/Missing Licenses ({len(unknown_licenses)} files):")
                    for file in unknown_licenses[:10]:  # Show first 10
                        print(f"      - {file}")
                    if len(unknown_licenses) > 10:
                        print(f"      ... and {len(unknown_licenses) - 10} more")

                if unapproved_licenses:
                    print(f"\n    Unapproved Licenses ({len(unapproved_licenses)} files):")
                    for file in unapproved_licenses[:10]:  # Show first 10
                        print(f"      - {file}")
                    if len(unapproved_licenses) > 10:
                        print(f"      ... and {len(unapproved_licenses) - 10} more")

                print("\n    📄 Reports saved:")
                print(f"       - {rat_report_xml} (structured)")
                print(f"       - {rat_report_txt} (human-readable)")

                if report_only:
                    print("\n  ℹ️  Report-only mode: continuing despite license issues")
                    return True
                else:
                    print("\n  ❌ License check failed!")
                    return False
            else:
                print("    ✅ All files have approved licenses")
                print("\n    📄 Reports saved:")
                print(f"       - {rat_report_xml} (structured)")
                print(f"       - {rat_report_txt} (human-readable)")
                return True

        except Exception as e:
            print(f"    ✗ Error parsing RAT report: {e}")
            if report_only:
                print("    ℹ️  Report-only mode: continuing despite parse error")
                return True
            return False


# ============================================================================
# Step 1: Git Archive (Voting Artifact)
# ============================================================================


def _create_git_archive(version: str, rc_num: str, output_dir: str = "dist") -> str:
    """Create git archive tar.gz for voting.

    This creates a snapshot of the entire repository from git HEAD.
    The archive includes all files tracked by git (respecting .gitignore).

    Args:
        version: Version string (e.g., "0.41.0")
        rc_num: RC number (e.g., "0")
        output_dir: Directory to write artifact to

    Returns:
        Path to created tar.gz file
    """
    print(f"Creating git archive for version {version}-incubating...")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Define output path
    archive_name = f"apache-burr-{version}-incubating-src.tar.gz"
    archive_path = os.path.join(output_dir, archive_name)

    # Run git archive
    # The prefix ensures all files are under apache-burr-{version}-incubating-src/ when extracted
    prefix = f"apache-burr-{version}-incubating-src/"

    try:
        subprocess.run(
            [
                "git",
                "archive",
                "HEAD",
                f"--prefix={prefix}",
                "--format=tar.gz",
                "--output",
                archive_path,
            ],
            check=True,
        )
        print(f"  ✓ Created git archive: {archive_path}")
    except subprocess.CalledProcessError as e:
        _fail(f"Error creating git archive: {e}")

    # Verify the archive was created and has content
    if not os.path.exists(archive_path):
        _fail(f"Git archive was not created at {archive_path}")

    file_size = os.path.getsize(archive_path)
    if file_size == 0:
        _fail(f"Git archive is empty: {archive_path}")

    print(f"  ✓ Archive size: {file_size:,} bytes")

    # Sign the archive
    print("Signing archive...")
    _sign_artifact(archive_path)

    # Verify the archive and signatures
    print("Verifying archive...")
    if not _verify_artifact_complete(archive_path):
        _fail("Archive verification failed!")

    return archive_path


def _verify_git_archive(archive_path: str) -> bool:
    """Verify git archive contents are correct.

    Args:
        archive_path: Path to tar.gz archive

    Returns:
        True if archive contents valid, False otherwise
    """
    # TODO: Extract and verify no node_modules, build artifacts, etc.
    return True


# ============================================================================
# Step 2: Build Source Distribution (sdist)
# ============================================================================


def _remove_ui_build_artifacts() -> None:
    """Remove pre-built UI artifacts to ensure clean build."""
    ui_build_dir = os.path.join("burr", "tracking", "server", "build")
    if os.path.exists(ui_build_dir):
        print(f"  Removing UI build artifacts: {ui_build_dir}")
        shutil.rmtree(ui_build_dir)
        print("    ✓ UI build artifacts removed")
    else:
        print("    ✓ No UI build artifacts to remove")


def _build_sdist_from_git(version: str, output_dir: str = "dist") -> str:
    """Build source distribution from git repository using flit.

    The sdist includes only files specified in pyproject.toml [tool.flit.sdist].
    This builds directly from git (not from the git archive tar.gz).

    Args:
        version: Version string (e.g., "0.41.0")
        output_dir: Directory to write sdist to

    Returns:
        Path to created sdist tar.gz file
    """
    _print_step(1, 3, "Building sdist with flit")

    # Ensure output directory exists (but don't clean it - artifacts accumulate)
    os.makedirs(output_dir, exist_ok=True)

    # Remove UI build artifacts
    _remove_ui_build_artifacts()

    # Check git working tree
    _check_git_working_tree()

    # Build sdist with flit
    print("  Running flit build --format sdist...")
    try:
        env = os.environ.copy()
        env["FLIT_USE_VCS"] = "0"  # Don't rely on VCS for file inclusion
        subprocess.run(
            ["flit", "build", "--format", "sdist"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        print("    ✓ flit sdist created successfully")
    except subprocess.CalledProcessError as e:
        print(f"    ✗ Error creating sdist: {e}")
        print(f"    Stdout: {e.stdout}")
        print(f"    Stderr: {e.stderr}")
        _fail("Failed to build sdist")

    # Find the created sdist (flit normalizes hyphens to underscores)
    print("  Locating created sdist...")
    expected_pattern = f"dist/apache_burr-{version.lower()}.tar.gz"
    sdist_files = glob.glob(expected_pattern)

    if not sdist_files:
        print(f"    ✗ Could not find: {expected_pattern}")
        if os.path.exists("dist"):
            print("    Contents of dist/:")
            for item in os.listdir("dist"):
                print(f"      - {item}")
        _fail("Failed to locate sdist file")

    # Rename to Apache naming convention (with -src-sdist to distinguish from git archive)
    original_sdist = sdist_files[0]
    apache_sdist = os.path.join(
        output_dir, f"apache-burr-{version.lower()}-incubating-src-sdist.tar.gz"
    )

    if os.path.exists(apache_sdist):
        print(f"  Removing existing sdist: {apache_sdist}")
        os.remove(apache_sdist)

    shutil.move(original_sdist, apache_sdist)
    print(f"    ✓ Renamed to: {os.path.basename(apache_sdist)}")

    return apache_sdist


def _verify_sdist(sdist_path: str) -> bool:
    """Verify sdist contents are correct.

    Args:
        sdist_path: Path to sdist tar.gz

    Returns:
        True if sdist contents valid, False otherwise
    """
    # TODO:
    # 1. Extract and verify structure
    # 2. Check for required files (LICENSE, NOTICE, DISCLAIMER, scripts/, etc.)
    # 3. Check for only 4 required examples
    # 4. Verify no built UI artifacts
    return True


# ============================================================================
# Step 3: Build Wheel from sdist
# ============================================================================


def _extract_sdist(sdist_path: str, extract_dir: str) -> str:
    """Extract sdist tar.gz to directory.

    Args:
        sdist_path: Path to sdist tar.gz file
        extract_dir: Directory to extract to

    Returns:
        Path to extracted source directory (the top-level directory inside the tarball)

    Assumptions:
        - sdist is a valid tar.gz file
        - sdist contains a single top-level directory
        - extract_dir exists or can be created
    """
    print(f"  Extracting sdist: {os.path.basename(sdist_path)}")

    os.makedirs(extract_dir, exist_ok=True)

    try:
        with tarfile.open(sdist_path, "r:gz") as tar:
            tar.extractall(extract_dir)

        # Find the extracted directory (should be single top-level dir)
        extracted_contents = os.listdir(extract_dir)
        if len(extracted_contents) != 1:
            _fail(f"Expected single directory in sdist, found {len(extracted_contents)} items")

        source_dir = os.path.join(extract_dir, extracted_contents[0])
        if not os.path.isdir(source_dir):
            _fail(f"Expected directory in sdist, found file: {extracted_contents[0]}")

        print(f"    ✓ Extracted to: {source_dir}")
        return source_dir

    except Exception as e:
        _fail(f"Error extracting sdist: {e}")


def _create_isolated_venv_uv(venv_dir: str) -> tuple[str, str]:
    """Create isolated virtual environment using uv.

    Args:
        venv_dir: Directory to create venv in

    Returns:
        Tuple of (python_path, pip_path) for the isolated environment

    Assumptions:
        - uv is installed and available in PATH
        - venv_dir does not exist yet
    """
    print("  Creating isolated build environment with uv...")

    try:
        subprocess.run(["uv", "venv", venv_dir], check=True, capture_output=True)
        print(f"    ✓ Created isolated venv: {venv_dir}")
    except subprocess.CalledProcessError as e:
        _fail(f"Error creating venv with uv: {e}\nStderr: {e.stderr.decode()}")

    # Determine paths based on platform
    if sys.platform == "win32":
        python_path = os.path.join(venv_dir, "Scripts", "python.exe")
        pip_path = "uv pip"  # uv pip command works globally
    else:
        python_path = os.path.join(venv_dir, "bin", "python")
        pip_path = "uv pip"  # uv pip command works globally

    if not os.path.exists(python_path):
        _fail(f"Python executable not found in venv: {python_path}")

    print(f"    ✓ Python: {python_path}")
    return python_path, pip_path


def _handle_symlinks_for_wheel(work_dir: str) -> dict:
    """Replace symlinks with copies and track for restoration.

    Args:
        work_dir: Working directory containing examples/

    Returns:
        Dictionary mapping path -> (was_symlink, original_target, is_dir)

    Assumptions:
        - work_dir contains an examples/ directory
        - Symlinks (if any) point to valid targets
        - We only care about the 4 required example directories
    """
    example_paths = [
        os.path.join(work_dir, "examples", "__init__.py"),
        os.path.join(work_dir, "examples", "email-assistant"),
        os.path.join(work_dir, "examples", "multi-modal-chatbot"),
        os.path.join(work_dir, "examples", "streaming-fastapi"),
        os.path.join(work_dir, "examples", "deep-researcher"),
    ]

    symlink_info = {}

    for path in example_paths:
        if not os.path.exists(path):
            symlink_info[path] = (False, None, False)
            continue

        if os.path.islink(path):
            original_target = os.readlink(path)
            is_dir = os.path.isdir(path)

            print(f"  Found symlink: {os.path.basename(path)} -> {original_target}")

            # Resolve target for copying
            if os.path.isabs(original_target):
                resolved_target = original_target
            else:
                symlink_dir = os.path.dirname(os.path.abspath(path))
                resolved_target = os.path.normpath(os.path.join(symlink_dir, original_target))

            if not os.path.exists(resolved_target):
                print(f"    ⚠️  Symlink target does not exist: {resolved_target}")
                symlink_info[path] = (False, None, False)
                continue

            # Remove symlink and replace with copy
            os.remove(path)
            if is_dir:
                shutil.copytree(resolved_target, path)
            else:
                shutil.copy2(resolved_target, path)

            symlink_info[path] = (True, original_target, is_dir)
            print("    ✓ Replaced with copy")
        else:
            symlink_info[path] = (False, None, False)

    return symlink_info


def _restore_symlinks(work_dir: str, symlink_info: dict) -> None:
    """Restore original symlinks.

    Args:
        work_dir: Working directory
        symlink_info: Dictionary from _handle_symlinks_for_wheel

    Assumptions:
        - work_dir is still valid
        - Paths in symlink_info are relative to work_dir or absolute
    """
    for path, (was_symlink, original_target, is_dir) in symlink_info.items():
        if was_symlink and original_target:
            if os.path.exists(path) and not os.path.islink(path):
                print(f"  Restoring symlink: {os.path.basename(path)} -> {original_target}")
                try:
                    if is_dir:
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    os.symlink(original_target, path)
                    print("    ✓ Symlink restored")
                except Exception as e:
                    print(f"    ⚠️  Could not restore symlink: {e}")


def _copy_examples_for_wheel(work_dir: str) -> tuple[bool, bool, Optional[str]]:
    """Copy required examples into burr/ for wheel packaging.

    Flit wheels only package what's in the burr/ module directory.
    We need to copy the 4 required examples from examples/ to burr/examples/.

    Args:
        work_dir: Working directory (extracted sdist root)

    Returns:
        Tuple of (copied, was_symlink, symlink_target)

    Assumptions:
        - work_dir contains examples/ with the 4 required example directories
        - burr/ directory exists
        - burr/examples/ may or may not exist (could be a symlink)
    """
    burr_examples_dir = os.path.join(work_dir, "burr", "examples")
    source_examples_dir = os.path.join(work_dir, "examples")

    if not os.path.exists(source_examples_dir):
        print(f"    ⚠️  {source_examples_dir} not found, skipping example copy")
        return (False, False, None)

    # Check if burr/examples exists and handle it
    was_symlink = False
    symlink_target = None

    if os.path.exists(burr_examples_dir):
        if os.path.islink(burr_examples_dir):
            was_symlink = True
            symlink_target = os.readlink(burr_examples_dir)
            print(f"  Removing existing symlink: burr/examples -> {symlink_target}")
            os.remove(burr_examples_dir)
        else:
            print("  Removing existing directory: burr/examples")
            shutil.rmtree(burr_examples_dir)

    print("  Copying examples to burr/examples/ for wheel packaging...")
    os.makedirs(burr_examples_dir, exist_ok=True)

    # Copy __init__.py
    init_src = os.path.join(source_examples_dir, "__init__.py")
    if os.path.exists(init_src):
        shutil.copy2(init_src, os.path.join(burr_examples_dir, "__init__.py"))

    # Copy the 4 required example directories
    example_dirs = [
        "email-assistant",
        "multi-modal-chatbot",
        "streaming-fastapi",
        "deep-researcher",
    ]

    for example_dir in example_dirs:
        src_path = os.path.join(source_examples_dir, example_dir)
        dest_path = os.path.join(burr_examples_dir, example_dir)

        if os.path.exists(src_path):
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src_path, dest_path)
            print(f"    ✓ Copied {example_dir}")

    return (True, was_symlink, symlink_target)


def _remove_examples_from_burr(
    work_dir: str, was_symlink: bool = False, symlink_target: Optional[str] = None
) -> None:
    """Remove examples from burr/ and optionally restore symlink.

    Args:
        work_dir: Working directory
        was_symlink: If True, restore original symlink
        symlink_target: Original symlink target (if was_symlink)

    Assumptions:
        - work_dir is still valid
        - burr/examples/ exists (we just created it)
    """
    burr_examples_dir = os.path.join(work_dir, "burr", "examples")

    if os.path.exists(burr_examples_dir):
        print("  Removing burr/examples/ after wheel build...")
        shutil.rmtree(burr_examples_dir)

        if was_symlink and symlink_target:
            print(f"  Restoring symlink: burr/examples -> {symlink_target}")
            try:
                os.symlink(symlink_target, burr_examples_dir)
                print("    ✓ Symlink restored")
            except Exception as e:
                print(f"    ⚠️  Could not restore symlink: {e}")


def _build_wheel_from_sdist(sdist_path: str, version: str, output_dir: str = "dist") -> str:
    """Build wheel from source distribution.

    This function:
    1. Builds UI artifacts in the **current project directory** (for local dev use)
    2. Extracts the sdist to a temp directory
    3. Copies the pre-built UI artifacts from project to extracted sdist
    4. Handles symlinks and copies examples for wheel packaging
    5. Builds the wheel with flit
    6. Moves the wheel to the output directory
    7. Cleans up the temporary directory

    Args:
        sdist_path: Path to sdist tar.gz file
        version: Version string (e.g., "0.41.0")
        output_dir: Directory to write final wheel to (default: "dist")

    Returns:
        Path to created wheel file in output_dir

    Assumptions:
        - node and npm are installed (for UI build)
        - burr is installed in current environment with [cli] extras (for burr-admin-build-ui)
        - sdist_path is a valid sdist tar.gz
        - System has enough disk space for temp extraction
        - Current directory is project root (for relative paths)
    """
    _print_step(1, 4, "Building UI artifacts in current project directory")

    # Check for node and npm
    if shutil.which("node") is None or shutil.which("npm") is None:
        _fail("node and npm are required to build UI artifacts. Please install Node.js.")

    print("  ✓ node and npm found")

    # Build UI artifacts in the current project directory
    # This ensures they're available for local development and for packaging
    project_ui_build_dir = "burr/tracking/server/build"

    print(
        f"\n  Building UI artifacts (will be available at {project_ui_build_dir} for local dev)..."
    )

    # Clean any existing UI build
    if os.path.exists(project_ui_build_dir):
        print(f"    Cleaning existing UI build: {project_ui_build_dir}")
        shutil.rmtree(project_ui_build_dir)

    # Run burr-admin-build-ui from the current environment
    if shutil.which("burr-admin-build-ui") is None:
        _fail(
            "burr-admin-build-ui not found. Please ensure burr is installed with [cli] extras:\n"
            "  pip install -e .[cli]"
        )

    env = os.environ.copy()
    env["BURR_PROJECT_ROOT"] = os.getcwd()

    try:
        subprocess.run(["burr-admin-build-ui"], check=True, env=env, capture_output=True)
        print("    ✓ UI artifacts built successfully")
    except subprocess.CalledProcessError as e:
        _fail(f"Error building UI: {e}\nStderr: {e.stderr.decode()}")

    # Verify UI build output
    if not os.path.exists(project_ui_build_dir) or not os.listdir(project_ui_build_dir):
        _fail(f"UI build directory is empty or missing: {project_ui_build_dir}")

    print(f"    ✓ UI build verified: {project_ui_build_dir}")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Create temporary work directory for extracting and building wheel
    with tempfile.TemporaryDirectory() as work_dir:
        print("\n  Created temporary work directory")

        _print_step(2, 4, "Extracting sdist and copying UI artifacts")

        # Step 1: Extract sdist
        source_dir = _extract_sdist(sdist_path, os.path.join(work_dir, "extracted"))

        # Step 2: Copy pre-built UI artifacts from project to extracted sdist
        sdist_ui_build_dir = os.path.join(source_dir, "burr", "tracking", "server", "build")

        print("\n  Copying UI artifacts to extracted sdist...")
        print(f"    From: {project_ui_build_dir}")
        print(f"    To:   {sdist_ui_build_dir}")

        if os.path.exists(sdist_ui_build_dir):
            shutil.rmtree(sdist_ui_build_dir)

        shutil.copytree(project_ui_build_dir, sdist_ui_build_dir)
        print("    ✓ UI artifacts copied")

        # Step 3: Handle symlinks and copy examples
        print("\n  Preparing wheel contents...")
        _print_step(3, 4, "Preparing wheel contents (examples, symlinks)")

        symlink_info = _handle_symlinks_for_wheel(source_dir)
        examples_copied, examples_was_symlink, examples_symlink_target = _copy_examples_for_wheel(
            source_dir
        )

        # Step 4: Build wheel with flit
        print("\n  Building wheel with flit...")
        _print_step(4, 4, "Building wheel with flit")

        try:
            env = os.environ.copy()
            env["FLIT_USE_VCS"] = "0"

            subprocess.run(
                ["flit", "build", "--format", "wheel"],
                cwd=source_dir,
                env=env,
                check=True,
                capture_output=True,
            )
            print("    ✓ Wheel built successfully")

        except subprocess.CalledProcessError as e:
            print(f"    ✗ Error building wheel: {e}")
            print(f"    Stderr: {e.stderr.decode()}")
            # Cleanup before failing
            if examples_copied:
                _remove_examples_from_burr(
                    source_dir, examples_was_symlink, examples_symlink_target
                )
            _restore_symlinks(source_dir, symlink_info)
            _fail("Wheel build failed")

        # Step 7: Cleanup source directory
        print("\n  Cleaning up source directory...")
        if examples_copied:
            _remove_examples_from_burr(source_dir, examples_was_symlink, examples_symlink_target)
        _restore_symlinks(source_dir, symlink_info)

        # Step 8: Find and move wheel to output directory
        print("\n  Locating and moving wheel...")
        sdist_dist_dir = os.path.join(source_dir, "dist")

        if not os.path.exists(sdist_dist_dir):
            _fail(f"Wheel output directory not found: {sdist_dist_dir}")

        wheel_files = [f for f in os.listdir(sdist_dist_dir) if f.endswith(".whl")]

        if not wheel_files:
            _fail(f"No wheel files found in {sdist_dist_dir}")

        if len(wheel_files) > 1:
            print(f"    ⚠️  Multiple wheel files found, using first: {wheel_files[0]}")

        wheel_file = wheel_files[0]
        wheel_src_path = os.path.join(sdist_dist_dir, wheel_file)

        # Keep the original wheel filename from flit
        # Wheel filenames MUST follow strict format: {distribution}-{version}-{python}-{abi}-{platform}.whl
        # The distribution name MUST use underscores, not hyphens (PEP 427)
        # So we keep: apache_burr-0.41.0-py3-none-any.whl (valid)
        # NOT: apache-burr-0.41.0-py3-none-any.whl (invalid - hyphen in dist name)
        # The package name in metadata is "apache-burr" but the wheel filename uses "apache_burr"
        apache_wheel_name = wheel_file  # Keep original name from flit

        final_wheel_path = os.path.join(output_dir, apache_wheel_name)

        if os.path.exists(final_wheel_path):
            print(f"  Removing existing wheel: {final_wheel_path}")
            os.remove(final_wheel_path)

        shutil.move(wheel_src_path, final_wheel_path)
        print(f"    ✓ Moved wheel to: {os.path.basename(final_wheel_path)}")

    print("\n  ✓ Temporary directory cleaned up")
    return final_wheel_path


def _verify_wheel(wheel_path: str) -> bool:
    """Verify wheel contents are correct.

    Args:
        wheel_path: Path to wheel file

    Returns:
        True if wheel contents valid, False otherwise

    Assumptions:
        - wheel_path is a valid .whl file (ZIP format)
        - We're checking for required components, not exhaustive validation
    """
    import zipfile

    print(f"  Verifying wheel contents: {os.path.basename(wheel_path)}")

    if not os.path.exists(wheel_path):
        print(f"    ✗ Wheel file not found: {wheel_path}")
        return False

    try:
        with zipfile.ZipFile(wheel_path, "r") as whl:
            file_list = whl.namelist()

            # Check for UI build artifacts
            ui_build_files = [f for f in file_list if "burr/tracking/server/build/" in f]
            if not ui_build_files:
                print("    ✗ No UI build artifacts found in wheel")
                return False
            print(f"    ✓ Found {len(ui_build_files)} UI build files")

            # Check for required examples in burr/examples/
            required_examples = [
                "burr/examples/__init__.py",
                "burr/examples/email-assistant/",
                "burr/examples/multi-modal-chatbot/",
                "burr/examples/streaming-fastapi/",
                "burr/examples/deep-researcher/",
            ]

            for example in required_examples:
                example_files = [f for f in file_list if f.startswith(example)]
                if not example_files:
                    print(f"    ✗ Required example not found: {example}")
                    return False

            print("    ✓ All 4 required examples found in wheel")

            # Check that source artifacts are NOT included
            unwanted_patterns = [
                "scripts/",
                "telemetry/ui/src/",
                "telemetry/ui/node_modules/",
                ".git/",
            ]

            for pattern in unwanted_patterns:
                unwanted_files = [f for f in file_list if pattern in f]
                if unwanted_files:
                    print(
                        f"    ⚠️  Warning: Found unwanted files matching '{pattern}': {len(unwanted_files)} files"
                    )

            print(f"    ✓ Wheel contains {len(file_list)} total files")
            return True

    except zipfile.BadZipFile:
        print(f"    ✗ Invalid wheel file (not a valid ZIP): {wheel_path}")
        return False
    except Exception as e:
        print(f"    ✗ Error verifying wheel: {e}")
        return False


# ============================================================================
# Upload to Apache SVN
# ============================================================================


def _upload_to_svn(
    version: str,
    rc_num: str,
    apache_id: str,
    artifacts: list[str],
    dry_run: bool = False,
) -> Optional[str]:
    """Upload artifacts to Apache SVN distribution repository.

    Args:
        version: Version string
        rc_num: RC number
        apache_id: Apache ID for authentication
        artifacts: List of file paths to upload (tar.gz, sdist, wheel, signatures, checksums)
        dry_run: If True, don't actually upload

    Returns:
        SVN URL if successful, None if failed
    """
    # TODO:
    # 1. Create SVN directory structure
    # 2. Upload all artifacts (tar.gz, sdist, wheel, and their .asc/.sha512 files)
    # 3. Return SVN URL
    return None


# ============================================================================
# Email Template Generation
# ============================================================================


def _generate_vote_email(version: str, rc_num: str, svn_url: str, artifacts: list[str]) -> str:
    """Generate [VOTE] email template.

    Args:
        version: Version string
        rc_num: RC number
        svn_url: SVN URL where artifacts are hosted
        artifacts: List of artifact filenames

    Returns:
        Email content as string
    """
    # TODO: Generate email template with checklist and artifact list
    return ""


def _print_vote_email(email_content: str) -> None:
    """Print vote email to console.

    Args:
        email_content: Email content from _generate_vote_email
    """
    # TODO: Print formatted email
    pass


# ============================================================================
# Auto-detection Helpers
# ============================================================================


def _auto_detect_artifact(
    version: str, artifact_type: str, output_dir: str = "dist"
) -> Optional[str]:
    """Auto-detect artifact path based on version and type.

    Args:
        version: Version string (e.g., "0.41.0")
        artifact_type: Type of artifact ('archive', 'sdist', 'wheel')
        output_dir: Directory to search in

    Returns:
        Path to artifact if found, None otherwise

    Assumptions:
        - Artifacts follow naming convention
        - archive: apache-burr-{version}-incubating-src.tar.gz
        - sdist: apache-burr-{version}-incubating-src-sdist.tar.gz
        - wheel: apache-burr-{version}-incubating-*.whl
    """
    if artifact_type == "archive":
        artifact_path = os.path.join(output_dir, f"apache-burr-{version}-incubating-src.tar.gz")
        if os.path.exists(artifact_path):
            return artifact_path

    elif artifact_type == "sdist":
        artifact_path = os.path.join(
            output_dir, f"apache-burr-{version}-incubating-src-sdist.tar.gz"
        )
        if os.path.exists(artifact_path):
            return artifact_path

    elif artifact_type == "wheel":
        # Use glob to find wheel with any platform tags
        wheel_pattern = os.path.join(output_dir, f"apache-burr-{version}-incubating-*.whl")
        wheel_files = glob.glob(wheel_pattern)
        if wheel_files:
            return wheel_files[0]  # Return first match

    return None


def _collect_all_artifacts(version: str, output_dir: str = "dist") -> list[str]:
    """Collect all artifacts (including signatures and checksums) for upload.

    Args:
        version: Version string
        output_dir: Directory containing artifacts

    Returns:
        List of artifact paths (archives, wheels, signatures, checksums)

    Assumptions:
        - All artifacts follow naming convention with {version}-incubating
        - Includes: .tar.gz, .whl, .asc, .sha512 files
        - Excludes RAT reports
    """
    if not os.path.exists(output_dir):
        return []

    artifacts = []

    for filename in os.listdir(output_dir):
        file_path = os.path.join(output_dir, filename)

        # Skip directories
        if not os.path.isfile(file_path):
            continue

        # Skip RAT reports
        if filename.startswith("rat-report-"):
            continue

        # Include artifacts with version-incubating in name
        if f"{version}-incubating" in filename:
            # Include: tar.gz, whl, .asc, .sha512
            if any(filename.endswith(ext) for ext in [".tar.gz", ".whl", ".asc", ".sha512"]):
                artifacts.append(file_path)

    return sorted(artifacts)


# ============================================================================
# Command Handlers
# ============================================================================


def cmd_archive(args) -> bool:
    """Handle 'archive' subcommand."""
    _print_section(f"Creating Git Archive - v{args.version}-RC{args.rc_num}")

    # Check if RAT is needed
    check_rat = args.check_licenses or args.check_licenses_report
    if check_rat and not args.rat_jar:
        _fail("--rat-jar is required when using --check-licenses or --check-licenses-report")

    # Prerequisites
    if not _check_prerequisites(check_rat=check_rat, rat_jar_path=args.rat_jar):
        return False
    if not _verify_project_root():
        return False
    if not _validate_version(args.version):
        return False
    _check_git_working_tree()

    # Create archive
    archive_path = _create_git_archive(args.version, args.rc_num, args.output_dir)
    if not archive_path:
        return False

    print(f"\n✅ Archive created: {archive_path}")

    # Optional license check
    if check_rat:
        _print_step(2, 2, "Checking licenses with Apache RAT")
        if not _check_licenses_with_rat(
            archive_path,
            args.rat_jar,
            args.version,
            args.rc_num,
            stage="archive",
            report_only=args.check_licenses_report,
        ):
            if not args.check_licenses_report:
                return False

    return True


def cmd_sdist(args) -> bool:
    """Handle 'sdist' subcommand."""
    _print_section(f"Building Source Distribution - v{args.version}-RC{args.rc_num}")

    # Check if RAT is needed
    check_rat = args.check_licenses or args.check_licenses_report
    if check_rat and not args.rat_jar:
        _fail("--rat-jar is required when using --check-licenses or --check-licenses-report")

    # Prerequisites (need flit for building)
    print("Checking prerequisites...")
    if shutil.which("flit") is None:
        _fail("'flit' not found. Install with: pip install flit")
    print("  ✓ flit found")

    if not _check_prerequisites(check_rat=check_rat, rat_jar_path=args.rat_jar):
        return False
    if not _verify_project_root():
        return False
    if not _validate_version(args.version):
        return False

    # Build sdist from git
    sdist_path = _build_sdist_from_git(args.version, args.output_dir)
    if not sdist_path:
        return False

    # Sign the sdist
    _print_step(2, 4 if check_rat else 3, "Signing sdist")
    _sign_artifact(sdist_path)

    # Verify the sdist
    _print_step(3, 4 if check_rat else 3, "Verifying sdist")
    if not _verify_artifact_complete(sdist_path):
        _fail("sdist verification failed!")

    # Optional license check on sdist
    if check_rat:
        _print_step(4, 4, "Checking licenses with Apache RAT")
        if not _check_licenses_with_rat(
            sdist_path,
            args.rat_jar,
            args.version,
            args.rc_num,
            stage="sdist",
            report_only=args.check_licenses_report,
        ):
            if not args.check_licenses_report:
                return False

    print(f"\n✅ Source distribution created: {sdist_path}")
    return True


def cmd_wheel(args) -> bool:
    """Handle 'wheel' subcommand."""
    _print_section(f"Building Wheel - v{args.version}-RC{args.rc_num}")

    # Prerequisites - check for uv, node, npm
    print("Checking prerequisites...")
    required_tools = ["uv", "node", "npm"]
    missing_tools = []

    for tool in required_tools:
        if shutil.which(tool) is None:
            missing_tools.append(tool)
            print(f"  ✗ '{tool}' not found")
        else:
            print(f"  ✓ '{tool}' found")

    if missing_tools:
        _fail(
            f"Missing required tools: {', '.join(missing_tools)}\n"
            + "Install uv: https://docs.astral.sh/uv/\n"
            + "Install Node.js: https://nodejs.org/"
        )

    if not _check_prerequisites():
        return False
    if not _verify_project_root():
        return False
    if not _validate_version(args.version):
        return False

    # Find or use specified sdist
    sdist_path = args.sdist_path
    if not sdist_path:
        detected = _auto_detect_artifact(args.version, "sdist", args.output_dir)
        if not detected:
            _fail("Could not find sdist. Please specify --sdist-path or run 'sdist' command first.")
        sdist_path = detected
        print(f"\nUsing sdist: {os.path.basename(sdist_path)}")

    # Build wheel in isolated environment
    wheel_path = _build_wheel_from_sdist(sdist_path, args.version, args.output_dir)
    if not wheel_path:
        return False

    # Sign the wheel
    print("\nSigning wheel...")
    _sign_artifact(wheel_path)

    # Verify the wheel
    print("\nVerifying wheel...")
    if not _verify_wheel(wheel_path):
        _fail("Wheel verification failed!")

    if not _verify_artifact_complete(wheel_path, check_tar=False):
        _fail("Wheel signature/checksum verification failed!")

    print(f"\n✅ Wheel created and verified: {os.path.basename(wheel_path)}")
    return True


def cmd_upload(args) -> bool:
    """Handle 'upload' subcommand."""
    _print_section(f"Uploading Artifacts - v{args.version}-RC{args.rc_num}")

    # Prerequisites
    if not _check_prerequisites():
        return False
    if not _verify_project_root():
        return False

    # Collect all artifacts
    artifacts = _collect_all_artifacts(args.version, args.artifacts_dir)
    if not artifacts:
        _fail(f"No artifacts found in {args.artifacts_dir}. Please build artifacts first.")

    print(f"Found {len(artifacts)} artifact(s) to upload:")
    for artifact in artifacts:
        print(f"  - {os.path.basename(artifact)}")

    # Upload
    if args.dry_run:
        svn_url = f"https://dist.apache.org/repos/dist/dev/incubator/{PROJECT_SHORT_NAME}/{args.version}-incubating-RC{args.rc_num}"
        print(f"\n[DRY RUN] Would upload to: {svn_url}")
    else:
        svn_url = _upload_to_svn(
            args.version, args.rc_num, args.apache_id, artifacts, dry_run=False
        )
        if not svn_url:
            return False
        print(f"\n✅ Artifacts uploaded to: {svn_url}")

    return True


def cmd_verify(args) -> bool:
    """Handle 'verify' subcommand."""
    _print_section(f"Verifying Artifacts - v{args.version}-RC{args.rc_num}")

    all_valid = True
    artifacts_found = 0

    # Define expected artifacts
    expected_artifacts = [
        f"apache-burr-{args.version}-incubating-src.tar.gz",  # Git archive
        f"apache-burr-{args.version}-incubating-sdist.tar.gz",  # Source dist
        # Wheel pattern will need globbing
    ]

    # Check each artifact
    for artifact_name in expected_artifacts:
        artifact_path = os.path.join(args.artifacts_dir, artifact_name)

        if os.path.exists(artifact_path):
            artifacts_found += 1
            if not _verify_artifact_complete(artifact_path):
                all_valid = False
        else:
            print(f"\nℹ️  Artifact not found (skipping): {artifact_name}")

    # Check for wheel (using glob pattern)
    wheel_pattern = os.path.join(args.artifacts_dir, f"apache_burr-{args.version}-*.whl")
    wheel_files = glob.glob(wheel_pattern)

    if wheel_files:
        for wheel_path in wheel_files:
            artifacts_found += 1
            if not _verify_artifact_complete(wheel_path):
                all_valid = False
    else:
        print(f"\nℹ️  No wheel files found matching: {os.path.basename(wheel_pattern)}")

    # Summary
    _print_section("Verification Summary")
    if artifacts_found == 0:
        print(f"⚠️  No artifacts found in {args.artifacts_dir}")
        return False
    elif all_valid:
        print(f"✅ All {artifacts_found} artifact(s) verified successfully!")
        return True
    else:
        print("❌ Some artifacts failed verification")
        return False


def cmd_all(args) -> bool:
    """Handle 'all' subcommand - run complete workflow."""
    _print_section(f"Apache Burr Release Process - v{args.version}-RC{args.rc_num}")

    if args.dry_run:
        print("*** DRY RUN MODE - No git tags or SVN uploads will be performed ***\n")

    # Check if RAT is needed
    check_rat = args.check_licenses or args.check_licenses_report
    if check_rat and not args.rat_jar:
        _fail("--rat-jar is required when using --check-licenses or --check-licenses-report")

    # Prerequisites
    _print_step(0, 5, "Checking prerequisites")
    if not _check_prerequisites(check_rat=check_rat, rat_jar_path=args.rat_jar):
        return False
    if not _verify_project_root():
        return False
    if not _validate_version(args.version):
        return False
    _check_git_working_tree()

    # Git tagging
    if not args.no_tag and not args.dry_run:
        _print_step(1, 5, "Creating/verifying git tag")
        if not _create_or_verify_git_tag(args.version, args.rc_num, args.dry_run):
            return False

    # Clean dist/
    if args.clean:
        _print_step(1, 5, "Cleaning dist/ directory")
        # TODO: Clean dist/

    artifacts = []

    # Step 1: Git Archive
    _print_step(2, 5, "Creating git archive (voting artifact)")
    archive_path = _create_git_archive(args.version, args.rc_num, args.output_dir)
    if not archive_path:
        return False
    artifacts.append(archive_path)

    if check_rat:
        print("\n[License Check] Checking licenses with Apache RAT")
        print("-" * 80)
        if not _check_licenses_with_rat(
            archive_path,
            args.rat_jar,
            args.version,
            args.rc_num,
            stage="archive",
            report_only=args.check_licenses_report,
        ):
            if not args.check_licenses_report:
                return False

    # Step 2: Build sdist
    _print_step(3, 5, "Building source distribution (sdist) from git")
    sdist_path = _build_sdist_from_git(args.version, args.output_dir)
    if not sdist_path:
        return False
    _sign_artifact(sdist_path)
    if not _verify_artifact_complete(sdist_path):
        _fail("sdist verification failed!")
    artifacts.append(sdist_path)

    # Step 3: Build wheel
    _print_step(4, 5, "Building wheel from sdist")
    wheel_path = _build_wheel_from_sdist(sdist_path, args.version, args.output_dir)
    if not wheel_path:
        return False
    artifacts.append(wheel_path)

    # Collect all artifacts (including signatures and checksums)
    all_artifacts = _collect_all_artifacts(args.version, args.output_dir)

    # Upload to SVN
    if not args.no_upload and not args.dry_run:
        _print_step(5, 5, "Uploading artifacts to Apache SVN")
        svn_url = _upload_to_svn(
            args.version, args.rc_num, args.apache_id, all_artifacts, dry_run=False
        )
        if not svn_url:
            return False
    else:
        svn_url = f"https://dist.apache.org/repos/dist/dev/incubator/{PROJECT_SHORT_NAME}/{args.version}-incubating-RC{args.rc_num}"
        if args.dry_run:
            print(f"\n[DRY RUN] Would upload to: {svn_url}")
        else:
            print("\nℹ️  Skipping upload (--no-upload specified)")

    # Generate email template
    _print_section("Release Complete!")
    email_content = _generate_vote_email(args.version, args.rc_num, svn_url, all_artifacts)
    _print_vote_email(email_content)

    return True


# ============================================================================
# CLI Entry Point
# ============================================================================


def main():
    """Main entry point for the release script."""
    parser = argparse.ArgumentParser(
        description="Apache Burr Release Automation Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full release workflow
  python scripts/apache_release.py all 0.41.0 0 myid

  # Step-by-step workflow
  python scripts/apache_release.py archive 0.41.0 0 --check-licenses
  python scripts/apache_release.py sdist 0.41.0 0
  python scripts/apache_release.py wheel 0.41.0 0
  python scripts/apache_release.py verify 0.41.0 0
  python scripts/apache_release.py upload 0.41.0 0 myid

  # Rebuild just the wheel
  python scripts/apache_release.py wheel 0.41.0 0

  # Dry run
  python scripts/apache_release.py all 0.41.0 0 myid --dry-run

  # With explicit paths
  python scripts/apache_release.py sdist 0.41.0 0 --archive-path /path/to/archive.tar.gz
  python scripts/apache_release.py wheel 0.41.0 0 --sdist-path /path/to/sdist.tar.gz

For more information, see scripts/README.md
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Subcommands")

    # ========================================
    # archive subcommand
    # ========================================
    archive_parser = subparsers.add_parser(
        "archive",
        help="Create git archive (voting artifact)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Create git archive snapshot of repository for voting.",
    )
    archive_parser.add_argument(
        "version",
        help="Release version (e.g., '0.41.0'). Must match version in pyproject.toml.",
    )
    archive_parser.add_argument(
        "rc_num",
        help="Release candidate number (e.g., '0' for RC0, '1' for RC1).",
    )
    archive_parser.add_argument(
        "--output-dir",
        default="dist",
        help="Output directory for artifacts (default: dist)",
    )
    archive_parser.add_argument(
        "--check-licenses",
        action="store_true",
        help="Run Apache RAT license checker (blocking on failure)",
    )
    archive_parser.add_argument(
        "--check-licenses-report",
        action="store_true",
        help="Run Apache RAT license checker (report only, non-blocking)",
    )
    archive_parser.add_argument(
        "--rat-jar",
        default=None,
        help="Path to Apache RAT JAR file (required if using --check-licenses or --check-licenses-report)",
    )

    # ========================================
    # sdist subcommand
    # ========================================
    sdist_parser = subparsers.add_parser(
        "sdist",
        help="Build source distribution from archive",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Build source distribution (sdist) from git archive using flit.",
    )
    sdist_parser.add_argument(
        "version",
        help="Release version (e.g., '0.41.0'). Must match version in pyproject.toml.",
    )
    sdist_parser.add_argument(
        "rc_num",
        help="Release candidate number (e.g., '0' for RC0, '1' for RC1).",
    )
    sdist_parser.add_argument(
        "--archive-path",
        default=None,
        help="Path to git archive tar.gz (default: auto-detect in output-dir)",
    )
    sdist_parser.add_argument(
        "--output-dir",
        default="dist",
        help="Output directory for artifacts (default: dist)",
    )
    sdist_parser.add_argument(
        "--check-licenses",
        action="store_true",
        help="Run Apache RAT license checker on sdist (blocking on failure)",
    )
    sdist_parser.add_argument(
        "--check-licenses-report",
        action="store_true",
        help="Run Apache RAT license checker on sdist (report only, non-blocking)",
    )
    sdist_parser.add_argument(
        "--rat-jar",
        default=None,
        help="Path to Apache RAT JAR file (required if using --check-licenses or --check-licenses-report)",
    )

    # ========================================
    # wheel subcommand
    # ========================================
    wheel_parser = subparsers.add_parser(
        "wheel",
        help="Build wheel from sdist",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Build wheel from source distribution using flit.",
    )
    wheel_parser.add_argument(
        "version",
        help="Release version (e.g., '0.41.0'). Must match version in pyproject.toml.",
    )
    wheel_parser.add_argument(
        "rc_num",
        help="Release candidate number (e.g., '0' for RC0, '1' for RC1).",
    )
    wheel_parser.add_argument(
        "--sdist-path",
        default=None,
        help="Path to sdist tar.gz (default: auto-detect in output-dir)",
    )
    wheel_parser.add_argument(
        "--output-dir",
        default="dist",
        help="Output directory for artifacts (default: dist)",
    )
    wheel_parser.add_argument(
        "--skip-ui-build",
        action="store_true",
        help="Skip UI build (use existing build artifacts)",
    )

    # ========================================
    # upload subcommand
    # ========================================
    upload_parser = subparsers.add_parser(
        "upload",
        help="Upload artifacts to Apache SVN",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Upload all artifacts to Apache SVN distribution repository.",
    )
    upload_parser.add_argument(
        "version",
        help="Release version (e.g., '0.41.0').",
    )
    upload_parser.add_argument(
        "rc_num",
        help="Release candidate number (e.g., '0' for RC0, '1' for RC1).",
    )
    upload_parser.add_argument(
        "apache_id",
        help="Your Apache ID for SVN authentication.",
    )
    upload_parser.add_argument(
        "--artifacts-dir",
        default="dist",
        help="Directory containing artifacts to upload (default: dist)",
    )
    upload_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be uploaded without actually uploading",
    )

    # ========================================
    # all subcommand
    # ========================================
    all_parser = subparsers.add_parser(
        "all",
        help="Run complete release workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Run complete release workflow: archive → sdist → wheel → upload",
    )
    all_parser.add_argument(
        "version",
        help="Release version (e.g., '0.41.0'). Must match version in pyproject.toml.",
    )
    all_parser.add_argument(
        "rc_num",
        help="Release candidate number (e.g., '0' for RC0, '1' for RC1).",
    )
    all_parser.add_argument(
        "apache_id",
        help="Your Apache ID for SVN authentication.",
    )
    all_parser.add_argument(
        "--output-dir",
        default="dist",
        help="Output directory for artifacts (default: dist)",
    )
    all_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build artifacts but don't create git tags or upload to SVN",
    )
    all_parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Build artifacts but skip SVN upload",
    )
    all_parser.add_argument(
        "--no-tag",
        action="store_true",
        help="Don't create git RC tag",
    )
    all_parser.add_argument(
        "--clean",
        action="store_true",
        default=True,
        help="Clean dist/ directory before starting (default: True)",
    )
    all_parser.add_argument(
        "--no-clean",
        dest="clean",
        action="store_false",
        help="Don't clean dist/ directory before starting",
    )
    all_parser.add_argument(
        "--check-licenses",
        action="store_true",
        help="Run Apache RAT license checker on archive (blocking on failure)",
    )
    all_parser.add_argument(
        "--check-licenses-report",
        action="store_true",
        help="Run Apache RAT license checker on archive (report only, non-blocking)",
    )
    all_parser.add_argument(
        "--rat-jar",
        default=None,
        help="Path to Apache RAT JAR file (required if using --check-licenses or --check-licenses-report)",
    )

    # ========================================
    # verify subcommand
    # ========================================
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify existing artifacts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Verify signatures, checksums, and contents of existing artifacts.",
    )
    verify_parser.add_argument(
        "version",
        help="Release version (e.g., '0.41.0').",
    )
    verify_parser.add_argument(
        "rc_num",
        help="Release candidate number (e.g., '0' for RC0, '1' for RC1).",
    )
    verify_parser.add_argument(
        "--artifacts-dir",
        default="dist",
        help="Directory containing artifacts to verify (default: dist)",
    )

    # Parse arguments
    args = parser.parse_args()

    # Validate environment before executing any command
    _validate_environment_for_command(args)

    # Dispatch to appropriate command handler
    success = False
    try:
        if args.command == "archive":
            success = cmd_archive(args)
        elif args.command == "sdist":
            success = cmd_sdist(args)
        elif args.command == "wheel":
            success = cmd_wheel(args)
        elif args.command == "upload":
            success = cmd_upload(args)
        elif args.command == "all":
            success = cmd_all(args)
        elif args.command == "verify":
            success = cmd_verify(args)
        else:
            print(f"Unknown command: {args.command}")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    if success:
        print("\n✅ Command completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Command failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
