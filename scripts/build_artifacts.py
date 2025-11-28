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
Build artifacts/wheels helper with subcommands:

    python scripts/build_artifacts.py artifacts [--skip-install]
    python scripts/build_artifacts.py wheel [--clean]
    python scripts/build_artifacts.py all [--skip-install] [--clean]

Subcommands:
    artifacts  -> Build UI artifacts only
    wheel      -> Build wheel (requires artifacts to exist)
    all        -> Run both steps (artifacts then wheel)
"""

import argparse
import os
import shutil
import subprocess
import sys


def _ensure_project_root() -> bool:
    if not os.path.exists("pyproject.toml"):
        print("Error: pyproject.toml not found.")
        print("Please run this script from the root of the Burr source directory.")
        return False
    return True


def _check_node_prereqs() -> bool:
    print("Checking for required tools...")
    required_tools = ["node", "npm"]
    missing_tools = []

    for tool in required_tools:
        if shutil.which(tool) is None:
            missing_tools.append(tool)
            print(f"  ✗ '{tool}' not found")
        else:
            print(f"  ✓ '{tool}' found")

    if missing_tools:
        print(f"\nError: Missing required tools: {', '.join(missing_tools)}")
        print("Please install Node.js and npm to build the UI.")
        return False

    print("All required tools found.\n")
    return True


def _require_flit() -> bool:
    if shutil.which("flit") is None:
        print("✗ flit CLI not found. Please install it with: pip install flit")
        return False
    print("✓ flit CLI found.\n")
    return True


def _install_burr(skip_install: bool) -> bool:
    if skip_install:
        print("Skipping burr installation as requested.\n")
        return True

    print("Installing burr from source...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", "."],
            check=True,
            cwd=os.getcwd(),
        )
        print("✓ Burr installed successfully.\n")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"✗ Error installing burr: {exc}")
        return False


def _build_ui() -> bool:
    print("Building UI assets...")
    try:
        env = os.environ.copy()
        env["BURR_PROJECT_ROOT"] = os.getcwd()
        subprocess.run(["burr-admin-build-ui"], check=True, env=env)
        print("✓ UI build completed successfully.\n")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"✗ Error building UI: {exc}")
        return False


def _verify_artifacts() -> bool:
    build_dir = "burr/tracking/server/build"
    print(f"Verifying build output in {build_dir}...")

    if not os.path.exists(build_dir):
        print(f"Build directory missing, creating placeholder at {build_dir}...")
        os.makedirs(build_dir, exist_ok=True)

    if not os.listdir(build_dir):
        print(f"✗ Build directory is empty: {build_dir}")
        return False

    print("✓ Build output verified.\n")
    return True


def _clean_dist():
    if os.path.exists("dist"):
        print("Cleaning dist/ directory...")
        shutil.rmtree("dist")
        print("✓ dist/ directory cleaned.\n")


def _clean_ui_build():
    """Remove any existing UI build directory to ensure clean state."""
    ui_build_dir = "burr/tracking/server/build"
    if os.path.exists(ui_build_dir):
        print(f"Cleaning existing UI build directory: {ui_build_dir}")
        shutil.rmtree(ui_build_dir)
        print("✓ UI build directory cleaned.\n")


def _replace_symlinks_with_copies():
    """
    Replace symlinked example files/directories with actual copies before building.
    Returns a dict mapping paths to their symlink targets (if they were symlinks),
    so they can be restored later.
    """
    # Files and directories from pyproject.toml lines 266-270 that might be symlinks
    example_paths = [
        "examples/__init__.py",
        "examples/email-assistant",
        "examples/multi-modal-chatbot",
        "examples/streaming-fastapi",
        "examples/deep-researcher",
    ]

    symlink_info = {}  # Maps path -> (was_symlink: bool, symlink_target: str or None, is_dir: bool)

    for path in example_paths:
        if not os.path.exists(path):
            continue

        if os.path.islink(path):
            # It's a symlink - we need to replace it with a copy
            # Store the original symlink target as read (may be relative)
            original_symlink_target = os.readlink(path)

            # Resolve relative symlink targets to absolute paths for copying
            if os.path.isabs(original_symlink_target):
                resolved_target = original_symlink_target
            else:
                # Resolve relative to the directory containing the symlink
                symlink_dir = os.path.dirname(os.path.abspath(path))
                resolved_target = os.path.join(symlink_dir, original_symlink_target)
                resolved_target = os.path.normpath(resolved_target)

            print(f"Found symlink: {path} -> {original_symlink_target}")
            print("  Replacing with copy...")

            # Verify the symlink target exists
            if not os.path.exists(resolved_target):
                print(f"  ✗ Warning: Symlink target does not exist: {resolved_target}")
                symlink_info[path] = (False, None, False)
                continue

            is_directory = os.path.isdir(resolved_target)

            # Remove the symlink
            os.remove(path)

            if is_directory:
                # For directories, use copytree
                shutil.copytree(resolved_target, path, dirs_exist_ok=True)
            else:
                # For files, use copy2 to preserve metadata
                shutil.copy2(resolved_target, path)

            # Store the original symlink target (as it was originally read)
            symlink_info[path] = (True, original_symlink_target, is_directory)
            print("  ✓ Replaced symlink with copy.\n")
        else:
            # Not a symlink, nothing to do
            symlink_info[path] = (False, None, False)

    return symlink_info


def _restore_symlinks(symlink_info):
    """
    Restore symlinks that were replaced with copies.
    symlink_info: dict from _replace_symlinks_with_copies()
    """
    for path, (was_symlink, symlink_target, is_directory) in symlink_info.items():
        if was_symlink and symlink_target:
            if os.path.exists(path) and not os.path.islink(path):
                # Remove the copy and restore the symlink
                print(f"Restoring symlink: {path} -> {symlink_target}")
                try:
                    if is_directory:
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    os.symlink(symlink_target, path)
                    print("  ✓ Symlink restored.\n")
                except Exception as exc:
                    print(f"  ✗ Error restoring symlink: {exc}\n")


def _copy_examples_to_burr():
    """
    Copy example directories into burr/examples/ so they're included in the wheel.
    Flit wheels only package what's in the burr/ module directory.
    If burr/examples exists (as symlink or directory), remove it first to ensure
    we copy actual files, not symlinks.
    Returns tuple: (copied: bool, was_symlink: bool, symlink_target: str or None)
    """
    burr_examples_dir = "burr/examples"
    source_examples_dir = "examples"

    if not os.path.exists(source_examples_dir):
        print(f"Warning: {source_examples_dir} does not exist. Skipping copy.\n")
        return (False, False, None)

    # Check if burr/examples exists and if it's a symlink - we'll need to restore it later
    was_symlink = False
    symlink_target = None
    if os.path.exists(burr_examples_dir):
        if os.path.islink(burr_examples_dir):
            was_symlink = True
            symlink_target = os.readlink(burr_examples_dir)
            print(f"Removing existing {burr_examples_dir} symlink (-> {symlink_target})...")
            os.remove(burr_examples_dir)
        else:
            print(f"Removing existing {burr_examples_dir} directory...")
            shutil.rmtree(burr_examples_dir)
        print(f"  ✓ Removed existing {burr_examples_dir}\n")

    print(
        f"Copying examples from {source_examples_dir} to {burr_examples_dir} for wheel packaging..."
    )

    # Create burr/examples directory
    os.makedirs(burr_examples_dir, exist_ok=True)

    # Copy __init__.py if it exists
    init_file = os.path.join(source_examples_dir, "__init__.py")
    if os.path.exists(init_file):
        shutil.copy2(init_file, os.path.join(burr_examples_dir, "__init__.py"))

    # Copy the specific example directories from pyproject.toml
    example_dirs = [
        "email-assistant",
        "multi-modal-chatbot",
        "streaming-fastapi",
        "deep-researcher",
    ]

    for example_dir in example_dirs:
        source_path = os.path.join(source_examples_dir, example_dir)
        dest_path = os.path.join(burr_examples_dir, example_dir)

        if os.path.exists(source_path):
            if os.path.isdir(source_path):
                shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
            else:
                shutil.copy2(source_path, dest_path)
            print(f"  ✓ Copied {example_dir}")

    print(f"✓ Examples copied to {burr_examples_dir}.\n")
    return (True, was_symlink, symlink_target)


def _remove_examples_from_burr(was_symlink=False, symlink_target=None):
    """
    Remove the examples directory from burr/ after building the wheel.
    If it was originally a symlink, restore it.
    """
    burr_examples_dir = "burr/examples"
    if os.path.exists(burr_examples_dir):
        print(f"Removing {burr_examples_dir} after wheel build...")
        shutil.rmtree(burr_examples_dir)
        print(f"  ✓ Removed {burr_examples_dir}.\n")

        # Restore the original symlink if it existed
        if was_symlink and symlink_target:
            print(f"Restoring symlink: {burr_examples_dir} -> {symlink_target}")
            try:
                os.symlink(symlink_target, burr_examples_dir)
                print("  ✓ Symlink restored.\n")
            except Exception as exc:
                print(f"  ✗ Error restoring symlink: {exc}\n")


def _build_wheel() -> bool:
    print("Building wheel distribution with 'flit build --format wheel'...")

    # Replace symlinked directories with copies before building
    symlink_info = _replace_symlinks_with_copies()

    # Copy examples into burr/ so they're included in the wheel
    examples_copied, examples_was_symlink, examples_symlink_target = _copy_examples_to_burr()

    try:
        env = os.environ.copy()
        env["FLIT_USE_VCS"] = "0"
        subprocess.run(["flit", "build", "--format", "wheel"], check=True, env=env)
        print("✓ Wheel build completed successfully.\n")

        # Remove examples from burr/ after successful build (and restore symlink if needed)
        if examples_copied:
            _remove_examples_from_burr(examples_was_symlink, examples_symlink_target)

        # Restore symlinks after successful build
        _restore_symlinks(symlink_info)
        return True
    except subprocess.CalledProcessError as exc:
        print(f"✗ Error building wheel: {exc}")
        # Remove examples from burr/ even on error (and restore symlink if needed)
        if examples_copied:
            _remove_examples_from_burr(examples_was_symlink, examples_symlink_target)
        # Restore symlinks even on error
        _restore_symlinks(symlink_info)
        return False
    except Exception as exc:
        # Remove examples from burr/ on any other error (and restore symlink if needed)
        if examples_copied:
            _remove_examples_from_burr(examples_was_symlink, examples_symlink_target)
        # Restore symlinks on any other error
        print(f"✗ Unexpected error building wheel: {exc}")
        _restore_symlinks(symlink_info)
        return False


def _verify_wheel() -> bool:
    print("Verifying wheel output...")

    if not os.path.exists("dist"):
        print("✗ dist/ directory not found")
        return False

    wheel_files = [f for f in os.listdir("dist") if f.endswith(".whl")]
    if not wheel_files:
        print("✗ No wheel files found in dist/")
        if os.listdir("dist"):
            print("Contents of dist/ directory:")
            for item in os.listdir("dist"):
                print(f"  - {item}")
        return False

    print(f"✓ Found {len(wheel_files)} wheel file(s):")
    for wheel_file in wheel_files:
        wheel_path = os.path.join("dist", wheel_file)
        size = os.path.getsize(wheel_path)
        print(f"  - {wheel_file} ({size:,} bytes)")

    print()
    return True


def create_artifacts(skip_install: bool) -> bool:
    if not _ensure_project_root():
        print("Failed to confirm project root.")
        return False
    if not _check_node_prereqs():
        print("Node/npm prerequisite check failed.")
        return False
    # Clean any existing UI build to ensure fresh state
    _clean_ui_build()
    if not _install_burr(skip_install):
        print("Installing burr from source failed.")
        return False
    if not _build_ui():
        print("UI build failed.")
        return False
    if not _verify_artifacts():
        print("UI artifact verification failed.")
        return False
    return True


def create_wheel(clean: bool) -> bool:
    if not _ensure_project_root():
        print("Failed to confirm project root.")
        return False
    if not _require_flit():
        print("Missing flit CLI.")
        return False
    if not _verify_artifacts():
        print("Please run the 'artifacts' subcommand first.")
        return False
    if clean:
        _clean_dist()
    if not _build_wheel():
        return False
    if not _verify_wheel():
        return False
    return True


def build_all(skip_install: bool, clean: bool) -> bool:
    if not create_artifacts(skip_install=skip_install):
        return False
    if not create_wheel(clean=clean):
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Build artifacts/wheels for Burr using subcommands."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    artifacts_parser = subparsers.add_parser("artifacts", help="Build UI artifacts only.")
    artifacts_parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip reinstalling burr when building artifacts",
    )

    wheel_parser = subparsers.add_parser(
        "wheel", help="Build wheel distribution (requires artifacts)."
    )
    wheel_parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean dist/ directory before building wheel",
    )

    all_parser = subparsers.add_parser("all", help="Build artifacts and wheel in sequence.")
    all_parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip reinstalling burr when building artifacts",
    )
    all_parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean dist/ directory before building wheel",
    )

    args = parser.parse_args()

    print("=" * 80)
    print(f"Burr Build Helper - command: {args.command}")
    print("=" * 80)
    print()

    success = False
    if args.command == "artifacts":
        success = create_artifacts(skip_install=args.skip_install)
    elif args.command == "wheel":
        success = create_wheel(clean=args.clean)
    elif args.command == "all":
        success = build_all(skip_install=args.skip_install, clean=args.clean)

    if success:
        print("=" * 80)
        print("✅ Build Complete!")
        print("=" * 80)
        if args.command in {"wheel", "all"}:
            print("\nWheel files are in the dist/ directory.")
            print("You can now upload to PyPI with:")
            print("  twine upload dist/*.whl")
        print()
    else:
        print("\n❌ Build failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
