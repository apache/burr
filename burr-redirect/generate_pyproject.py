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
Generate burr-redirect/pyproject.toml from the template and the root pyproject.

The redirect package (PyPI name ``burr``) exists only to point users at
``apache-burr``. Every extra that ``apache-burr`` declares must also exist on
the redirect package, otherwise ``pip install burr[langfuse]`` warns about an
unknown extra and silently installs nothing. Hand-mirroring the extras drifted
in the past, so the ``[project.optional-dependencies]`` section is generated
here from the extras declared in the repository root ``pyproject.toml``.

Usage:
    python generate_pyproject.py <version>
    python generate_pyproject.py 0.42.0
"""

import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib

PLACEHOLDER = "#OPTIONAL_DEPENDENCIES#"

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ROOT_PYPROJECT = REPO_ROOT / "pyproject.toml"
TEMPLATE = SCRIPT_DIR / "pyproject.toml.template"
OUTPUT = SCRIPT_DIR / "pyproject.toml"


def fail(message: str) -> None:
    """Print an error and exit nonzero."""
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def load_toml(path: Path) -> dict:
    """Parse a TOML file, failing with a clear message if it is unreadable."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        fail(f"{path} not found")
    except tomllib.TOMLDecodeError as e:
        fail(f"{path} is not valid TOML: {e}")


def read_root_extras() -> list:
    """Return the alphabetically sorted extra names declared by apache-burr."""
    extras = load_toml(ROOT_PYPROJECT).get("project", {}).get("optional-dependencies")
    if not extras:
        fail(f"no [project.optional-dependencies] found in {ROOT_PYPROJECT}")
    return sorted(extras)


def render_extras(extras: list, version: str) -> str:
    """Render the [project.optional-dependencies] section for the redirect package."""
    lines = ["[project.optional-dependencies]"]
    lines += [f'{name} = ["apache-burr[{name}]=={version}"]' for name in extras]
    return "\n".join(lines)


def render_template(extras: list, version: str) -> str:
    """Substitute the extras section and the version into the template text."""
    template = TEMPLATE.read_text()
    matches = [line for line in template.splitlines() if PLACEHOLDER in line]
    if not matches:
        fail(
            f"placeholder {PLACEHOLDER} not found in {TEMPLATE}. "
            "The template must contain that line so the generated "
            "[project.optional-dependencies] section has somewhere to go."
        )
    rendered = "\n".join(
        render_extras(extras, version) if PLACEHOLDER in line else line
        for line in template.splitlines()
    )
    if not rendered.endswith("\n"):
        rendered += "\n"
    return rendered.replace("VERSION", version)


def verify(extras: list, version: str) -> None:
    """Re-parse the written file and assert it says exactly what we intended."""
    project = load_toml(OUTPUT).get("project", {})

    written_extras = project.get("optional-dependencies", {})
    if sorted(written_extras) != extras:
        missing = sorted(set(extras) - set(written_extras))
        unexpected = sorted(set(written_extras) - set(extras))
        fail(
            f"{OUTPUT} extras do not match {ROOT_PYPROJECT}: "
            f"missing={missing} unexpected={unexpected}"
        )

    for name in extras:
        expected = [f"apache-burr[{name}]=={version}"]
        if written_extras[name] != expected:
            fail(f"{OUTPUT} extra {name!r} is {written_extras[name]!r}, expected {expected!r}")

    expected_deps = [f"apache-burr=={version}"]
    if project.get("dependencies") != expected_deps:
        fail(
            f"{OUTPUT} dependencies are {project.get('dependencies')!r}, expected {expected_deps!r}"
        )

    if project.get("version") != version:
        fail(f"{OUTPUT} version is {project.get('version')!r}, expected {version!r}")


def main(argv: list) -> None:
    if len(argv) != 2:
        print(f"Usage: {Path(argv[0]).name} <version>", file=sys.stderr)
        print(f"Example: {Path(argv[0]).name} 0.42.0", file=sys.stderr)
        sys.exit(1)

    version = argv[1]
    extras = read_root_extras()
    OUTPUT.write_text(render_template(extras, version))
    verify(extras, version)
    print(f"Wrote {OUTPUT} for version {version} with {len(extras)} extras.")


if __name__ == "__main__":
    main(sys.argv)
