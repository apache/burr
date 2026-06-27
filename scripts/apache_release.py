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
Apache Burr Release Script (SIMPLIFIED VERSION)

This script automates the Apache release process:
1. Create git archive (voting artifact)
2. Build source distribution (sdist)
3. Build wheel
4. Upload to Apache SVN

Usage:
    python scripts/apache_release_simplified.py all 0.41.0 0 myid
    python scripts/apache_release_simplified.py wheel 0.41.0 0
"""

import argparse
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NoReturn, Optional

# --- Configuration ---
PROJECT_SHORT_NAME = "burr"
VERSION_FILE = "pyproject.toml"
VERSION_PATTERN = r'version\s*=\s*"(\d+\.\d+\.\d+)"'
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_DOWNLOADS_URL = f"https://downloads.apache.org/incubator/{PROJECT_SHORT_NAME}/"
DEFAULT_DEV_SVN_ROOT = f"https://dist.apache.org/repos/dist/dev/incubator/{PROJECT_SHORT_NAME}"
DEFAULT_RELEASE_SVN_ROOT = (
    f"https://dist.apache.org/repos/dist/release/incubator/{PROJECT_SHORT_NAME}"
)
RC_LABEL_PATTERN = re.compile(
    r"^(?P<version>\d+\.\d+\.\d+)(?:-incubating)?-RC(?P<rc_num>\d+)$", re.IGNORECASE
)

# Required examples for wheel (from pyproject.toml)
REQUIRED_EXAMPLES = [
    "__init__.py",
    "email-assistant",
    "multi-modal-chatbot",
    "streaming-fastapi",
    "deep-researcher",
    "hello-world-counter",
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


def _run_command(
    cmd: list[str],
    description: str,
    error_message: str,
    success_message: Optional[str] = None,
    capture_output: bool = True,
    **kwargs,
) -> subprocess.CompletedProcess:
    """Run a subprocess command with consistent error handling and output.

    Args:
        cmd: Command and arguments as list
        description: What we're doing (printed before running)
        error_message: Error message prefix if command fails
        success_message: Optional success message (printed after if provided)
        capture_output: Whether to capture stdout/stderr (default True)
        **kwargs: Additional arguments to pass to subprocess.run

    Returns:
        CompletedProcess instance
    """
    if description:
        print(f"  {description}")

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=capture_output,
            text=True,
            **kwargs,
        )
        if success_message:
            print(f"    ✓ {success_message}")
        return result
    except subprocess.CalledProcessError as e:
        error_detail = f": {e.stderr}" if capture_output and e.stderr else ""
        _fail(f"{error_message}{error_detail}")


def _render_template(template_name: str, context: dict[str, Any]) -> str:
    """Render a template with Jinja2."""
    template_path = TEMPLATES_DIR / template_name

    if not template_path.exists():
        _fail(f"Template not found: {template_path}")

    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )
    return environment.get_template(template_name).render(**context)


def _clipboard_commands() -> list[list[str]]:
    """Return clipboard commands for macOS, Linux, and Windows."""
    return [
        ["pbcopy"],  # macOS
        ["xclip", "-selection", "clipboard"],  # Linux with xclip
        ["xsel", "--clipboard", "--input"],  # Linux with xsel
        ["clip"],  # Windows
    ]


def _copy_to_clipboard(content: str) -> bool:
    """Copy content to the system clipboard when a known clipboard tool exists."""
    for command in _clipboard_commands():
        if shutil.which(command[0]) is None:
            continue
        try:
            subprocess.run(command, input=content, text=True, check=True)
            return True
        except subprocess.CalledProcessError:
            continue
    return False


def _emit_email_output(content: str, copy_to_clipboard: bool = False) -> None:
    """Emit rendered email to stdout and optionally copy it to the clipboard."""
    print(content)
    if copy_to_clipboard:
        if _copy_to_clipboard(content):
            print("\n Copied email content to clipboard", file=sys.stderr)
        else:
            print(
                "\n Clipboard tool not found; email content was printed to stdout instead",
                file=sys.stderr,
            )


def _parse_semver(version: str) -> tuple[int, int, int]:
    """Parse an X.Y.Z version string into a sortable tuple."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        _fail(f"Invalid version format: {version}")
    return tuple(int(part) for part in match.groups())


def _list_release_tags() -> list[tuple[tuple[int, int, int], str]]:
    """List known release tags in the repository."""
    try:
        result = subprocess.run(
            ["git", "tag", "--list"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return []

    tags: list[tuple[tuple[int, int, int], str]] = []
    for line in result.stdout.splitlines():
        match = re.fullmatch(r"(?:v|burr-)(\d+\.\d+\.\d+)", line.strip())
        if match:
            tags.append((_parse_semver(match.group(1)), line.strip()))
    return sorted(tags)


def _find_previous_release_tag(version: str) -> Optional[str]:
    """Find the most recent release tag strictly older than the requested version."""
    target = _parse_semver(version)
    previous_tags = [tag for parsed, tag in _list_release_tags() if parsed < target]
    if not previous_tags:
        return None
    return previous_tags[-1]


def _find_release_tag(version: str) -> Optional[str]:
    """Find the exact release tag for a version, if it exists."""
    target = _parse_semver(version)
    matching_tags = [tag for parsed, tag in _list_release_tags() if parsed == target]
    if not matching_tags:
        return None
    return matching_tags[-1]


def _build_changelog_summary(
    version: str, previous_tag: Optional[str] = None, max_entries: int = 8
) -> str:
    """Summarize recent commits since the prior release tag."""
    if previous_tag is None:
        previous_tag = _find_previous_release_tag(version)
    release_tag = _find_release_tag(version)

    if not previous_tag:
        return "- Changelog summary unavailable; please add a short summary before sending."

    revision_range = f"{previous_tag}..{release_tag or 'HEAD'}"

    try:
        result = subprocess.run(
            ["git", "log", revision_range, "--pretty=format:%s"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return f"- Changelog summary unavailable; review commits in {revision_range} manually."

    subjects = []
    for line in result.stdout.splitlines():
        cleaned = line.strip()
        if cleaned and cleaned not in subjects:
            subjects.append(cleaned)

    if not subjects:
        return f"- No commits found in {revision_range}; verify the tag range before sending."

    summary_lines = [f"- {subject}" for subject in subjects[:max_entries]]
    remaining = len(subjects) - len(summary_lines)
    if remaining > 0:
        summary_lines.append(f"- ... plus {remaining} more commits in {revision_range}")
    return "\n".join(summary_lines)


def _build_vote_deadline(hours: int = 72) -> datetime:
    """Return the vote deadline timestamp in UTC."""
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _format_vote_deadline(deadline: datetime) -> str:
    """Format the vote deadline for email output."""
    return deadline.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _build_vote_email_context(
    version: str,
    rc_num: str,
    svn_url: Optional[str] = None,
    pypi_url: Optional[str] = None,
    keys_url: Optional[str] = None,
    changelog_summary: Optional[str] = None,
    previous_tag: Optional[str] = None,
    deadline: Optional[datetime] = None,
) -> dict[str, str]:
    """Build rendering context for the vote email template."""
    version_with_incubating = f"{version}-incubating"
    svn_url = svn_url or _build_svn_dev_url(version, rc_num)
    deadline = deadline or _build_vote_deadline()
    return {
        "project_short_name": PROJECT_SHORT_NAME,
        "project_display_name": PROJECT_SHORT_NAME.capitalize(),
        "version": version,
        "version_with_incubating": version_with_incubating,
        "rc_num": rc_num,
        "svn_url": svn_url,
        "pypi_url": pypi_url or _build_pypi_rc_url(version, rc_num),
        "keys_url": keys_url or _build_keys_url(),
        "git_tag": f"v{version}-incubating-RC{rc_num}",
        "changelog_summary": changelog_summary
        or _build_changelog_summary(version, previous_tag=previous_tag),
        "vote_deadline": _format_vote_deadline(deadline),
    }


def _build_result_email_context(
    version: str,
    rc_num: str,
    binding_yes: int,
    non_binding_yes: int,
    abstain: int,
    binding_no: int,
    non_binding_no: int,
    vote_thread_url: Optional[str] = None,
) -> dict[str, str]:
    """Build rendering context for the result email template."""
    release_passed = binding_yes >= 3 and binding_yes > binding_no
    return {
        "project_short_name": PROJECT_SHORT_NAME,
        "project_display_name": PROJECT_SHORT_NAME.capitalize(),
        "version": version,
        "version_with_incubating": f"{version}-incubating",
        "rc_num": rc_num,
        "binding_yes": str(binding_yes),
        "non_binding_yes": str(non_binding_yes),
        "abstain": str(abstain),
        "binding_no": str(binding_no),
        "non_binding_no": str(non_binding_no),
        "vote_thread_url": vote_thread_url or "[add link to vote thread]",
        "result_outcome": (
            "Therefore, the release candidate has passed."
            if release_passed
            else "Therefore, the release candidate has not passed."
        ),
    }


def _build_announcement_email_context(
    version: str,
    pypi_url: Optional[str] = None,
    downloads_url: Optional[str] = None,
    changelog_summary: Optional[str] = None,
    previous_tag: Optional[str] = None,
) -> dict[str, str]:
    """Build rendering context for the release announcement template."""
    return {
        "project_short_name": PROJECT_SHORT_NAME,
        "project_display_name": PROJECT_SHORT_NAME.capitalize(),
        "version": version,
        "version_with_incubating": f"{version}-incubating",
        "pypi_url": pypi_url or f"https://pypi.org/project/apache-burr/{version}/",
        "downloads_url": downloads_url or DEFAULT_DOWNLOADS_URL,
        "changelog_summary": changelog_summary
        or _build_changelog_summary(version, previous_tag=previous_tag),
    }


def _build_svn_dev_url(version: str, rc_num: str) -> str:
    """Build the Apache SVN development artifacts URL for an RC."""
    return (
        "https://dist.apache.org/repos/dist/dev/incubator/"
        f"{PROJECT_SHORT_NAME}/{version}-incubating-RC{rc_num}"
    )


def _build_keys_url() -> str:
    """Build the Apache KEYS URL."""
    return f"{DEFAULT_DOWNLOADS_URL}KEYS"


def _build_pypi_rc_url(version: str, rc_num: str) -> str:
    """Build the PyPI URL for a release candidate."""
    return f"https://pypi.org/project/apache-burr/{version}rc{rc_num}/"


def _parse_rc_label(rc_label: str) -> tuple[str, str]:
    """Parse an RC label like 0.42.0-RC1 or 0.42.0-incubating-RC1."""
    match = RC_LABEL_PATTERN.fullmatch(rc_label.strip())
    if not match:
        _fail("Invalid RC label. Expected format like '0.42.0-RC1' " "or '0.42.0-incubating-RC1'.")
    return match.group("version"), match.group("rc_num")


# ============================================================================
# Environment Validation
# ============================================================================


def _validate_environment_for_command(args) -> None:
    """Validate required tools for the requested command."""
    print("\n" + "=" * 80)
    print("  Environment Validation")
    print("=" * 80 + "\n")

    # Define required tools for each command
    command_requirements = {
        "archive": ["git", "gpg"],
        "sdist": ["git", "gpg", "flit"],
        "wheel": ["git", "gpg", "flit", "node", "npm", "twine"],
        "upload": ["git", "gpg", "svn"],
        "promote": ["svn"],
        "all": ["git", "gpg", "flit", "node", "npm", "svn", "twine"],
        "verify": ["git", "gpg", "twine"],
        "vote-email": ["git"],
        "result-email": [],
        "announce-email": ["git"],
    }

    required_tools = list(command_requirements.get(args.command, ["git", "gpg"]))

    # Drop gpg if user opted out of signing
    if getattr(args, "skip_signing", False) and "gpg" in required_tools:
        required_tools.remove("gpg")

    # Drop svn if user opted out of upload (svn is only used for upload)
    if getattr(args, "no_upload", False) and "svn" in required_tools:
        required_tools.remove("svn")

    # Check for RAT if needed
    if hasattr(args, "check_licenses") or hasattr(args, "check_licenses_report"):
        if getattr(args, "check_licenses", False) or getattr(args, "check_licenses_report", False):
            required_tools.append("java")
            if not getattr(args, "rat_jar", None):
                _fail("--rat-jar is required when using --check-licenses")

    # Check each tool
    missing_tools = []
    print("Checking required tools:")

    for tool in required_tools:
        if shutil.which(tool) is None:
            missing_tools.append(tool)
            print(f"  ✗ '{tool}' not found")
        else:
            print(f"  ✓ '{tool}' found")

    if missing_tools:
        print("\n❌ Missing required tools:")
        for tool in missing_tools:
            if tool == "flit":
                print(f"  • {tool}: Install with 'pip install flit'")
            elif tool == "twine":
                print(f"  • {tool}: Install with 'pip install twine'")
            elif tool in ["node", "npm"]:
                print(f"  • {tool}: Install from https://nodejs.org/")
            else:
                print(f"  • {tool}")
        sys.exit(1)

    print("\n✓ All required tools are available\n")


# ============================================================================
# Prerequisites
# ============================================================================


def _verify_project_root() -> bool:
    """Verify script is running from project root."""
    if not os.path.exists("pyproject.toml"):
        _fail("pyproject.toml not found. Please run from project root.")
    return True


def _get_version_from_file(file_path: str) -> str:
    """Extract version from pyproject.toml."""
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
    match = re.search(VERSION_PATTERN, content)
    if match:
        return match.group(1)
    _fail(f"Could not find version in {file_path}")


def _validate_version(requested_version: str) -> bool:
    """Validate that requested version matches pyproject.toml."""
    current_version = _get_version_from_file(VERSION_FILE)
    if current_version != requested_version:
        _fail(
            f"Version mismatch!\n"
            f"  Requested: {requested_version}\n"
            f"  In {VERSION_FILE}: {current_version}\n"
            f"Please update {VERSION_FILE} to {requested_version} first."
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
            for line in dirty.splitlines()[:10]:
                print(f"     {line}")
            if len(dirty.splitlines()) > 10:
                print(f"     ... and {len(dirty.splitlines()) - 10} more files")
            print()
    except subprocess.CalledProcessError:
        pass


# ============================================================================
# Signing and Verification
# ============================================================================


def _checksum_artifact(artifact_path: str) -> str:
    """Create SHA512 checksum for artifact in the standard ``sha512sum`` layout.

    The file is written as ``<digest>  <filename>\n`` so that voters can verify
    with the standard ``sha512sum -c <file>.sha512`` recipe without having to
    splice the filename in by hand.
    """
    checksum_path = f"{artifact_path}.sha512"
    sha512_hash = hashlib.sha512()
    with open(artifact_path, "rb") as f:
        while chunk := f.read(65536):
            sha512_hash.update(chunk)
    artifact_filename = os.path.basename(artifact_path)
    with open(checksum_path, "w", encoding="utf-8") as f:
        f.write(f"{sha512_hash.hexdigest()}  {artifact_filename}\n")
    print(f"  ✓ Created SHA512 checksum: {checksum_path}")
    return checksum_path


def _sign_artifact(artifact_path: str, skip_signing: bool = False) -> tuple[Optional[str], str]:
    """Sign artifact with GPG (unless skipped) and create SHA512 checksum."""
    signature_path: Optional[str] = None
    if not skip_signing:
        signature_path = f"{artifact_path}.asc"
        _run_command(
            ["gpg", "--armor", "--output", signature_path, "--detach-sig", artifact_path],
            description="",
            error_message="Error signing artifact",
            capture_output=False,
        )
        print(f"  ✓ Created GPG signature: {signature_path}")
    else:
        print("  ⊘ Skipping GPG signature (--skip-signing)")

    checksum_path = _checksum_artifact(artifact_path)
    return (signature_path, checksum_path)


def _verify_artifact_signature(artifact_path: str, signature_path: str) -> bool:
    """Verify GPG signature of artifact."""
    if not os.path.exists(signature_path):
        print(f"    ✗ Signature file not found: {signature_path}")
        return False

    try:
        result = subprocess.run(
            ["gpg", "--verify", signature_path, artifact_path],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            print("    ✓ GPG signature is valid")
            return True
        else:
            print("    ✗ GPG signature verification failed")
            return False
    except subprocess.CalledProcessError:
        return False


def _verify_artifact_checksum(artifact_path: str, checksum_path: str) -> bool:
    """Verify SHA512 checksum of artifact."""
    if not os.path.exists(checksum_path):
        print(f"    ✗ Checksum file not found: {checksum_path}")
        return False

    # Read expected checksum
    with open(checksum_path, "r", encoding="utf-8") as f:
        expected_checksum = f.read().strip().split()[0]

    # Calculate actual checksum
    sha512_hash = hashlib.sha512()
    with open(artifact_path, "rb") as f:
        while chunk := f.read(65536):
            sha512_hash.update(chunk)

    actual_checksum = sha512_hash.hexdigest()

    if actual_checksum == expected_checksum:
        print("    ✓ SHA512 checksum is valid")
        return True
    else:
        print("    ✗ SHA512 checksum mismatch!")
        return False


def _verify_artifact_complete(artifact_path: str, skip_signing: bool = False) -> bool:
    """Verify artifact and its signature/checksum files."""
    print(f"\nVerifying artifact: {os.path.basename(artifact_path)}")

    if not os.path.exists(artifact_path):
        print(f"    ✗ Artifact not found: {artifact_path}")
        return False

    # Verify signature (unless skipped) and checksum
    checksum_path = f"{artifact_path}.sha512"
    checksum_valid = _verify_artifact_checksum(artifact_path, checksum_path)

    if skip_signing:
        if checksum_valid:
            print(f"  ✓ Checks passed for {os.path.basename(artifact_path)} (signing skipped)\n")
            return True
        return False

    signature_path = f"{artifact_path}.asc"
    sig_valid = _verify_artifact_signature(artifact_path, signature_path)

    if sig_valid and checksum_valid:
        print(f"  ✓ All checks passed for {os.path.basename(artifact_path)}\n")
        return True
    return False


# ============================================================================
# Step 1: Git Archive
# ============================================================================


def _create_git_archive(
    version: str, rc_num: str, output_dir: str = "dist", skip_signing: bool = False
) -> str:
    """Create git archive tar.gz for voting."""
    print(f"Creating git archive for version {version}-incubating...")

    os.makedirs(output_dir, exist_ok=True)

    archive_name = f"apache-burr-{version}-incubating-src.tar.gz"
    archive_path = os.path.join(output_dir, archive_name)
    prefix = f"apache-burr-{version}-incubating-src/"

    _run_command(
        [
            "git",
            "archive",
            "HEAD",
            f"--prefix={prefix}",
            "--format=tar.gz",
            "--output",
            archive_path,
        ],
        description="",
        error_message="Error creating git archive",
        capture_output=False,
    )
    print(f"  ✓ Created git archive: {archive_path}")

    file_size = os.path.getsize(archive_path)
    print(f"  ✓ Archive size: {file_size:,} bytes")

    print("Signing archive..." if not skip_signing else "Creating checksum for archive...")
    _sign_artifact(archive_path, skip_signing=skip_signing)

    # Verify
    if not _verify_artifact_complete(archive_path, skip_signing=skip_signing):
        _fail("Archive verification failed!")

    return archive_path


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


def _build_sdist_from_git(version: str, output_dir: str = "dist") -> str:
    """Build source distribution from git using flit."""
    _print_step(1, 2, "Building sdist with flit")

    os.makedirs(output_dir, exist_ok=True)
    _remove_ui_build_artifacts()
    _check_git_working_tree()

    env = os.environ.copy()
    env["FLIT_USE_VCS"] = "0"
    source_epoch = _source_date_epoch(version, output_dir)
    if source_epoch is not None:
        env["SOURCE_DATE_EPOCH"] = str(source_epoch)
    _run_command(
        ["flit", "build", "--format", "sdist"],
        description="Running flit build --format sdist...",
        error_message="Failed to build sdist",
        success_message="flit sdist created successfully",
        env=env,
    )

    # Find and rename sdist
    expected_pattern = f"dist/apache_burr-{version.lower()}.tar.gz"
    sdist_files = glob.glob(expected_pattern)

    if not sdist_files:
        _fail(f"Could not find sdist: {expected_pattern}")

    original_sdist = sdist_files[0]
    apache_sdist = os.path.join(
        output_dir, f"apache-burr-{version.lower()}-incubating-sdist.tar.gz"
    )

    if os.path.exists(apache_sdist):
        os.remove(apache_sdist)

    shutil.move(original_sdist, apache_sdist)
    print(f"    ✓ Renamed to: {os.path.basename(apache_sdist)}")

    return apache_sdist


def _source_date_epoch(version: str, output_dir: str = "dist") -> Optional[int]:
    """Use the source archive timestamp when available so local rebuilds are comparable."""
    source_archive = os.path.join(output_dir, f"apache-burr-{version}-incubating-src.tar.gz")
    if os.path.exists(source_archive):
        return int(os.path.getmtime(source_archive))
    return None


# ============================================================================
# Step 3: Build Wheel (SIMPLIFIED!)
# ============================================================================


def _build_ui_artifacts() -> None:
    """Build UI artifacts (npm build + copy to burr/tracking/server/build).

    This replicates the logic from burr.cli.__main__.run_build_ui_bash_commands()
    without requiring burr to be installed.
    """
    print("Building UI artifacts...")

    ui_source_dir = "telemetry/ui"
    ui_build_dir = "burr/tracking/server/build"

    # Clean existing UI build
    if os.path.exists(ui_build_dir):
        shutil.rmtree(ui_build_dir)

    # Install npm dependencies
    _run_command(
        ["npm", "install", "--prefix", ui_source_dir],
        description="Installing npm dependencies...",
        error_message="npm install failed",
        success_message="npm dependencies installed",
    )

    # Build UI with npm
    _run_command(
        ["npm", "run", "build", "--prefix", ui_source_dir],
        description="Building UI with npm...",
        error_message="npm build failed",
        success_message="npm build completed",
    )

    # Copy build artifacts
    print("  Copying build artifacts...")
    os.makedirs(ui_build_dir, exist_ok=True)
    ui_output = os.path.join(ui_source_dir, "build")

    try:
        shutil.copytree(ui_output, ui_build_dir, dirs_exist_ok=True)
        print("    ✓ Build artifacts copied")
    except Exception as e:
        _fail(f"Failed to copy build artifacts: {e}")

    # Verify
    if not os.path.exists(ui_build_dir) or not os.listdir(ui_build_dir):
        _fail(f"UI build directory is empty: {ui_build_dir}")


def _prepare_wheel_contents() -> tuple[bool, bool, Optional[str], list[tuple[str, str]]]:
    """Prepare wheel contents and temporarily remove files excluded from the sdist."""
    burr_examples_dir = "burr/examples"
    source_examples_dir = "examples"
    removed_files: list[tuple[str, str]] = []

    if not os.path.exists(source_examples_dir):
        print(f"    ⚠️  {source_examples_dir} not found")
        return (False, False, None, removed_files)

    # Check if burr/examples is a symlink (should be in dev repo)
    was_symlink = False
    symlink_target = None

    # Use lexists (not exists) so we detect broken symlinks too — CI runners
    # sometimes check out burr/examples as a symlink whose relative target
    # doesn't resolve from the working directory, and os.path.exists would
    # return False for such a link while os.makedirs would still blow up on it.
    if os.path.lexists(burr_examples_dir):
        if os.path.islink(burr_examples_dir):
            was_symlink = True
            symlink_target = os.readlink(burr_examples_dir)
            print(f"  Removing symlink: burr/examples -> {symlink_target}")
            os.remove(burr_examples_dir)
        else:
            shutil.rmtree(burr_examples_dir)

    # Copy the 4 required examples
    print("  Copying examples to burr/examples/...")
    os.makedirs(burr_examples_dir, exist_ok=True)

    # Copy __init__.py
    init_src = os.path.join(source_examples_dir, "__init__.py")
    if os.path.exists(init_src):
        shutil.copy2(init_src, os.path.join(burr_examples_dir, "__init__.py"))

    # Copy example directories
    for example_dir in REQUIRED_EXAMPLES[1:]:  # Skip __init__.py
        src_path = os.path.join(source_examples_dir, example_dir)
        dest_path = os.path.join(burr_examples_dir, example_dir)

        if os.path.exists(src_path) and os.path.isdir(src_path):
            shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
            print(f"    ✓ Copied {example_dir}")

    # Keep wheel contents aligned with the sdist so rebuild verification compares like-for-like artifacts.
    excluded_wheel_files = [
        "burr/tracking/server/s3/deployment/terraform/.gitignore",
    ]
    for path in excluded_wheel_files:
        if os.path.exists(path):
            backup_dir = tempfile.mkdtemp(prefix="apache-release-wheel-")
            backup_path = os.path.join(backup_dir, os.path.basename(path))
            os.replace(path, backup_path)
            removed_files.append((path, backup_path))
            print(f"    ✓ Temporarily excluded {path}")

    return (True, was_symlink, symlink_target, removed_files)


def _cleanup_wheel_contents(
    was_symlink: bool, symlink_target: Optional[str], removed_files: list[tuple[str, str]]
) -> None:
    """Restore temporary wheel-build changes after the wheel build finishes."""
    burr_examples_dir = "burr/examples"

    if os.path.exists(burr_examples_dir):
        shutil.rmtree(burr_examples_dir)

        if was_symlink and symlink_target:
            print(f"  Restoring symlink: burr/examples -> {symlink_target}")
            os.symlink(symlink_target, burr_examples_dir)
            print("    ✓ Symlink restored")

    for original_path, backup_path in removed_files:
        if os.path.exists(backup_path):
            os.replace(backup_path, original_path)
            print(f"  Restored {original_path}")
            backup_dir = os.path.dirname(backup_path)
            if os.path.isdir(backup_dir):
                shutil.rmtree(backup_dir)


def _build_wheel_from_current_dir(version: str, output_dir: str = "dist") -> str:
    """Build wheel from current directory (matches what voters do).

    This is MUCH simpler than the old approach:
    - No temp directory extraction
    - No copying UI between directories
    - Just build in place and clean up
    """
    _print_step(1, 3, "Building UI artifacts")
    _build_ui_artifacts()

    _print_step(2, 3, "Preparing wheel contents")
    copied, was_symlink, symlink_target, removed_files = _prepare_wheel_contents()

    _print_step(3, 3, "Building wheel with flit")

    try:
        env = os.environ.copy()
        env["FLIT_USE_VCS"] = "0"
        source_epoch = _source_date_epoch(version, output_dir)
        if source_epoch is not None:
            env["SOURCE_DATE_EPOCH"] = str(source_epoch)

        _run_command(
            ["flit", "build", "--format", "wheel"],
            description="",
            error_message="Wheel build failed",
            success_message="Wheel built successfully",
            env=env,
        )

        # Find the wheel
        wheel_pattern = f"dist/apache_burr-{version}*.whl"
        wheel_files = glob.glob(wheel_pattern)

        if not wheel_files:
            _fail(f"No wheel found matching: {wheel_pattern}")

        wheel_path = wheel_files[0]
        print(f"    ✓ Wheel created: {os.path.basename(wheel_path)}")

        return wheel_path

    finally:
        # Always restore symlinks
        if copied:
            _cleanup_wheel_contents(was_symlink, symlink_target, removed_files)


def _verify_wheel(wheel_path: str) -> bool:
    """Verify wheel contents are correct."""
    import zipfile

    print(f"  Verifying wheel contents: {os.path.basename(wheel_path)}")

    try:
        with zipfile.ZipFile(wheel_path, "r") as whl:
            file_list = whl.namelist()

            # Check for UI build artifacts
            ui_files = [f for f in file_list if "burr/tracking/server/build/" in f]
            if not ui_files:
                print("    ✗ No UI build artifacts found")
                return False
            print(f"    ✓ Found {len(ui_files)} UI build files")

            # Check for required examples
            for example in REQUIRED_EXAMPLES:
                prefix = f"burr/examples/{example}"
                example_files = [f for f in file_list if f.startswith(prefix)]
                if not example_files:
                    print(f"    ✗ Required example not found: {example}")
                    return False

            print("    ✓ All 4 required examples found")
            print(f"    ✓ Wheel contains {len(file_list)} total files")
            return True

    except Exception as e:
        print(f"    ✗ Error verifying wheel: {e}")
        return False


def _verify_wheel_with_twine(wheel_path: str) -> bool:
    """Verify wheel metadata and package validity using twine."""
    print(f"  Verifying wheel with twine: {os.path.basename(wheel_path)}")

    try:
        subprocess.run(
            ["twine", "check", wheel_path],
            check=True,
            capture_output=True,
            text=True,
        )
        print("    ✓ Twine check passed")
        print("    ✓ Wheel metadata is valid")
        return True
    except subprocess.CalledProcessError as e:
        print("\n❌ Twine metadata validation failed\n")
        print("Twine output:")
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr)
        _fail("Wheel failed twine validation - see output above for details")


# ============================================================================
# Upload to Apache SVN
# ============================================================================


def _collect_all_artifacts(version: str, output_dir: str = "dist") -> list[str]:
    """Collect all artifacts for upload."""
    if not os.path.exists(output_dir):
        return []

    artifacts = []
    for filename in os.listdir(output_dir):
        # Match both incubating artifacts and wheel (which doesn't have -incubating suffix)
        version_match = f"{version}-incubating" in filename or f"{version}" in filename
        if version_match:
            if any(filename.endswith(ext) for ext in [".tar.gz", ".whl", ".asc", ".sha512"]):
                artifacts.append(os.path.join(output_dir, filename))

    return sorted(artifacts)


def _upload_to_svn(
    version: str,
    rc_num: str,
    apache_id: str,
    artifacts: list[str],
    dry_run: bool = False,
) -> Optional[str]:
    """Upload artifacts to Apache SVN distribution repository."""
    svn_url = f"https://dist.apache.org/repos/dist/dev/incubator/{PROJECT_SHORT_NAME}/{version}-incubating-RC{rc_num}"

    if dry_run:
        print(f"\n[DRY RUN] Would upload to: {svn_url}")
        return svn_url

    print(f"Uploading to: {svn_url}")

    try:
        # Create directory
        subprocess.run(
            [
                "svn",
                "mkdir",
                "--parents",
                "-m",
                f"Creating directory for {version}-incubating-RC{rc_num}",
                svn_url,
            ],
            check=True,
        )

        # Upload each file
        for file_path in artifacts:
            filename = os.path.basename(file_path)
            print(f"  Uploading {filename}...")
            subprocess.run(
                [
                    "svn",
                    "import",
                    file_path,
                    f"{svn_url}/{filename}",
                    "-m",
                    f"Adding {filename}",
                    "--username",
                    apache_id,
                ],
                check=True,
            )

        print(f"\n✅ Artifacts uploaded to: {svn_url}")
        return svn_url

    except subprocess.CalledProcessError as e:
        print(f"Error during SVN upload: {e}")
        return None


def _generate_vote_email(version: str, rc_num: str, svn_url: str) -> str:
    """Generate [VOTE] email from template."""
    context = _build_vote_email_context(version=version, rc_num=rc_num, svn_url=svn_url)
    return _render_template("vote_email.j2", context)


def _generate_result_email(
    version: str,
    rc_num: str,
    binding_yes: int,
    non_binding_yes: int,
    abstain: int,
    binding_no: int,
    non_binding_no: int,
    vote_thread_url: Optional[str] = None,
) -> str:
    """Generate [RESULT] email from template."""
    context = _build_result_email_context(
        version=version,
        rc_num=rc_num,
        binding_yes=binding_yes,
        non_binding_yes=non_binding_yes,
        abstain=abstain,
        binding_no=binding_no,
        non_binding_no=non_binding_no,
        vote_thread_url=vote_thread_url,
    )
    return _render_template("result_email.j2", context)


def _generate_announcement_email(
    version: str,
    pypi_url: Optional[str] = None,
    downloads_url: Optional[str] = None,
    changelog_summary: Optional[str] = None,
    previous_tag: Optional[str] = None,
) -> str:
    """Generate [ANNOUNCE] email from template."""
    context = _build_announcement_email_context(
        version=version,
        pypi_url=pypi_url,
        downloads_url=downloads_url,
        changelog_summary=changelog_summary,
        previous_tag=previous_tag,
    )
    return _render_template("announce_email.j2", context)


def _promotion_source_url(version: str, rc_num: str, dev_svn_root: str) -> str:
    """Return the SVN URL for a voted RC in dist/dev."""
    return f"{dev_svn_root}/{version}-incubating-RC{rc_num}"


def _promotion_target_url(version: str, release_svn_root: str) -> str:
    """Return the SVN URL for the final per-version release directory.

    Releases are published under a per-version subdirectory
    (e.g. dist/release/incubator/burr/0.42.0), alongside any existing
    releases and the shared KEYS file at the project root.
    """
    return f"{release_svn_root}/{version}"


def _promotion_commit_message(version: str, rc_num: str) -> str:
    """Return the SVN commit message for a promotion."""
    return f"Promote Apache Burr {version}-incubating RC{rc_num} to release"


def _expected_promotion_artifact_patterns(version: str) -> dict[str, str]:
    """Return the required artifact patterns for a final release promotion."""
    return {
        "source_archive": f"apache-burr-{version}-incubating-src.tar.gz",
        "sdist": f"apache-burr-{version}-incubating-sdist.tar.gz",
        "wheel": f"apache_burr-{version}-*.whl",
    }


def _find_single_glob_match(directory: str, pattern: str, description: str) -> str:
    matches = sorted(glob.glob(os.path.join(directory, pattern)))
    if not matches:
        _fail(f"Missing required {description}: {pattern}")
    if len(matches) > 1:
        names = ", ".join(os.path.basename(match) for match in matches)
        _fail(f"Expected exactly one {description} for pattern {pattern}, found: {names}")
    return matches[0]


def _validate_promotion_artifacts(rc_checkout_dir: str, version: str) -> list[str]:
    """Validate the expected release artifacts exist in the RC checkout."""
    artifacts: list[str] = []
    patterns = _expected_promotion_artifact_patterns(version)

    source_archive = _find_single_glob_match(
        rc_checkout_dir, patterns["source_archive"], "source archive"
    )
    sdist = _find_single_glob_match(rc_checkout_dir, patterns["sdist"], "source distribution")
    wheel = _find_single_glob_match(rc_checkout_dir, patterns["wheel"], "wheel")

    for artifact_path in [source_archive, sdist, wheel]:
        artifacts.append(artifact_path)
        for suffix in [".asc", ".sha512"]:
            companion_path = f"{artifact_path}{suffix}"
            if not os.path.exists(companion_path):
                _fail(f"Missing required companion artifact: {os.path.basename(companion_path)}")
            artifacts.append(companion_path)

    return sorted(artifacts)


def _twine_upload_command(promoted_artifacts: list[str]) -> str:
    """Return the PyPI upload command for the final release artifacts."""
    upload_candidates = [
        artifact
        for artifact in promoted_artifacts
        if artifact.endswith(".whl") or artifact.endswith("-incubating-sdist.tar.gz")
    ]
    upload_names = " ".join(sorted(os.path.basename(artifact) for artifact in upload_candidates))
    return f"twine upload {upload_names}"


def _svn_checkout(url: str, checkout_dir: str) -> None:
    """Check out an SVN URL into a local directory."""
    _run_command(
        ["svn", "checkout", url, checkout_dir],
        description=f"Checking out SVN path: {url}",
        error_message=f"SVN checkout failed for {url}",
        success_message="SVN checkout completed",
    )


def _svn_target_exists(url: str) -> bool:
    """Return True if an SVN URL already exists in the repository."""
    result = subprocess.run(
        ["svn", "info", url],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _promote_with_server_copy(
    source_url: str,
    target_url: str,
    message: str,
    apache_id: str,
    dry_run: bool = False,
) -> bool:
    """Promote a voted RC by copying it server-side into the release tree.

    A single ``svn cp <rc_url> <release>/<version>`` is atomic: it copies the
    voted RC directory (artifacts plus their .asc / .sha512 companions) into a
    new per-version release directory in one commit, without downloading the
    artifacts. Existing release directories and the shared KEYS file are left
    untouched, matching the additive layout used in dist/release.
    """
    command = [
        "svn",
        "cp",
        source_url,
        target_url,
        "-m",
        message,
        "--username",
        apache_id,
    ]
    if dry_run:
        print(f"  [DRY RUN] Would run: {' '.join(command)}")
        return True

    _run_command(
        command,
        description="Promoting RC to release via server-side copy...",
        error_message="SVN server-side copy failed for promotion",
        success_message="Release promoted",
        capture_output=False,
    )
    return True


# ============================================================================
# Command Handlers
# ============================================================================


def cmd_archive(args) -> bool:
    """Handle 'archive' subcommand."""
    _print_section(f"Creating Git Archive - v{args.version}-RC{args.rc_num}")
    skip_signing = getattr(args, "skip_signing", False)

    _verify_project_root()
    _validate_version(args.version)
    _check_git_working_tree()

    archive_path = _create_git_archive(
        args.version, args.rc_num, args.output_dir, skip_signing=skip_signing
    )
    print(f"\n✅ Archive created: {archive_path}")
    return True


def cmd_sdist(args) -> bool:
    """Handle 'sdist' subcommand."""
    _print_section(f"Building Source Distribution - v{args.version}-RC{args.rc_num}")
    skip_signing = getattr(args, "skip_signing", False)

    _verify_project_root()
    _validate_version(args.version)

    sdist_path = _build_sdist_from_git(args.version, args.output_dir)

    _print_step(2, 2, "Signing sdist" if not skip_signing else "Checksumming sdist")
    _sign_artifact(sdist_path, skip_signing=skip_signing)

    if not _verify_artifact_complete(sdist_path, skip_signing=skip_signing):
        _fail("sdist verification failed!")

    print(f"\n✅ Source distribution created: {sdist_path}")
    return True


def cmd_wheel(args) -> bool:
    """Handle 'wheel' subcommand."""
    _print_section(f"Building Wheel - v{args.version}-RC{args.rc_num}")
    skip_signing = getattr(args, "skip_signing", False)

    _verify_project_root()
    _validate_version(args.version)

    wheel_path = _build_wheel_from_current_dir(args.version, args.output_dir)

    print("\nVerifying wheel with twine...")
    if not _verify_wheel_with_twine(wheel_path):
        _fail("Twine verification failed!")

    print("\nVerifying wheel contents...")
    if not _verify_wheel(wheel_path):
        _fail("Wheel verification failed!")

    print("\nSigning wheel..." if not skip_signing else "\nChecksumming wheel...")
    _sign_artifact(wheel_path, skip_signing=skip_signing)

    if not _verify_artifact_complete(wheel_path, skip_signing=skip_signing):
        _fail("Wheel signature/checksum verification failed!")

    print(f"\n✅ Wheel created and verified: {os.path.basename(wheel_path)}")
    return True


def cmd_upload(args) -> bool:
    """Handle 'upload' subcommand."""
    _print_section(f"Uploading Artifacts - v{args.version}-RC{args.rc_num}")

    artifacts = _collect_all_artifacts(args.version, args.artifacts_dir)
    if not artifacts:
        _fail(f"No artifacts found in {args.artifacts_dir}")

    print(f"Found {len(artifacts)} artifact(s):")
    for artifact in artifacts:
        print(f"  - {os.path.basename(artifact)}")

    svn_url = _upload_to_svn(
        args.version, args.rc_num, args.apache_id, artifacts, dry_run=args.dry_run
    )

    if not svn_url:
        return False

    return True


def cmd_promote(args) -> bool:
    """Handle 'promote' subcommand."""
    _print_section(f"Promoting Release Candidate - {args.rc_label}")
    _verify_project_root()

    version, rc_num = _parse_rc_label(args.rc_label)
    source_url = _promotion_source_url(version, rc_num, args.dev_svn_root)
    target_url = _promotion_target_url(version, args.release_svn_root)

    print(f"Source RC URL: {source_url}")
    print(f"Release URL:   {target_url}")
    if args.dry_run:
        print("\n*** DRY RUN MODE ***")

    if _svn_target_exists(target_url):
        _fail(
            f"Release path already exists: {target_url}\n"
            "Refusing to overwrite an already-promoted release."
        )

    with tempfile.TemporaryDirectory(prefix="burr-promote-") as temp_dir:
        rc_checkout_dir = os.path.join(temp_dir, "rc")
        _svn_checkout(source_url, rc_checkout_dir)

        print("\nValidating expected artifacts...")
        validated_artifacts = _validate_promotion_artifacts(rc_checkout_dir, version)
        for artifact in validated_artifacts:
            print(f"  ✓ {os.path.basename(artifact)}")

    print("\nPromoting RC into release...")
    _promote_with_server_copy(
        source_url,
        target_url,
        _promotion_commit_message(version, rc_num),
        args.apache_id,
        dry_run=args.dry_run,
    )

    print("\nPromotion summary:")
    print(f"  Release path: {target_url}")
    for artifact in validated_artifacts:
        print(f"  - {os.path.basename(artifact)}")

    print("\nPyPI upload command:")
    print(f"  {_twine_upload_command(validated_artifacts)}")

    return True


def cmd_verify(args) -> bool:
    """Handle 'verify' subcommand."""
    _print_section(f"Verifying Artifacts - v{args.version}-RC{args.rc_num}")

    artifacts = _collect_all_artifacts(args.version, args.artifacts_dir)

    if not artifacts:
        print(f"⚠️  No artifacts found in {args.artifacts_dir}")
        return False

    all_valid = True
    for artifact in artifacts:
        if artifact.endswith((".asc", ".sha512")):
            continue  # Skip signature/checksum files
        if not _verify_artifact_complete(artifact):
            all_valid = False

    if all_valid:
        print("✅ All artifacts verified successfully!")
    else:
        print("❌ Some artifacts failed verification")

    return all_valid


def cmd_vote_email(args) -> bool:
    """Handle 'vote-email' subcommand."""
    _verify_project_root()
    _validate_version(args.version)

    content = _render_template(
        "vote_email.j2",
        _build_vote_email_context(
            version=args.version,
            rc_num=args.rc_num,
            svn_url=args.svn_url,
            pypi_url=args.pypi_url,
            keys_url=args.keys_url,
            changelog_summary=args.changelog_summary,
            previous_tag=args.previous_tag,
        ),
    )
    _emit_email_output(content, copy_to_clipboard=args.copy)
    return True


def cmd_result_email(args) -> bool:
    """Handle 'result-email' subcommand."""
    _verify_project_root()
    _validate_version(args.version)

    content = _generate_result_email(
        version=args.version,
        rc_num=args.rc_num,
        binding_yes=args.binding_yes,
        non_binding_yes=args.non_binding_yes,
        abstain=args.abstain,
        binding_no=args.binding_no,
        non_binding_no=args.non_binding_no,
        vote_thread_url=args.vote_thread_url,
    )
    _emit_email_output(content, copy_to_clipboard=args.copy)
    return True


def cmd_announce_email(args) -> bool:
    """Handle 'announce-email' subcommand."""
    _verify_project_root()
    _validate_version(args.version)

    content = _generate_announcement_email(
        version=args.version,
        pypi_url=args.pypi_url,
        downloads_url=args.downloads_url,
        changelog_summary=args.changelog_summary,
        previous_tag=args.previous_tag,
    )
    _emit_email_output(content, copy_to_clipboard=args.copy)
    return True


def cmd_all(args) -> bool:
    """Handle 'all' subcommand - run complete workflow."""
    _print_section(f"Apache Burr Release Process - v{args.version}-RC{args.rc_num}")

    if args.dry_run:
        print("*** DRY RUN MODE ***\n")
    skip_signing = getattr(args, "skip_signing", False)
    if skip_signing:
        print("*** SKIP SIGNING MODE ***\n")

    _verify_project_root()
    _validate_version(args.version)
    _check_git_working_tree()

    # Step 1: Git Archive
    _print_step(1, 4, "Creating git archive")
    _create_git_archive(args.version, args.rc_num, args.output_dir, skip_signing=skip_signing)

    # Step 2: Build sdist
    _print_step(2, 4, "Building sdist")
    sdist_path = _build_sdist_from_git(args.version, args.output_dir)
    _sign_artifact(sdist_path, skip_signing=skip_signing)
    if not _verify_artifact_complete(sdist_path, skip_signing=skip_signing):
        _fail("sdist verification failed!")

    # Step 3: Build wheel
    _print_step(3, 4, "Building wheel")
    wheel_path = _build_wheel_from_current_dir(args.version, args.output_dir)
    if not _verify_wheel_with_twine(wheel_path):
        _fail("Twine verification failed!")
    _sign_artifact(wheel_path, skip_signing=skip_signing)
    if not _verify_wheel(wheel_path) or not _verify_artifact_complete(
        wheel_path, skip_signing=skip_signing
    ):
        _fail("Wheel verification failed!")

    # Step 4: Upload (if not disabled)
    if not args.no_upload:
        _print_step(4, 4, "Uploading to Apache SVN")
        all_artifacts = _collect_all_artifacts(args.version, args.output_dir)
        svn_url = _upload_to_svn(
            args.version, args.rc_num, args.apache_id, all_artifacts, dry_run=args.dry_run
        )
        if not svn_url:
            _fail("SVN upload failed!")
    else:
        svn_url = f"https://dist.apache.org/repos/dist/dev/incubator/{PROJECT_SHORT_NAME}/{args.version}-incubating-RC{args.rc_num}"
        if args.dry_run:
            print(f"\n[DRY RUN] Would upload to: {svn_url}")

    # Generate email template
    _print_section("Release Complete!")
    email_content = _generate_vote_email(args.version, args.rc_num, svn_url)
    print(email_content)

    return True


# ============================================================================
# CLI Entry Point
# ============================================================================


def _add_email_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add common CLI arguments shared by email-generation commands."""
    parser.add_argument("--version", required=True, help="Version (e.g., '0.41.0')")
    parser.add_argument("--copy", action="store_true", help="Copy rendered email to clipboard")


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Apache Burr Release Script (Simplified)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # archive subcommand
    archive_parser = subparsers.add_parser("archive", help="Create git archive")
    archive_parser.add_argument("version", help="Version (e.g., '0.41.0')")
    archive_parser.add_argument("rc_num", help="RC number (e.g., '0')")
    archive_parser.add_argument("--output-dir", default="dist", help="Output directory")
    archive_parser.add_argument(
        "--skip-signing",
        action="store_true",
        help="Skip GPG signing (for CI). SHA512 checksum is still generated.",
    )

    # sdist subcommand
    sdist_parser = subparsers.add_parser("sdist", help="Build source distribution")
    sdist_parser.add_argument("version", help="Version")
    sdist_parser.add_argument("rc_num", help="RC number")
    sdist_parser.add_argument("--output-dir", default="dist")
    sdist_parser.add_argument("--skip-signing", action="store_true")

    # wheel subcommand
    wheel_parser = subparsers.add_parser("wheel", help="Build wheel")
    wheel_parser.add_argument("version", help="Version")
    wheel_parser.add_argument("rc_num", help="RC number")
    wheel_parser.add_argument("--output-dir", default="dist")
    wheel_parser.add_argument("--skip-signing", action="store_true")

    # upload subcommand
    upload_parser = subparsers.add_parser("upload", help="Upload to SVN")
    upload_parser.add_argument("version", help="Version")
    upload_parser.add_argument("rc_num", help="RC number")
    upload_parser.add_argument("apache_id", help="Apache ID")
    upload_parser.add_argument("--artifacts-dir", default="dist")
    upload_parser.add_argument("--dry-run", action="store_true")

    # promote subcommand
    promote_parser = subparsers.add_parser(
        "promote", help="Promote a voted RC from dist/dev to dist/release"
    )
    promote_parser.add_argument(
        "rc_label", help="Release candidate label, e.g. '0.42.0-RC1' or '0.42.0-incubating-RC1'"
    )
    promote_parser.add_argument("apache_id", help="Apache ID")
    promote_parser.add_argument("--dry-run", action="store_true")
    promote_parser.add_argument(
        "--dev-svn-root",
        default=DEFAULT_DEV_SVN_ROOT,
        help="SVN root for RC artifacts in dist/dev",
    )
    promote_parser.add_argument(
        "--release-svn-root",
        default=DEFAULT_RELEASE_SVN_ROOT,
        help="SVN root for promoted artifacts in dist/release",
    )

    # verify subcommand
    verify_parser = subparsers.add_parser("verify", help="Verify artifacts")
    verify_parser.add_argument("version", help="Version")
    verify_parser.add_argument("rc_num", help="RC number")
    verify_parser.add_argument("--artifacts-dir", default="dist")

    # vote-email subcommand
    vote_email_parser = subparsers.add_parser("vote-email", help="Generate release vote email")
    _add_email_common_arguments(vote_email_parser)
    vote_email_parser.add_argument("--rc", dest="rc_num", required=True, help="RC number")
    vote_email_parser.add_argument("--svn-url", help="Override the Apache SVN RC URL")
    vote_email_parser.add_argument("--pypi-url", help="Override the PyPI RC package URL")
    vote_email_parser.add_argument("--keys-url", help="Override the Apache KEYS URL")
    vote_email_parser.add_argument(
        "--previous-tag",
        help="Use a specific previous release tag when building the changelog summary",
    )
    vote_email_parser.add_argument(
        "--changelog-summary",
        help="Provide a custom changelog summary instead of generating one from git history",
    )

    # result-email subcommand
    result_email_parser = subparsers.add_parser(
        "result-email", help="Generate release vote result email"
    )
    _add_email_common_arguments(result_email_parser)
    result_email_parser.add_argument("--rc", dest="rc_num", required=True, help="RC number")
    result_email_parser.add_argument(
        "--binding-yes", type=int, required=True, help="Number of binding +1 votes"
    )
    result_email_parser.add_argument(
        "--non-binding-yes", type=int, default=0, help="Number of non-binding +1 votes"
    )
    result_email_parser.add_argument("--abstain", type=int, default=0, help="Number of 0 votes")
    result_email_parser.add_argument(
        "--binding-no", type=int, default=0, help="Number of binding -1 votes"
    )
    result_email_parser.add_argument(
        "--non-binding-no", type=int, default=0, help="Number of non-binding -1 votes"
    )
    result_email_parser.add_argument("--vote-thread-url", help="Link to the vote thread archive")

    # announce-email subcommand
    announce_email_parser = subparsers.add_parser(
        "announce-email", help="Generate release announcement email"
    )
    _add_email_common_arguments(announce_email_parser)
    announce_email_parser.add_argument("--pypi-url", help="Override the PyPI release URL")
    announce_email_parser.add_argument(
        "--downloads-url",
        help="Override the Apache downloads URL",
    )
    announce_email_parser.add_argument(
        "--previous-tag",
        help="Use a specific previous release tag when building the changelog summary",
    )
    announce_email_parser.add_argument(
        "--changelog-summary",
        help="Provide a custom changelog summary instead of generating one from git history",
    )

    # all subcommand
    all_parser = subparsers.add_parser("all", help="Run complete workflow")
    all_parser.add_argument("version", help="Version")
    all_parser.add_argument("rc_num", help="RC number")
    all_parser.add_argument("apache_id", help="Apache ID")
    all_parser.add_argument("--output-dir", default="dist")
    all_parser.add_argument("--dry-run", action="store_true")
    all_parser.add_argument("--no-upload", action="store_true")
    all_parser.add_argument(
        "--skip-signing",
        action="store_true",
        help="Skip GPG signing (for CI). SHA512 checksum is still generated.",
    )

    return parser


def main():
    """Main entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    # Validate environment
    _validate_environment_for_command(args)

    # Dispatch to command handler
    try:
        if args.command == "archive":
            success = cmd_archive(args)
        elif args.command == "sdist":
            success = cmd_sdist(args)
        elif args.command == "wheel":
            success = cmd_wheel(args)
        elif args.command == "upload":
            success = cmd_upload(args)
        elif args.command == "promote":
            success = cmd_promote(args)
        elif args.command == "verify":
            success = cmd_verify(args)
        elif args.command == "vote-email":
            success = cmd_vote_email(args)
        elif args.command == "result-email":
            success = cmd_result_email(args)
        elif args.command == "announce-email":
            success = cmd_announce_email(args)
        elif args.command == "all":
            success = cmd_all(args)
        else:
            _fail(f"Unknown command: {args.command}")
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
