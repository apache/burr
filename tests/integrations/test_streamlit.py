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

import builtins
import importlib
import json
import sys
import types
from pathlib import Path


def test_load_state_from_log_file_reads_utf8(monkeypatch, tmp_path):
    monkeypatch.setitem(
        sys.modules,
        "burr.integrations.hamilton",
        types.SimpleNamespace(Hamilton=object, StateSource=object),
    )
    monkeypatch.setitem(sys.modules, "graphviz", types.SimpleNamespace(Digraph=object))
    monkeypatch.setitem(sys.modules, "streamlit", types.SimpleNamespace(session_state={}))
    colors = types.ModuleType("matplotlib.colors")
    matplotlib = types.ModuleType("matplotlib")
    matplotlib.colors = colors
    monkeypatch.setitem(sys.modules, "matplotlib", matplotlib)
    monkeypatch.setitem(sys.modules, "matplotlib.colors", colors)
    # Use a temporary module name so stubbed imports cannot leak into later tests.
    name = "_burr_streamlit_under_test"
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[2] / "burr/integrations/streamlit.py"
    )
    streamlit = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, streamlit)
    spec.loader.exec_module(streamlit)

    log_file = tmp_path / "state.jsonl"
    log_file.write_text(
        json.dumps(
            {
                "state": {"message": "café"},
                "action": "say",
                "result": {"ok": True},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    real_open = builtins.open
    opened = []

    def guarded_open(*args, **kwargs):
        assert kwargs.get("encoding") == "utf-8"
        handle = real_open(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(builtins, "open", guarded_open)

    app = object()
    state = streamlit.load_state_from_log_file(str(log_file), app)

    assert state.app is app
    assert state.history[0].state == {"message": "café"}
    assert state.history[0].action == "say"
    assert state.history[0].result == {"ok": True}
    assert opened and all(handle.closed for handle in opened)
