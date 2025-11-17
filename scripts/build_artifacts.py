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


def _build_wheel() -> bool:
    print("Building wheel distribution with 'flit build --format wheel'...")
    try:
        env = os.environ.copy()
        env["FLIT_USE_VCS"] = "0"
        subprocess.run(["flit", "build", "--format", "wheel"], check=True, env=env)
        print("✓ Wheel build completed successfully.\n")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"✗ Error building wheel: {exc}")
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
