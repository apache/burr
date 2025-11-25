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


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
def test_examples_include_exclude_coverage():
    """
    Verify that pyproject.toml's [tool.flit.sdist] include/exclude lists cover
    all example directories.

    WHY THIS TEST EXISTS:
    Flit automatically includes the examples/ directory in the release tarball because
    it's a Python package (has __init__.py). Without explicit include/exclude rules,
    ALL examples would be shipped in the Apache release, which is not intended.

    For Apache releases, we only want to include 4 specific examples for voters to test:
    - email-assistant
    - multi-modal-chatbot
    - streaming-fastapi
    - deep-researcher

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

    # Extract example directories from include patterns
    included_examples = set()
    for pattern in include_patterns:
        if pattern.startswith("examples/") and pattern.endswith("/**"):
            # Extract directory name from patterns like "examples/email-assistant/**"
            dir_name = pattern.removeprefix("examples/").removesuffix("/**")
            included_examples.add(dir_name)

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
            f"\n   Currently only these 4 examples should be included:\n"
            f"   email-assistant, multi-modal-chatbot, streaming-fastapi, deep-researcher\n"
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

    # Report what's currently configured (for debugging)
    if errors:
        summary = (
            f"\n📋 Current configuration:\n"
            f"   Included examples ({len(included_examples)}): {sorted(included_examples)}\n"
            f"   Excluded examples ({len(excluded_examples)}): {sorted(excluded_examples)}\n"
            f"   Excluded files ({len(excluded_files)}): {sorted(excluded_files)}\n"
            f"   Actual directories ({len(actual_dirs)}): {sorted(actual_dirs)}\n"
        )
        errors.append(summary)

    assert not errors, "\n".join(errors)
