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
from pathlib import Path

import pytest


def _load_preview_module():
    module_path = (
        Path(__file__).resolve().parent.parent / "scripts" / "milestone_management_preview.py"
    )
    spec = importlib.util.spec_from_file_location("milestone_management_preview", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


preview = _load_preview_module()


def test_main_branch_uses_earliest_open_milestone():
    milestone = preview.choose_milestone("main", ["0.43.1", "0.43.0", "not-a-release"])

    assert milestone == "0.43.0"


def test_release_branch_maps_to_exact_version():
    milestone = preview.choose_milestone("release-0.43.1", ["0.43.0", "0.43.1"])

    assert milestone == "0.43.1"


def test_release_slash_branch_maps_to_exact_version():
    milestone = preview.choose_milestone("release/0.43.1", ["0.43.0", "0.43.1"])

    assert milestone == "0.43.1"


def test_apache_burr_release_branch_maps_to_exact_version():
    milestone = preview.choose_milestone("apache-burr-0.43.1-release", ["0.43.0", "0.43.1"])

    assert milestone == "0.43.1"


def test_minor_release_branch_maps_to_patch_zero_milestone():
    milestone = preview.choose_milestone("release-0.43", ["0.43.0", "0.43.1"])

    assert milestone == "0.43.0"


def test_minor_test_branch_maps_to_patch_zero_milestone():
    milestone = preview.choose_milestone("v0.43-test", ["0.43.0", "0.43.1"])

    assert milestone == "0.43.0"


def test_main_branch_without_open_release_milestone_skips_assignment():
    milestone = preview.choose_milestone("main", ["not-a-release"])

    assert milestone is None


def test_unmanaged_branch_skips_assignment():
    milestone = preview.choose_milestone("feature/example", ["0.43.0"])

    assert milestone is None


def test_missing_release_branch_milestone_raises_error():
    with pytest.raises(ValueError, match="Expected an open milestone named '0.43.1'"):
        preview.choose_milestone("release-0.43.1", ["0.43.0"])
