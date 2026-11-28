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

"""Regression tests: the streaming entry points used to process inputs twice.

``stream_result`` and ``astream_result`` built ``action_inputs`` from the caller's
inputs, but when the halt action was *not* streaming they delegated to
``_step`` / ``_astep``, which processed those same inputs again. A dependency such
as ``__context`` was therefore constructed twice per step, and the object built by
the streaming entry point was thrown away.

``stream_result`` documents that halting on a non-streaming action is supported,
so this is a supported path, not an edge case.
"""

import pytest

from burr.core import ApplicationBuilder, State, action


class _Recorder:
    def __init__(self):
        self.factory_calls = []
        self.action_calls = 0


def _build_app(recorder: _Recorder):
    @action(reads=[], writes=["finished"])
    def work(state: State, __context) -> State:
        recorder.action_calls += 1
        return state.update(finished=True)

    app = ApplicationBuilder().with_actions(work).with_entrypoint("work").build()

    def fresh_context(action_obj, sequence_id):
        # A new object per call makes duplicate invocations observable.
        obj = object()
        recorder.factory_calls.append(obj)
        return obj

    # ``__context`` is bound to ``self._context_factory`` when the application is
    # constructed, so the instance-level mapping is what has to be replaced.
    app._dependency_factory["__context"] = fresh_context
    return app


@pytest.mark.parametrize("use_async", [False, True], ids=["stream_result", "astream_result"])
async def test_streaming_entry_point_injects_dependency_once(use_async):
    """Halting on a non-streaming action must inject the dependency exactly once."""
    recorder = _Recorder()
    app = _build_app(recorder)
    inputs = {"unused": "ignored"}

    if use_async:
        _, container = await app.astream_result(halt_after=["work"], inputs=inputs)
        await container.get()
    else:
        _, container = app.stream_result(halt_after=["work"], inputs=inputs)
        container.get()

    assert recorder.action_calls == 1
    assert len(recorder.factory_calls) == 1, "__context should be injected once per step"
