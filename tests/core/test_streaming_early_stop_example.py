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

CLOSED = "respond: close LLM connection"
STOPPED = "post_run_step: respond failed with GeneratorExit()"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("streaming_early_stop_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _timeline(capsys) -> list[str]:
    return [line.strip() for line in capsys.readouterr().out.splitlines() if line.startswith("   ")]


def _cleanup_then_report_then(events: list[str], caller_line: str):
    """The action is cleaned up, then the step is reported, all before the caller moves on."""
    i = events.index(CLOSED)
    assert events[i : i + 3] == [CLOSED, STOPPED, caller_line]


def test_sync_break(demo, capsys):
    demo.sync_break_demo()
    events = _timeline(capsys)
    _cleanup_then_report_then(events, "caller: after the loop")
    assert events[-1] == "caller: get() -> result=None, 'response' in state=False"


def test_sync_iterate_break(demo, capsys):
    demo.sync_iterate_break_demo()
    _cleanup_then_report_then(_timeline(capsys), "caller: after the loop")


async def test_async_aclosing(demo, capsys):
    await demo.async_aclosing_demo()
    _cleanup_then_report_then(_timeline(capsys), "caller: left the `async with` block")


async def test_async_iterate_aclosing(demo, capsys):
    await demo.async_iterate_aclosing_demo()
    _cleanup_then_report_then(_timeline(capsys), "caller: left the `async with` block")


async def test_async_break_without_aclose_defers_cleanup(demo, capsys):
    await demo.async_break_without_aclose_demo()
    events = _timeline(capsys)
    assert events.index("caller: after the loop -- nothing has been cleaned up yet") < (
        events.index(CLOSED)
    )


async def test_cancel_task(demo, capsys):
    await demo.cancel_task_demo()
    assert _timeline(capsys)[-3:] == [
        "caller: task.cancel()",
        CLOSED,
        "post_run_step: respond failed with CancelledError()",
    ]


async def test_client_disconnect(demo, capsys):
    """A cancel scope (Starlette's disconnect) also cancels the await on async hooks/persisters:
    the action is cleaned up, the step isn't recorded, and resuming still re-runs it."""
    await demo.client_disconnect_demo()
    events = _timeline(capsys)
    assert not any(event.startswith("post_run_step") for event in events)
    assert events[-4:] == [
        "server: client disconnected -> cancel the response",
        CLOSED,
        "persister: saved for this run: None",
        "resume: next action is 'respond' (it runs again)",
    ]


def test_resume_after_stop(demo, capsys):
    demo.resume_after_stop_demo()
    events = _timeline(capsys)
    assert "persister: last step saved as 'failed'" in events
    assert events[-1] == "resume: next action is 'respond' (it runs again)"


def test_cleanup_error(demo, capsys):
    demo.cleanup_error_demo()
    assert _timeline(capsys)[-3:] == [
        CLOSED,
        "post_run_step: respond failed with ConnectionError('LLM connection did not close cleanly')",
        "caller: close() raised ConnectionError('LLM connection did not close cleanly')",
    ]
