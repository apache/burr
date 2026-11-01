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
Tests to validate release configuration in pyproject.toml.

This ensures the examples include/exclude lists stay in sync with the actual
examples directory structure.
"""

import sys
from pathlib import Path

import pytest

# tomllib is only available in Python 3.11+
if sys.version_info >= (3, 11):
    import tomllib
else:
    tomllib = None


def test_sdist_license_only_covers_files_shipped_in_sdist():
    project_root = Path(__file__).parent.parent
    source_license = (project_root / "LICENSE").read_text(encoding="utf-8")
    sdist_license = (project_root / "LICENSE-sdist").read_text(encoding="utf-8")

    assert "examples/deep-researcher" in sdist_license
    assert "website/" not in sdist_license
    assert "Magic UI" not in sdist_license
    assert "shadcn" not in sdist_license

    # The full source archive still ships the website, so its LICENSE must
    # retain the corresponding third-party license entries.
    assert "website/" in source_license
    assert "Magic UI" in source_license
    assert "shadcn" in source_license


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
def test_examples_include_exclude_coverage():
    """
    Verify that pyproject.toml's [tool.flit.sdist] include/exclude lists cover
    all example directories.

    WHY THIS TEST EXISTS:
    Flit automatically includes the examples/ directory in the release tarball because
    it's a Python package (has __init__.py). Without explicit include/exclude rules,
    ALL examples would be shipped in the Apache release, which is not intended.

    For Apache releases, we only want to include 5 specific examples for voters to test:
    - email-assistant
    - multi-modal-chatbot
    - streaming-fastapi
    - deep-researcher
    - hello-world-counter

    All other examples must be explicitly excluded. This test ensures the configuration
    stays in sync with the filesystem when examples are added/removed.

    If this test fails, you need to update pyproject.toml:
    - To INCLUDE an example: add it to [tool.flit.sdist] include list
    - To EXCLUDE an example: add it to [tool.flit.sdist] exclude list
    """
    # Load pyproject.toml
    project_root = Path(__file__).parent.parent
    pyproject_path = project_root / "pyproject.toml"

    with open(pyproject_path, "rb") as f:
        config = tomllib.load(f)

    flit_sdist = config.get("tool", {}).get("flit", {}).get("sdist", {})
    include_patterns = flit_sdist.get("include", [])
    exclude_patterns = flit_sdist.get("exclude", [])

    # Extract example directories and files from include patterns
    included_examples = set()
    included_files = set()
    for pattern in include_patterns:
        if pattern.startswith("examples/"):
            if pattern.endswith("/**"):
                # Extract directory name from patterns like "examples/email-assistant/**"
                dir_name = pattern.removeprefix("examples/").removesuffix("/**")
                included_examples.add(dir_name)
            else:
                # File pattern like "examples/__init__.py"
                included_files.add(pattern.removeprefix("examples/"))

    # Extract example directories from exclude patterns
    excluded_examples = set()
    excluded_files = set()
    for pattern in exclude_patterns:
        if pattern.startswith("examples/"):
            if pattern.endswith("/**"):
                # Directory pattern like "examples/adaptive-crag/**"
                dir_name = pattern.removeprefix("examples/").removesuffix("/**")
                excluded_examples.add(dir_name)
            else:
                # File pattern like "examples/__init__.py"
                file_name = pattern.removeprefix("examples/")
                excluded_files.add(file_name)

    # Get actual example directories from filesystem
    examples_dir = project_root / "examples"
    actual_dirs = set()
    actual_files = set()

    if examples_dir.exists():
        for item in examples_dir.iterdir():
            if item.name.startswith(".") or item.name == "__pycache__":
                continue
            if item.is_dir():
                actual_dirs.add(item.name)
            else:
                actual_files.add(item.name)

    # Check coverage
    configured_dirs = included_examples | excluded_examples
    missing_from_config = actual_dirs - configured_dirs
    extra_in_config = configured_dirs - actual_dirs

    configured_files = included_files | excluded_files
    files_missing_from_config = actual_files - configured_files
    extra_files_in_config = configured_files - actual_files

    # Build error message if mismatch found
    errors = []

    if missing_from_config:
        errors.append(
            f"\n❌ Example directories exist but are NOT in pyproject.toml config:\n"
            f"   {sorted(missing_from_config)}\n"
            f"\n   WHY THIS MATTERS:\n"
            f"   Flit auto-discovers examples/ as a package (it has __init__.py) and will\n"
            f"   include ALL subdirectories in the release tarball unless explicitly excluded.\n"
            f"   Every example directory MUST be either included or excluded to ensure the\n"
            f"   Apache release contains only the intended examples for voters to test.\n"
            f"\n   To fix: Add to pyproject.toml [tool.flit.sdist]:\n"
            f"   - To INCLUDE in Apache release: add 'examples/<name>/**' to 'include' list\n"
            f"   - To EXCLUDE from Apache release: add 'examples/<name>/**' to 'exclude' list\n"
            f"\n   Currently only these 5 examples should be included:\n"
            f"   email-assistant, multi-modal-chatbot, streaming-fastapi, deep-researcher, hello-world-counter\n"
        )

    if extra_in_config:
        errors.append(
            f"\n❌ Example directories in pyproject.toml but NOT in filesystem:\n"
            f"   {sorted(extra_in_config)}\n"
            f"\n   WHY THIS MATTERS:\n"
            f"   These entries reference examples that no longer exist and should be removed\n"
            f"   to keep the configuration accurate and maintainable.\n"
            f"\n   To fix: Remove these entries from pyproject.toml [tool.flit.sdist]\n"
        )

    if files_missing_from_config:
        errors.append(
            f"\n❌ Top-level files in examples/ that are NOT in pyproject.toml config:\n"
            f"   {sorted(files_missing_from_config)}\n"
            f"\n   WHY THIS MATTERS:\n"
            f"   Loose files directly under examples/ are picked up by flit's package\n"
            f"   auto-discovery just like the subdirectories, so they ship in the sdist as\n"
            f"   stray files unless explicitly excluded (this is how\n"
            f"   examples/fastapi_mount_example.py leaked into a release artifact).\n"
            f"\n   To fix: Add to pyproject.toml [tool.flit.sdist]:\n"
            f"   - To INCLUDE in Apache release: add 'examples/<name>' to 'include' list\n"
            f"   - To EXCLUDE from Apache release: add 'examples/<name>' to 'exclude' list\n"
        )

    if extra_files_in_config:
        errors.append(
            f"\n❌ Files listed in pyproject.toml but NOT in examples/ on disk:\n"
            f"   {sorted(extra_files_in_config)}\n"
            f"\n   To fix: Remove these entries from pyproject.toml [tool.flit.sdist]\n"
        )

    # Report what's currently configured (for debugging)
    if errors:
        summary = (
            f"\n📋 Current configuration:\n"
            f"   Included examples ({len(included_examples)}): {sorted(included_examples)}\n"
            f"   Excluded examples ({len(excluded_examples)}): {sorted(excluded_examples)}\n"
            f"   Included files ({len(included_files)}): {sorted(included_files)}\n"
            f"   Excluded files ({len(excluded_files)}): {sorted(excluded_files)}\n"
            f"   Actual directories ({len(actual_dirs)}): {sorted(actual_dirs)}\n"
            f"   Actual files ({len(actual_files)}): {sorted(actual_files)}\n"
        )
        errors.append(summary)

    assert not errors, "\n".join(errors)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
def test_non_source_trees_excluded_from_sdist():
    """
    Verify that top-level trees which are not "source used to build" are excluded from
    the sdist.

    WHY THIS TEST EXISTS:
    scripts/README.md defines the policy table for what belongs in each artifact. The
    docs/ and website/ trees are included in the git archive (tar.gz) for voters to
    review, but must NOT appear in the sdist or the wheel since they are not needed to
    build or use the package. website/ previously shipped in the sdist because it had no
    exclude entry.

    If this test fails, add the missing pattern to [tool.flit.sdist] exclude.
    """
    project_root = Path(__file__).parent.parent
    pyproject_path = project_root / "pyproject.toml"

    with open(pyproject_path, "rb") as f:
        config = tomllib.load(f)

    exclude_patterns = set(config["tool"]["flit"]["sdist"]["exclude"])

    # Trees that exist in the repo but must never be part of the sdist.
    non_source_trees = ["docs", "website", "burr-redirect"]

    missing = [
        f"{tree}/**"
        for tree in non_source_trees
        if (project_root / tree).is_dir() and f"{tree}/**" not in exclude_patterns
    ]

    assert not missing, (
        f"\n❌ Non-source trees missing from [tool.flit.sdist] exclude: {missing}\n"
        f"\n   These directories are not source needed to build or use the package (see\n"
        f"   the policy table in scripts/README.md) and would otherwise ship in the sdist.\n"
        f"\n   To fix: add the listed pattern(s) to pyproject.toml [tool.flit.sdist] exclude.\n"
    )
