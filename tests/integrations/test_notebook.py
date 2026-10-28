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

import sys
import types
from unittest.mock import Mock, patch

from burr.integrations import notebook


def test_launch_ui_jupyter_uses_current_python_interpreter():
    with patch("burr.integrations.notebook.subprocess.Popen") as popen:
        notebook.launch_ui_jupyter()

    command = popen.call_args.args[0]
    assert command[0] == sys.executable


def test_launch_ui_colab_uses_current_python_interpreter(monkeypatch):
    google_module = types.ModuleType("google")
    colab_module = types.ModuleType("google.colab")
    output_module = types.ModuleType("google.colab.output")
    output_module.eval_js = Mock(return_value="https://colab.example/proxy/7241")

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.colab", colab_module)
    monkeypatch.setitem(sys.modules, "google.colab.output", output_module)

    with patch("burr.integrations.notebook.subprocess.Popen") as popen:
        notebook.launch_ui_colab()

    command = popen.call_args.args[0]
    assert command[0] == sys.executable
