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
from typing import NoReturn, Optional

# --- Configuration ---
PROJECT_SHORT_NAME = "burr"
VERSION_FILE = "pyproject.toml"
VERSION_PATTERN = r'version\s*=\s*"(\d+\.\d+\.\d+)"'

# Required examples for wheel (from pyproject.toml)
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
    """Validate required tools for the requested command."""
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

    required_tools = command_requirements.get(args.command, ["git", "gpg"])

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


def _sign_artifact(artifact_path: str) -> tuple[str, str]:
    """Sign artifact with GPG and create SHA512 checksum."""
    signature_path = f"{artifact_path}.asc"
    checksum_path = f"{artifact_path}.sha512"

    # GPG signature
    try:
        subprocess.run(
            ["gpg", "--armor", "--output", signature_path, "--detach-sig", artifact_path],
            check=True,
        )
        print(f"  ✓ Created GPG signature: {signature_path}")
    except subprocess.CalledProcessError as e:
        _fail(f"Error signing artifact: {e}")

    # SHA512 checksum
    sha512_hash = hashlib.sha512()
    with open(artifact_path, "rb") as f:
        while chunk := f.read(65536):
            sha512_hash.update(chunk)

    with open(checksum_path, "w", encoding="utf-8") as f:
        f.write(f"{sha512_hash.hexdigest()}\n")
    print(f"  ✓ Created SHA512 checksum: {checksum_path}")

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


def _verify_artifact_complete(artifact_path: str) -> bool:
    """Verify artifact and its signature/checksum files."""
    print(f"\nVerifying artifact: {os.path.basename(artifact_path)}")

    if not os.path.exists(artifact_path):
        print(f"    ✗ Artifact not found: {artifact_path}")
        return False

    # Verify signature and checksum
    signature_path = f"{artifact_path}.asc"
    checksum_path = f"{artifact_path}.sha512"

    sig_valid = _verify_artifact_signature(artifact_path, signature_path)
    checksum_valid = _verify_artifact_checksum(artifact_path, checksum_path)

    if sig_valid and checksum_valid:
        print(f"  ✓ All checks passed for {os.path.basename(artifact_path)}\n")
        return True
    return False


# ============================================================================
# Step 1: Git Archive
# ============================================================================


def _create_git_archive(version: str, rc_num: str, output_dir: str = "dist") -> str:
    """Create git archive tar.gz for voting."""
    print(f"Creating git archive for version {version}-incubating...")

    os.makedirs(output_dir, exist_ok=True)

    archive_name = f"apache-burr-{version}-incubating-src.tar.gz"
    archive_path = os.path.join(output_dir, archive_name)
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

    file_size = os.path.getsize(archive_path)
    print(f"  ✓ Archive size: {file_size:,} bytes")

    # Sign the archive
    print("Signing archive...")
    _sign_artifact(archive_path)

    # Verify
    if not _verify_artifact_complete(archive_path):
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

    print("  Running flit build --format sdist...")
    try:
        env = os.environ.copy()
        env["FLIT_USE_VCS"] = "0"
        subprocess.run(
            ["flit", "build", "--format", "sdist"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        print("    ✓ flit sdist created successfully")
    except subprocess.CalledProcessError as e:
        _fail(f"Failed to build sdist: {e.stderr}")

    # Find and rename sdist
    expected_pattern = f"dist/apache_burr-{version.lower()}.tar.gz"
    sdist_files = glob.glob(expected_pattern)

    if not sdist_files:
        _fail(f"Could not find sdist: {expected_pattern}")

    original_sdist = sdist_files[0]
    apache_sdist = os.path.join(
        output_dir, f"apache-burr-{version.lower()}-incubating-src-sdist.tar.gz"
    )

    if os.path.exists(apache_sdist):
        os.remove(apache_sdist)

    shutil.move(original_sdist, apache_sdist)
    print(f"    ✓ Renamed to: {os.path.basename(apache_sdist)}")

    return apache_sdist


# ============================================================================
# Step 3: Build Wheel (SIMPLIFIED!)
# ============================================================================


def _build_ui_artifacts() -> None:
    """Build UI artifacts using burr-admin-build-ui."""
    print("Building UI artifacts...")

    ui_build_dir = "burr/tracking/server/build"

    # Clean existing UI build
    if os.path.exists(ui_build_dir):
        shutil.rmtree(ui_build_dir)

    # Check for burr-admin-build-ui
    if shutil.which("burr-admin-build-ui") is None:
        _fail("burr-admin-build-ui not found. Install with: pip install -e .[cli]")

    # Build UI
    env = os.environ.copy()
    env["BURR_PROJECT_ROOT"] = os.getcwd()

    try:
        subprocess.run(["burr-admin-build-ui"], check=True, env=env, capture_output=True)
        print("  ✓ UI artifacts built successfully")
    except subprocess.CalledProcessError as e:
        _fail(f"Error building UI: {e}")

    # Verify
    if not os.path.exists(ui_build_dir) or not os.listdir(ui_build_dir):
        _fail(f"UI build directory is empty: {ui_build_dir}")


def _prepare_wheel_contents() -> tuple[bool, bool, Optional[str]]:
    """Handle burr/examples symlink: replace with real files for wheel."""
    burr_examples_dir = "burr/examples"
    source_examples_dir = "examples"

    if not os.path.exists(source_examples_dir):
        print(f"    ⚠️  {source_examples_dir} not found")
        return (False, False, None)

    # Check if burr/examples is a symlink (should be in dev repo)
    was_symlink = False
    symlink_target = None

    if os.path.exists(burr_examples_dir):
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

    return (True, was_symlink, symlink_target)


def _cleanup_wheel_contents(was_symlink: bool, symlink_target: Optional[str]) -> None:
    """Restore burr/examples symlink after wheel build."""
    burr_examples_dir = "burr/examples"

    if os.path.exists(burr_examples_dir):
        shutil.rmtree(burr_examples_dir)

        if was_symlink and symlink_target:
            print(f"  Restoring symlink: burr/examples -> {symlink_target}")
            os.symlink(symlink_target, burr_examples_dir)
            print("    ✓ Symlink restored")


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
    copied, was_symlink, symlink_target = _prepare_wheel_contents()

    _print_step(3, 3, "Building wheel with flit")

    try:
        env = os.environ.copy()
        env["FLIT_USE_VCS"] = "0"

        subprocess.run(
            ["flit", "build", "--format", "wheel"],
            env=env,
            check=True,
            capture_output=True,
        )
        print("    ✓ Wheel built successfully")

        # Find the wheel
        wheel_pattern = f"dist/apache_burr-{version}*.whl"
        wheel_files = glob.glob(wheel_pattern)

        if not wheel_files:
            _fail(f"No wheel found matching: {wheel_pattern}")

        wheel_path = wheel_files[0]
        print(f"    ✓ Wheel created: {os.path.basename(wheel_path)}")

        return wheel_path

    except subprocess.CalledProcessError as e:
        _fail(f"Wheel build failed: {e}")
    finally:
        # Always restore symlinks
        if copied:
            _cleanup_wheel_contents(was_symlink, symlink_target)


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


# ============================================================================
# Upload to Apache SVN
# ============================================================================


def _collect_all_artifacts(version: str, output_dir: str = "dist") -> list[str]:
    """Collect all artifacts for upload."""
    if not os.path.exists(output_dir):
        return []

    artifacts = []
    for filename in os.listdir(output_dir):
        if f"{version}-incubating" in filename:
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
    """Generate [VOTE] email template."""
    version_with_incubating = f"{version}-incubating"
    tag = f"v{version}-incubating-RC{rc_num}"

    return f"""[VOTE] Release Apache {PROJECT_SHORT_NAME} {version_with_incubating} (RC{rc_num})

Hi all,

This is a call for a vote on releasing Apache {PROJECT_SHORT_NAME} {version_with_incubating},
release candidate {rc_num}.

The artifacts for this release candidate can be found at:
{svn_url}

The Git tag to be voted upon is:
{tag}

Release artifacts are signed with your GPG key. The KEYS file is available at:
https://downloads.apache.org/incubator/{PROJECT_SHORT_NAME}/KEYS

Please download, verify, and test the release candidate.

Some ideas to verify the release:
1. Build from source - see README in scripts/ directory for instructions
2. Install the wheel using pip to test functionality
3. Run license verification using the verify_apache_artifacts.py script or manually check
   - Verify checksums and signatures match
   - Check LICENSE/NOTICE files are present
   - Ensure all source files have Apache headers

The vote will run for a minimum of 72 hours.
Please vote:

[ ] +1 Release this package as Apache {PROJECT_SHORT_NAME} {version_with_incubating}
[ ] +0 No opinion
[ ] -1 Do not release this package because... (reason required)

Checklist for reference:
[ ] Download links are valid
[ ] Checksums and signatures are valid
[ ] LICENSE/NOTICE files exist
[ ] No unexpected binary files in source
[ ] All source files have ASF headers
[ ] Can compile from source

On behalf of the Apache {PROJECT_SHORT_NAME} PPMC,
[Your Name]
"""


# ============================================================================
# Command Handlers
# ============================================================================


def cmd_archive(args) -> bool:
    """Handle 'archive' subcommand."""
    _print_section(f"Creating Git Archive - v{args.version}-RC{args.rc_num}")

    _verify_project_root()
    _validate_version(args.version)
    _check_git_working_tree()

    archive_path = _create_git_archive(args.version, args.rc_num, args.output_dir)
    print(f"\n✅ Archive created: {archive_path}")
    return True


def cmd_sdist(args) -> bool:
    """Handle 'sdist' subcommand."""
    _print_section(f"Building Source Distribution - v{args.version}-RC{args.rc_num}")

    _verify_project_root()
    _validate_version(args.version)

    sdist_path = _build_sdist_from_git(args.version, args.output_dir)

    _print_step(2, 2, "Signing sdist")
    _sign_artifact(sdist_path)

    if not _verify_artifact_complete(sdist_path):
        _fail("sdist verification failed!")

    print(f"\n✅ Source distribution created: {sdist_path}")
    return True


def cmd_wheel(args) -> bool:
    """Handle 'wheel' subcommand."""
    _print_section(f"Building Wheel - v{args.version}-RC{args.rc_num}")

    _verify_project_root()
    _validate_version(args.version)

    wheel_path = _build_wheel_from_current_dir(args.version, args.output_dir)

    print("\nSigning wheel...")
    _sign_artifact(wheel_path)

    print("\nVerifying wheel...")
    if not _verify_wheel(wheel_path):
        _fail("Wheel verification failed!")

    if not _verify_artifact_complete(wheel_path):
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


def cmd_all(args) -> bool:
    """Handle 'all' subcommand - run complete workflow."""
    _print_section(f"Apache Burr Release Process - v{args.version}-RC{args.rc_num}")

    if args.dry_run:
        print("*** DRY RUN MODE ***\n")

    _verify_project_root()
    _validate_version(args.version)
    _check_git_working_tree()

    # Step 1: Git Archive
    _print_step(1, 4, "Creating git archive")
    _create_git_archive(args.version, args.rc_num, args.output_dir)

    # Step 2: Build sdist
    _print_step(2, 4, "Building sdist")
    sdist_path = _build_sdist_from_git(args.version, args.output_dir)
    _sign_artifact(sdist_path)
    if not _verify_artifact_complete(sdist_path):
        _fail("sdist verification failed!")

    # Step 3: Build wheel
    _print_step(3, 4, "Building wheel")
    wheel_path = _build_wheel_from_current_dir(args.version, args.output_dir)
    _sign_artifact(wheel_path)
    if not _verify_wheel(wheel_path) or not _verify_artifact_complete(wheel_path):
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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Apache Burr Release Script (Simplified)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # archive subcommand
    archive_parser = subparsers.add_parser("archive", help="Create git archive")
    archive_parser.add_argument("version", help="Version (e.g., '0.41.0')")
    archive_parser.add_argument("rc_num", help="RC number (e.g., '0')")
    archive_parser.add_argument("--output-dir", default="dist", help="Output directory")

    # sdist subcommand
    sdist_parser = subparsers.add_parser("sdist", help="Build source distribution")
    sdist_parser.add_argument("version", help="Version")
    sdist_parser.add_argument("rc_num", help="RC number")
    sdist_parser.add_argument("--output-dir", default="dist")

    # wheel subcommand
    wheel_parser = subparsers.add_parser("wheel", help="Build wheel")
    wheel_parser.add_argument("version", help="Version")
    wheel_parser.add_argument("rc_num", help="RC number")
    wheel_parser.add_argument("--output-dir", default="dist")

    # upload subcommand
    upload_parser = subparsers.add_parser("upload", help="Upload to SVN")
    upload_parser.add_argument("version", help="Version")
    upload_parser.add_argument("rc_num", help="RC number")
    upload_parser.add_argument("apache_id", help="Apache ID")
    upload_parser.add_argument("--artifacts-dir", default="dist")
    upload_parser.add_argument("--dry-run", action="store_true")

    # verify subcommand
    verify_parser = subparsers.add_parser("verify", help="Verify artifacts")
    verify_parser.add_argument("version", help="Version")
    verify_parser.add_argument("rc_num", help="RC number")
    verify_parser.add_argument("--artifacts-dir", default="dist")

    # all subcommand
    all_parser = subparsers.add_parser("all", help="Run complete workflow")
    all_parser.add_argument("version", help="Version")
    all_parser.add_argument("rc_num", help="RC number")
    all_parser.add_argument("apache_id", help="Apache ID")
    all_parser.add_argument("--output-dir", default="dist")
    all_parser.add_argument("--dry-run", action="store_true")
    all_parser.add_argument("--no-upload", action="store_true")

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
        elif args.command == "verify":
            success = cmd_verify(args)
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
