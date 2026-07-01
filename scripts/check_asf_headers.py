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
Check that Python, YAML, and shell files carry the ASF license header.

Called by pre-commit with the list of staged files. Reads .rat-excludes at
runtime so known third-party files are automatically respected without any
duplication of the exclusion list.

Usage (pre-commit invokes this automatically):
    python scripts/check_asf_headers.py file1.py file2.yml ...
"""

import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional

# Extensions whose source files must carry an ASF header.
CHECKED_EXTENSIONS = {".py", ".yml", ".yaml", ".sh"}

# Only search this many lines from the top of each file.
# Headers are always at the start; searching the whole file would be slow
# and would risk false positives from files that quote the license in prose.
HEADER_SEARCH_LINES = 30

# The one string that appears in every valid ASF license header regardless
# of comment style (# for Python/YAML/shell, // for Java, /* for C, etc.).
ASF_HEADER_MARKER = "Licensed to the Apache Software Foundation (ASF)"


def _find_repo_root(start: Path) -> Path:
    """Walk upward from start until we find .rat-excludes or pyproject.toml."""
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / ".rat-excludes").exists() or (candidate / "pyproject.toml").exists():
            return candidate
    return start.resolve()


def _load_rat_exclude_patterns(repo_root: Path) -> list:
    """Return non-comment, non-blank lines from .rat-excludes as glob patterns."""
    path = repo_root / ".rat-excludes"
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _is_excluded(file_path: Path, repo_root: Path, patterns: list) -> bool:
    """Return True if file_path matches any pattern from .rat-excludes.

    Patterns use RAT's **/<name> syntax. We handle this by checking the
    file's basename against patterns that start with **/, and also checking
    the full relative path against each pattern directly.
    """
    try:
        rel = str(file_path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        rel = str(file_path)
    name = file_path.name
    for pattern in patterns:
        if pattern.startswith("**/"):
            # Strip the **/ prefix and match against the bare filename.
            if fnmatch(name, pattern[3:]):
                return True
        if fnmatch(rel, pattern):
            return True
    return False


def _has_asf_header(file_path: Path) -> bool:
    """Return True if the ASF header marker appears within the first HEADER_SEARCH_LINES."""
    try:
        with file_path.open(encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= HEADER_SEARCH_LINES:
                    break
                if ASF_HEADER_MARKER in line:
                    return True
    except OSError:
        pass
    return False


def main(argv: Optional[list] = None) -> int:
    files = [Path(p) for p in (argv if argv is not None else sys.argv[1:])]
    if not files:
        return 0

    repo_root = _find_repo_root(files[0].parent)
    patterns = _load_rat_exclude_patterns(repo_root)

    violations = []
    for f in files:
        if f.suffix not in CHECKED_EXTENSIONS:
            continue
        if _is_excluded(f, repo_root, patterns):
            continue
        if not _has_asf_header(f):
            violations.append(f)

    if violations:
        print("Missing ASF license header in the following file(s):")
        for v in violations:
            print(f"  {v}")
        print()
        print("Add the standard Apache 2.0 header block to each file.")
        print("See any existing .py file in scripts/ for the correct format.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
