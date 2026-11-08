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

import subprocess
import sys
import types
from unittest.mock import MagicMock

import pytest

# Ensure IPython can be imported even if not installed in test environment
if "IPython" not in sys.modules:
    ipython = types.ModuleType("IPython")
    ipython_core = types.ModuleType("IPython.core")
    ipython_core_magic = types.ModuleType("IPython.core.magic")
    ipython_core_magic.Magics = object
    ipython_core_magic.line_magic = lambda f: f
    ipython_core_magic.magics_class = lambda cls: cls

    ipython_core_magic_arguments = types.ModuleType("IPython.core.magic_arguments")
    ipython_core_magic_arguments.argument = lambda *args, **kwargs: lambda f: f
    ipython_core_magic_arguments.magic_arguments = lambda: lambda f: f
    ipython_core_magic_arguments.parse_argstring = lambda *args, **kwargs: types.SimpleNamespace()

    ipython_core_shellapp = types.ModuleType("IPython.core.shellapp")
    ipython_core_shellapp.InteractiveShellApp = object

    ipython_display = types.ModuleType("IPython.display")
    ipython_display.IFrame = object
    ipython_display.display = lambda *args, **kwargs: None

    sys.modules["IPython"] = ipython
    sys.modules["IPython.core"] = ipython_core
    sys.modules["IPython.core.magic"] = ipython_core_magic
    sys.modules["IPython.core.magic_arguments"] = ipython_core_magic_arguments
    sys.modules["IPython.core.shellapp"] = ipython_core_shellapp
    sys.modules["IPython.display"] = ipython_display

from burr.integrations.notebook import (
    NotebookEnvironment,
    launch_ui,
    launch_ui_colab,
    launch_ui_jupyter,
)


def test_launch_ui_jupyter_uses_current_python_interpreter(monkeypatch):
    custom_executable = "/custom/virtualenv/bin/python"
    monkeypatch.setattr(sys, "executable", custom_executable)

    mock_popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", mock_popen)

    process, url = launch_ui_jupyter()

    mock_popen.assert_called_once()
    cmd = mock_popen.call_args[0][0]
    assert cmd[0] == custom_executable
    assert cmd[1] == "-c"
    assert "import uvicorn" in cmd[2]
    assert url == "http://127.0.0.1:7241"
    assert process == mock_popen.return_value


def test_launch_ui_jupyter_fallback_when_executable_empty(monkeypatch):
    monkeypatch.setattr(sys, "executable", "")

    mock_popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", mock_popen)

    process, url = launch_ui_jupyter()

    mock_popen.assert_called_once()
    cmd = mock_popen.call_args[0][0]
    assert cmd[0] == "python"
    assert url == "http://127.0.0.1:7241"


def test_launch_ui_colab_uses_current_python_interpreter(monkeypatch):
    custom_executable = "/colab/custom_env/bin/python"
    monkeypatch.setattr(sys, "executable", custom_executable)

    mock_popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", mock_popen)

    colab_output = types.SimpleNamespace(eval_js=MagicMock(return_value="https://colab-proxy-url/"))
    colab_mod = types.SimpleNamespace(output=colab_output)
    google_mod = types.SimpleNamespace(colab=colab_mod)
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.colab", colab_mod)
    monkeypatch.setitem(sys.modules, "google.colab.output", colab_output)

    process, url = launch_ui_colab()

    colab_output.eval_js.assert_called_once_with("google.colab.kernel.proxyPort(7241)")
    mock_popen.assert_called_once()
    cmd = mock_popen.call_args[0][0]
    assert cmd[0] == custom_executable
    assert cmd[1] == "-c"
    assert "import uvicorn" in cmd[2]
    assert url == "https://colab-proxy-url/"
    assert process == mock_popen.return_value


def test_launch_ui_colab_fallback_when_executable_empty(monkeypatch):
    monkeypatch.setattr(sys, "executable", "")

    mock_popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", mock_popen)

    colab_output = types.SimpleNamespace(eval_js=MagicMock(return_value="https://colab-proxy-url/"))
    colab_mod = types.SimpleNamespace(output=colab_output)
    google_mod = types.SimpleNamespace(colab=colab_mod)
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.colab", colab_mod)
    monkeypatch.setitem(sys.modules, "google.colab.output", colab_output)

    process, url = launch_ui_colab()

    mock_popen.assert_called_once()
    cmd = mock_popen.call_args[0][0]
    assert cmd[0] == "python"
    assert url == "https://colab-proxy-url/"


def test_launch_ui_environment_dispatch(monkeypatch):
    mock_jupyter = MagicMock(return_value=("proc_j", "url_j"))
    mock_colab = MagicMock(return_value=("proc_c", "url_c"))
    monkeypatch.setattr("burr.integrations.notebook.launch_ui_jupyter", mock_jupyter)
    monkeypatch.setattr("burr.integrations.notebook.launch_ui_colab", mock_colab)

    assert launch_ui(NotebookEnvironment.JUPYTER) == ("proc_j", "url_j")
    mock_jupyter.assert_called_once()

    assert launch_ui(NotebookEnvironment.COLAB) == ("proc_c", "url_c")
    mock_colab.assert_called_once()
