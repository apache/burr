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

import importlib.util
import sys
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parent.parent / "scripts" / "check_asf_headers.py"
    spec = importlib.util.spec_from_file_location("check_asf_headers", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


chk = _load_module()

ASF_HEADER = "# Licensed to the Apache Software Foundation (ASF) under one\n"


# ---------------------------------------------------------------------------
# _has_asf_header
# ---------------------------------------------------------------------------


def test_has_asf_header_returns_true_when_marker_present(tmp_path):
    """A file whose first line contains the ASF marker is accepted."""
    f = tmp_path / "good.py"
    f.write_text(ASF_HEADER + "print('hello')\n")
    assert chk._has_asf_header(f) is True


def test_has_asf_header_returns_false_when_marker_absent(tmp_path):
    """A file with no mention of the ASF is rejected."""
    f = tmp_path / "bad.py"
    f.write_text("print('hello')\n")
    assert chk._has_asf_header(f) is False


def test_has_asf_header_only_searches_first_n_lines(tmp_path):
    """The marker appearing after HEADER_SEARCH_LINES is not found."""
    padding = "# padding\n" * chk.HEADER_SEARCH_LINES
    f = tmp_path / "late.py"
    f.write_text(padding + ASF_HEADER)
    assert chk._has_asf_header(f) is False


def test_has_asf_header_accepts_marker_anywhere_within_search_window(tmp_path):
    """A shebang line before the header is fine — still within search window."""
    f = tmp_path / "script.sh"
    f.write_text("#!/usr/bin/env bash\n" + ASF_HEADER)
    assert chk._has_asf_header(f) is True


# ---------------------------------------------------------------------------
# _load_rat_exclude_patterns
# ---------------------------------------------------------------------------


def test_load_rat_exclude_patterns_strips_comments_and_blanks(tmp_path):
    """Comments (#) and blank lines are stripped; only glob patterns remain."""
    rat = tmp_path / ".rat-excludes"
    rat.write_text(
        "# This is a comment\n"
        "\n"
        "**/prompts.py\n"
        "  # indented comment\n"
        "**/deep_researcher_utils.py\n"
    )
    patterns = chk._load_rat_exclude_patterns(tmp_path)
    assert patterns == ["**/prompts.py", "**/deep_researcher_utils.py"]


def test_load_rat_exclude_patterns_returns_empty_when_file_missing(tmp_path):
    """Returns an empty list when .rat-excludes does not exist."""
    assert chk._load_rat_exclude_patterns(tmp_path) == []


# ---------------------------------------------------------------------------
# _is_excluded
# ---------------------------------------------------------------------------


def test_is_excluded_matches_basename_glob(tmp_path):
    """A file matching **/name.py is excluded regardless of directory depth."""
    f = tmp_path / "examples" / "deep-researcher" / "prompts.py"
    f.parent.mkdir(parents=True)
    f.touch()
    assert chk._is_excluded(f, tmp_path, ["**/prompts.py"]) is True


def test_is_excluded_returns_false_for_non_matching_file(tmp_path):
    """An ordinary source file that matches no pattern is not excluded."""
    f = tmp_path / "burr" / "core.py"
    f.parent.mkdir(parents=True)
    f.touch()
    assert chk._is_excluded(f, tmp_path, ["**/prompts.py"]) is False


def test_is_excluded_matches_extension_glob(tmp_path):
    """A **/*.json pattern excludes all JSON files."""
    f = tmp_path / "some" / "config.json"
    f.parent.mkdir(parents=True)
    f.touch()
    assert chk._is_excluded(f, tmp_path, ["**/*.json"]) is True


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_returns_0_with_no_files():
    """Invoked with no arguments, main returns 0 (nothing to check)."""
    assert chk.main([]) == 0


def test_main_returns_0_when_all_files_have_headers(tmp_path):
    """Clean files: exits 0."""
    f = tmp_path / "good.py"
    f.write_text(ASF_HEADER + "x = 1\n")
    assert chk.main([str(f)]) == 0


def test_main_returns_1_when_file_is_missing_header(tmp_path):
    """A staged Python file without the header causes exit 1."""
    f = tmp_path / "bad.py"
    f.write_text("x = 1\n")
    assert chk.main([str(f)]) == 1


def test_main_skips_unchecked_extensions(tmp_path):
    """File types that don't need headers (e.g. .json) are silently skipped."""
    f = tmp_path / "config.json"
    f.write_text("{}\n")
    assert chk.main([str(f)]) == 0


def test_main_skips_rat_excluded_files(tmp_path):
    """A file that matches a .rat-excludes pattern is not checked."""
    # Write a .rat-excludes that excludes prompts.py
    (tmp_path / ".rat-excludes").write_text("**/prompts.py\n")
    # Write a prompts.py with no header — would normally fail
    f = tmp_path / "examples" / "prompts.py"
    f.parent.mkdir()
    f.write_text("SYSTEM_PROMPT = 'hello'\n")
    assert chk.main([str(f)]) == 0


def test_main_reports_all_violations(tmp_path, capsys):
    """When multiple files are missing headers, all are reported."""
    a = tmp_path / "a.py"
    b = tmp_path / "b.yml"
    a.write_text("x = 1\n")
    b.write_text("key: value\n")
    result = chk.main([str(a), str(b)])
    out = capsys.readouterr().out
    assert result == 1
    assert "a.py" in out
    assert "b.yml" in out
