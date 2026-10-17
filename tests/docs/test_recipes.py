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

import os
import subprocess
import sys
from pathlib import Path

import pytest

RECIPES_DIR = Path(__file__).parent / "recipes"
REPOSITORY_ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("recipe", sorted(RECIPES_DIR.glob("*.py")), ids=lambda path: path.stem)
def test_recipe_runs_in_isolation(recipe: Path, tmp_path: Path) -> None:
    env = os.environ.copy()
    python_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(REPOSITORY_ROOT), python_path) if part
    )

    result = subprocess.run(
        [sys.executable, str(recipe)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
