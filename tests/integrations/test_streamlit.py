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


def test_load_state_from_log_file_reads_utf8(monkeypatch, tmp_path):
    monkeypatch.setitem(
        sys.modules,
        "burr.integrations.hamilton",
        types.SimpleNamespace(Hamilton=object, StateSource=object),
    )
    monkeypatch.setitem(sys.modules, "graphviz", types.SimpleNamespace(Digraph=object))
    monkeypatch.setitem(
        sys.modules, "streamlit", types.SimpleNamespace(session_state={})
    )
    streamlit = importlib.import_module("burr.integrations.streamlit")

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

    def guarded_open(*args, **kwargs):
        assert kwargs.get("encoding") == "utf-8"
        return real_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)

    app = object()
    state = streamlit.load_state_from_log_file(str(log_file), app)

    assert state.app is app
    assert state.history[0].state == {"message": "café"}
    assert state.history[0].action == "say"
    assert state.history[0].result == {"ok": True}
