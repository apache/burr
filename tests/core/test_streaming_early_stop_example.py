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

"""Keeps examples/streaming-early-stop honest: each demo must show what its README claims."""

import importlib.util
import pathlib

import pytest

EXAMPLE = pathlib.Path(__file__).parents[2] / "examples" / "streaming-early-stop" / "application.py"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("streaming_early_stop_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _timeline(capsys) -> list[str]:
    return [line.strip() for line in capsys.readouterr().out.splitlines() if line.startswith("   ")]


def test_stop_with_close(demo, capsys):
    demo.stop_with_close_demo()
    events = _timeline(capsys)
    assert "respond: close LLM connection" in events
    assert "post_run_step: respond failed with GeneratorExit()" in events
    assert events.index("respond: close LLM connection") < events.index(
        "caller: closed the container"
    )
    assert events[-1] == "caller: get() -> result=None, 'response' in state=False"


async def test_stop_with_aclose(demo, capsys):
    await demo.stop_with_aclose_demo()
    events = _timeline(capsys)
    assert events.index("respond: close LLM connection") < events.index(
        "caller: closed the container"
    )
    assert "post_run_step: respond failed with GeneratorExit()" in events


def test_stop_iterate_with_closing(demo, capsys):
    demo.stop_iterate_with_closing_demo()
    events = _timeline(capsys)
    assert events.index("respond: close LLM connection") < events.index(
        "caller: left the `with` block"
    )
    assert "post_run_step: respond failed with GeneratorExit()" in events


async def test_client_disconnect(demo, capsys):
    await demo.client_disconnect_demo()
    events = _timeline(capsys)
    assert events[-2:] == [
        "respond: close LLM connection",
        "post_run_step: respond failed with CancelledError()",
    ]


def test_resume_after_stop(demo, capsys):
    demo.resume_after_stop_demo()
    events = _timeline(capsys)
    assert "persister: last step saved as 'failed'" in events
    assert events[-1] == "resume: next action is 'respond' (it runs again)"


def test_cleanup_error(demo, capsys):
    demo.cleanup_error_demo()
    events = _timeline(capsys)
    assert events[-1] == (
        "caller: close() raised ConnectionError('LLM connection did not close cleanly')"
    )
