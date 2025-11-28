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

import argparse
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys

# --- Configuration ---
# You need to fill these in for your project.
# The name of your project's short name (e.g., 'myproject').
PROJECT_SHORT_NAME = "burr"
# The file where you want to update the version number.
VERSION_FILE = "pyproject.toml"
# A regular expression pattern to find the version string in the VERSION_FILE.
VERSION_PATTERN = r'version\s*=\s*"(\d+\.\d+\.\d+)"'


def _fail(message: str) -> None:
    print(f"\n❌ {message}")
    sys.exit(1)


def get_version_from_file(file_path: str) -> str:
    """Get the version from a file."""
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
    match = re.search(VERSION_PATTERN, content)
    if match:
        version = match.group(1)
        return version
    raise ValueError(f"Could not find version in {file_path}")


def check_prerequisites():
    """Checks for necessary command-line tools and Python modules."""
    print("Checking for required tools...")
    required_tools = ["git", "gpg", "svn", "flit"]
    for tool in required_tools:
        if shutil.which(tool) is None:
            _fail(
                f"Required tool '{tool}' not found. Please install it and ensure it's in your PATH."
            )

    print("All required tools found.")


def update_version(version, _rc_num):
    """Updates the version number in the specified file."""
    print(f"Updating version in {VERSION_FILE} to {version}...")
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        # For pyproject.toml, we just update the version string directly
        new_version_string = f'version = "{version}"'
        new_content = re.sub(VERSION_PATTERN, new_version_string, content)
        if new_content == content:
            print("Error: Could not find or replace version string. Check your VERSION_PATTERN.")
            return False

        with open(VERSION_FILE, "w", encoding="utf-8") as f:
            f.write(new_content)

        print("Version updated successfully.")
        return True

    except FileNotFoundError:
        _fail(f"{VERSION_FILE} not found.")
    except (OSError, re.error) as e:
        _fail(f"An error occurred while updating the version: {e}")


def sign_artifacts(archive_name: str) -> list[str]:
    """Creates signed files for the designated artifact."""
    files = []
    # Sign the tarball with GPG. The user must have a key configured.
    try:
        subprocess.run(
            ["gpg", "--armor", "--output", f"{archive_name}.asc", "--detach-sig", archive_name],
            check=True,
        )
        files.append(f"{archive_name}.asc")
        print(f"Created GPG signature: {archive_name}.asc")
    except subprocess.CalledProcessError as e:
        _fail(f"Error signing tarball {archive_name}: {e}")

    # Generate SHA512 checksum.
    sha512_hash = hashlib.sha512()
    with open(archive_name, "rb") as f:
        while True:
            data = f.read(65536)
            if not data:
                break
            sha512_hash.update(data)

    with open(f"{archive_name}.sha512", "w", encoding="utf-8") as f:
        f.write(f"{sha512_hash.hexdigest()}\n")
    print(f"Created SHA512 checksum: {archive_name}.sha512")
    files.append(f"{archive_name}.sha512")
    return files


def create_release_artifacts(version, build_wheel=False) -> list[str]:
    """Creates the source tarball, GPG signatures, and checksums using flit.

    Args:
        version: The version string for the release
        build_wheel: If True, also build and sign a wheel distribution
    """
    print("\n[Step 1/1] Creating source release artifacts with 'flit build'...")

    # Clean the dist directory before building.
    if os.path.exists("dist"):
        shutil.rmtree("dist")
    # Ensure no pre-built UI assets slip into the source package.
    ui_build_dir = os.path.join("burr", "tracking", "server", "build")
    if os.path.exists(ui_build_dir):
        print("Removing previously built UI artifacts...")
        shutil.rmtree(ui_build_dir)

    # Warn if git working tree is dirty/untracked
    try:
        dirty = (
            subprocess.check_output(["git", "status", "--porcelain"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
        if dirty:
            print(
                "⚠️  Detected untracked or modified files. flit may refuse to build; "
                "consider committing/stashing or verify FLIT_USE_VCS=0."
            )
            print("    Git status summary:")
            for line in dirty.splitlines():
                print(f"     {line}")
    except subprocess.CalledProcessError:
        pass

    # Use flit to create the source distribution.
    try:
        env = os.environ.copy()
        env["FLIT_USE_VCS"] = "0"
        subprocess.run(["flit", "build", "--format", "sdist"], check=True, env=env)
        print("✓ flit sdist created successfully.")
    except subprocess.CalledProcessError as e:
        _fail(f"Error creating source distribution: {e}")

    # Find the created tarball in the dist directory.
    # Note: flit normalizes hyphens to underscores in filenames
    expected_tar_ball = f"dist/apache_burr-{version.lower()}.tar.gz"
    tarball_path = glob.glob(expected_tar_ball)

    if not tarball_path:
        details = []
        if os.path.exists("dist"):
            details.append("Contents of 'dist':")
            for item in os.listdir("dist"):
                details.append(f"- {item}")
        else:
            details.append("'dist' directory not found.")
        _fail(
            "Could not find the generated source tarball in the 'dist' directory.\n"
            + "\n".join(details)
        )

    # Rename the tarball to apache-burr-{version.lower()}-incubating.tar.gz
    apache_tar_ball = f"dist/apache-burr-{version.lower()}-incubating.tar.gz"
    shutil.move(tarball_path[0], apache_tar_ball)
    print(f"✓ Created source tarball: {apache_tar_ball}")

    # Sign the Apache tarball
    signed_files = sign_artifacts(apache_tar_ball)
    all_files = [apache_tar_ball] + signed_files

    # Optionally build the wheel (without built UI artifacts)
    if build_wheel:
        print("\n[Step 2/2] Creating wheel distribution with 'flit build --format wheel'...")
        try:
            env = os.environ.copy()
            env["FLIT_USE_VCS"] = "0"
            subprocess.run(["flit", "build", "--format", "wheel"], check=True, env=env)
            print("✓ flit wheel created successfully.")
        except subprocess.CalledProcessError as e:
            _fail(f"Error creating wheel distribution: {e}")

        # Find the created wheel in the dist directory.
        # Note: flit normalizes hyphens to underscores in filenames
        expected_wheel = f"dist/apache_burr-{version.lower()}-*.whl"
        wheel_path = glob.glob(expected_wheel)

        if not wheel_path:
            details = []
            if os.path.exists("dist"):
                details.append("Contents of 'dist':")
                for item in os.listdir("dist"):
                    details.append(f"- {item}")
            else:
                details.append("'dist' directory not found.")
            _fail(
                "Could not find the generated wheel in the 'dist' directory.\n" + "\n".join(details)
            )

        # Rename the wheel to apache-burr-{version.lower()}-incubating-{rest}.whl
        # Extract the wheel tags (e.g., py3-none-any.whl)
        original_wheel = os.path.basename(wheel_path[0])
        # Pattern: apache_burr-{version}-{tags}.whl -> apache-burr-{version}-incubating-{tags}.whl
        wheel_tags = original_wheel.replace(f"apache_burr-{version.lower()}-", "")
        apache_wheel = f"dist/apache-burr-{version.lower()}-incubating-{wheel_tags}"
        shutil.move(wheel_path[0], apache_wheel)
        print(f"✓ Created wheel: {apache_wheel}")

        # Sign the Apache wheel
        wheel_signed_files = sign_artifacts(apache_wheel)
        all_files.extend([apache_wheel] + wheel_signed_files)

    return all_files


def svn_upload(version, rc_num, archive_files, apache_id):
    """Uploads the artifacts to the ASF dev distribution repository."""
    print("Uploading artifacts to ASF SVN...")
    svn_path = f"https://dist.apache.org/repos/dist/dev/incubator/{PROJECT_SHORT_NAME}/apache-burr/{version}-incubating-RC{rc_num}"

    try:
        # Create a new directory for the release candidate.
        subprocess.run(
            [
                "svn",
                "mkdir",
                "-m",
                f"Creating directory for {version}-incubating-RC{rc_num}",
                svn_path,
            ],
            check=True,
        )

        # Get the files to import (tarball, asc, sha512).
        files_to_import = archive_files

        # Use svn import for the new directory.
        for file_path in files_to_import:
            subprocess.run(
                [
                    "svn",
                    "import",
                    file_path,
                    f"{svn_path}/{os.path.basename(file_path)}",
                    "-m",
                    f"Adding {os.path.basename(file_path)}",
                    "--username",
                    apache_id,
                ],
                check=True,
            )

        print(f"Artifacts successfully uploaded to: {svn_path}")
        return svn_path

    except subprocess.CalledProcessError as e:
        print(f"Error during SVN upload: {e}")
        print("Make sure you have svn access configured for your Apache ID.")
        return None


def generate_email_template(version, rc_num, svn_url):
    """Generates the content for the [VOTE] email."""
    print("Generating email template...")
    version_with_incubating = f"{version}-incubating"
    tag = f"v{version}"

    email_content = f"""[VOTE] Release Apache {PROJECT_SHORT_NAME} {version_with_incubating} (release candidate {rc_num})

Hi all,

This is a call for a vote on releasing Apache {PROJECT_SHORT_NAME} {version_with_incubating},
release candidate {rc_num}.

This release includes the following changes (see CHANGELOG for details):
- [List key changes here]

The artifacts for this release candidate can be found at:
{svn_url}

The Git tag to be voted upon is:
{tag}

The release hash is:
[Insert git commit hash here]


Release artifacts are signed with the following key:
[Insert your GPG key ID here]
The KEYS file is available at:
https://downloads.apache.org/incubator/{PROJECT_SHORT_NAME}/KEYS

Please download, verify, and test the release candidate.

For testing, please run some of the examples, scripts/qualify.sh has
a sampling of them to run.

The vote will run for a minimum of 72 hours.
Please vote:

[ ] +1 Release this package as Apache {PROJECT_SHORT_NAME} {version_with_incubating}
[ ] +0 No opinion
[ ] -1 Do not release this package because... (Please provide a reason)

Checklist for reference:
[ ] Download links are valid.
[ ] Checksums and signatures.
[ ] LICENSE/NOTICE files exist
[ ] LICENSE/NOTICE files exist in convenience packages
[ ] No unexpected binary files in source
[ ] No unexpected binary files in convenience packages
[ ] All source files have ASF headers
[ ] Can compile from source
[ ] Build script recreates convenience packages (contents need to match)

On behalf of the Apache {PROJECT_SHORT_NAME} PPMC,
[Your Name]
"""
    print("\n" + "=" * 80)
    print("EMAIL TEMPLATE (COPY AND PASTE TO YOUR MAILING LIST)")
    print("=" * 80)
    print(email_content)
    print("=" * 80)


def main():
    """
    ### How to Use the Updated Script

    1.  **Install flit**:
        ```bash
        pip install flit
        ```
    2.  **Configure the Script**: Open `apache_release_helper.py` in a text editor and update the three variables at the top of the file with your project's details:
        * `PROJECT_SHORT_NAME`
        * `VERSION_FILE` and `VERSION_PATTERN`
    3.  **Prerequisites**:
        * You must have `git`, `gpg`, `svn`, and `flit` installed.
        * Your GPG key and SVN access must be configured for your Apache ID.
    4.  **Run the Script**:
        Open your terminal, navigate to the root of your project directory, and run the script with the desired version, release candidate number, and Apache ID.


    python apache_release_helper.py 1.2.3 0 your_apache_id
    """
    parser = argparse.ArgumentParser(description="Automates parts of the Apache release process.")
    parser.add_argument("version", help="The new release version (e.g., '1.0.0').")
    parser.add_argument("rc_num", help="The release candidate number (e.g., '0' for RC0).")
    parser.add_argument("apache_id", help="Your apache user ID.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (skip git tag creation and SVN upload)",
    )
    parser.add_argument(
        "--build-wheel",
        action="store_true",
        help="Also build and sign a wheel distribution (in addition to the source tarball)",
    )
    args = parser.parse_args()

    version = args.version
    rc_num = args.rc_num
    apache_id = args.apache_id
    dry_run = args.dry_run
    build_wheel = args.build_wheel

    if dry_run:
        print("\n*** DRY RUN MODE - No git tags or SVN uploads will be performed ***\n")

    check_prerequisites()

    current_version = get_version_from_file(VERSION_FILE)
    print(current_version)
    if current_version != version:
        _fail(
            "Version mismatch. Update pyproject.toml to the requested version before running the script."
        )

    tag_name = f"v{version}-incubating-RC{rc_num}"
    if dry_run:
        print(f"\n[DRY RUN] Would create git tag '{tag_name}'")
    else:
        print(f"\nChecking for git tag '{tag_name}'...")
        try:
            # Check if the tag already exists
            existing_tag = subprocess.check_output(["git", "tag", "-l", tag_name]).decode().strip()
            if existing_tag == tag_name:
                print(f"Git tag '{tag_name}' already exists.")
                response = (
                    input("Do you want to continue without creating a new tag? (y/n): ")
                    .lower()
                    .strip()
                )
                if response != "y":
                    print("Aborting.")
                    sys.exit(1)
            else:
                # Tag does not exist, create it
                print(f"Creating git tag '{tag_name}'...")
                subprocess.run(["git", "tag", tag_name], check=True)
                print(f"Git tag {tag_name} created.")
        except subprocess.CalledProcessError as e:
            _fail(f"Error checking or creating Git tag: {e}")

    # Create artifacts
    archive_files = create_release_artifacts(version, build_wheel=build_wheel)

    # Upload artifacts
    # NOTE: You MUST have your SVN client configured to use your Apache ID and have permissions.
    if dry_run:
        svn_url = f"https://dist.apache.org/repos/dist/dev/incubator/{PROJECT_SHORT_NAME}/apache-burr/{version}-incubating-RC{rc_num}"
        print(f"\n[DRY RUN] Would upload artifacts to: {svn_url}")
    else:
        svn_url = svn_upload(version, rc_num, archive_files, apache_id)
        if not svn_url:
            _fail("SVN upload failed.")

    # Generate email
    generate_email_template(version, rc_num, svn_url)

    print("\nProcess complete. Please copy the email template to your mailing list.")


if __name__ == "__main__":
    main()
