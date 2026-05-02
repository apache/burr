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
"""Preview milestone selection for the milestone-management workflow.

Examples:
  python scripts/milestone_management_preview.py --base-branch main --open-milestones 0.43.0 0.43.1
  python scripts/milestone_management_preview.py --base-branch release-0.43.1 --open-milestones 0.43.0 0.43.1
  python scripts/milestone_management_preview.py --base-branch v0.43-test --open-milestones 0.43.0
"""

from __future__ import annotations

import argparse
import re
import sys

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_version(version: str) -> tuple[int, int, int]:
    match = SEMVER_RE.match(version)
    if not match:
        raise ValueError(f"Invalid milestone version: {version!r}. Expected X.Y.Z.")
    return tuple(int(part) for part in match.groups())


def milestone_title_for_branch(branch_name: str) -> str | None:
    exact_patterns = (
        re.compile(r"^release[-/](\d+\.\d+\.\d+)$"),
        re.compile(r"^apache-burr-(\d+\.\d+\.\d+)-release$"),
        re.compile(r"^v(\d+\.\d+\.\d+)-test$"),
    )
    for pattern in exact_patterns:
        match = pattern.match(branch_name)
        if match:
            return match.group(1)

    minor_patterns = (
        re.compile(r"^release[-/](\d+\.\d+)$"),
        re.compile(r"^v(\d+\.\d+)-test$"),
    )
    for pattern in minor_patterns:
        match = pattern.match(branch_name)
        if match:
            return f"{match.group(1)}.0"

    return None


# Keep this branch-to-milestone logic in sync with
# .github/workflows/milestone-management.yml.
def find_current_open_milestone(open_milestones: list[str]) -> str | None:
    valid_milestones = [title for title in open_milestones if SEMVER_RE.match(title)]
    if not valid_milestones:
        return None
    return min(valid_milestones, key=parse_version)


def choose_milestone(base_branch: str, open_milestones: list[str]) -> str | None:
    if base_branch == "main":
        return find_current_open_milestone(open_milestones)

    title = milestone_title_for_branch(base_branch)
    if title is None:
        return None
    if title not in open_milestones:
        raise ValueError(
            f"Expected an open milestone named {title!r} for base branch {base_branch!r}, but none exists."
        )
    return title


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-branch",
        required=True,
        help="The PR base branch to evaluate, for example main or release-0.43.0",
    )
    parser.add_argument(
        "--open-milestones",
        nargs="+",
        required=True,
        help="Open milestone titles visible to the workflow, for example 0.43.0 0.43.1",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        milestone = choose_milestone(args.base_branch, args.open_milestones)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if milestone is None:
        print(
            f"Base branch {args.base_branch!r} is not a managed release branch. "
            "The workflow would skip milestone assignment."
        )
        return 0

    print(milestone)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
