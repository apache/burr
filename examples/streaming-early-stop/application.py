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

"""Stopping a streaming action early -- the patterns to use.

The application is a single streaming action, ``respond``, that pretends to stream tokens from an
LLM. It holds a resource while it streams (think: an open HTTP connection) and releases it in a
``finally`` block. Each ``*_demo`` function below shows one way to stop the stream early, and
prints what happened, in order, so you can see when the resource is released and what Burr
reports to hooks/persisters.

Run it with ``python application.py``. See README.md for the explanation.
"""

import asyncio
import contextlib
from typing import AsyncGenerator, Generator, List, Optional, Tuple

from burr.core import Application, ApplicationBuilder, State
from burr.core.action import streaming_action
from burr.core.persistence import SQLLitePersister
from burr.lifecycle import PostRunStepHook

TOKENS = ["Burr ", "streams ", "tokens ", "one ", "at ", "a ", "time."]


class Timeline:
    """Collects what happened, in order, so the demos can print it."""

    def __init__(self):
        self.events: List[str] = []

    def __call__(self, event: str):
        self.events.append(event)

    def print(self, title: str):
        print(f"\n=== {title}")
        for event in self.events:
            print(f"   {event}")


class ReportStep(PostRunStepHook):
    """Stands in for any hook/tracker/persister: shows how each step was reported."""

    def __init__(self, log: Timeline):
        self.log = log

    def post_run_step(self, *, action, exception: Optional[BaseException], **future_kwargs):
        outcome = "completed" if exception is None else f"failed with {exception!r}"
        self.log(f"post_run_step: {action.name} {outcome}")


def _respond_sync(log: Timeline, cleanup_error: bool = False):
    @streaming_action(reads=[], writes=["response"])
    def respond(state: State) -> Generator[Tuple[dict, Optional[State]], None, None]:
        log("respond: open LLM connection")
        try:
            response = ""
            for token in TOKENS:
                response += token
                yield {"token": token}, None
            yield {"token": ""}, state.update(response=response)
        finally:
            log("respond: close LLM connection")
            if cleanup_error:
                raise ConnectionError("LLM connection did not close cleanly")

    return respond


def _respond_async(log: Timeline, delay: float = 0.0):
    @streaming_action(reads=[], writes=["response"])
    async def respond(state: State) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
        log("respond: open LLM connection")
        try:
            response = ""
            for token in TOKENS:
                await asyncio.sleep(delay)  # waiting for the next chunk from the network
                response += token
                yield {"token": token}, None
            yield {"token": ""}, state.update(response=response)
        finally:
            log("respond: close LLM connection")

    return respond


def application(
    respond, log: Timeline, persister: Optional[SQLLitePersister] = None
) -> Application:
    builder = (
        ApplicationBuilder()
        .with_actions(respond=respond)
        .with_transitions()
        .with_entrypoint("respond")
        .with_state(State())
        .with_hooks(ReportStep(log))
        .with_identifiers(app_id="early-stop-demo")
    )
    if persister is not None:
        builder = builder.with_state_persister(persister)
    return builder.build()


def wants_to_stop(token: str) -> bool:
    """Stand-in for "the user hit stop", a moderation check, a token budget, ..."""
    return token == "tokens "


# --------------------------------------------------------------------------------------------
# Pattern 1: stop reading, then close() the container.
# --------------------------------------------------------------------------------------------


def stop_with_close_demo():
    log = Timeline()
    app = application(_respond_sync(log), log)
    _, container = app.stream_result(halt_after=["respond"])
    for item in container:
        log(f"caller: got {item['token']!r}")
        if wants_to_stop(item["token"]):
            break
    container.close()  # releases the action's resources *now*
    log("caller: closed the container")
    result, state = container.get()  # the step did not finish: no result, state not updated
    log(f"caller: get() -> result={result!r}, 'response' in state={'response' in state}")
    log.print("Pattern 1: break, then container.close()")


async def stop_with_aclose_demo():
    log = Timeline()
    app = application(_respond_async(log), log)
    _, container = await app.astream_result(halt_after=["respond"])
    async for item in container:
        log(f"caller: got {item['token']!r}")
        if wants_to_stop(item["token"]):
            break
    await container.aclose()
    log("caller: closed the container")
    log.print("Pattern 1 (async): break, then await container.aclose()")


# --------------------------------------------------------------------------------------------
# Pattern 2: wrap stream_iterate/astream_iterate in contextlib.closing/aclosing.
# --------------------------------------------------------------------------------------------


def stop_iterate_with_closing_demo():
    log = Timeline()
    app = application(_respond_sync(log), log)
    with contextlib.closing(app.stream_iterate(halt_after=["respond"])) as steps:
        for _, container in steps:
            for item in container:
                log(f"caller: got {item['token']!r}")
                if wants_to_stop(item["token"]):
                    break
            break
    log("caller: left the `with` block")
    log.print("Pattern 2: contextlib.closing(app.stream_iterate(...))")


# --------------------------------------------------------------------------------------------
# Pattern 3: the client disconnects -> cancel the task that is consuming the stream.
# --------------------------------------------------------------------------------------------


async def client_disconnect_demo():
    log = Timeline()
    app = application(_respond_async(log, delay=0.05), log)

    async def stream_to_client():
        async with contextlib.aclosing(app.astream_iterate(halt_after=["respond"])) as steps:
            async for _, container in steps:
                async for item in container:
                    log(f"server: sent {item['token']!r}")

    task = asyncio.create_task(stream_to_client())
    await asyncio.sleep(0.12)
    log("server: client disconnected -> task.cancel()")
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    log.print("Pattern 3: client disconnect, cancel the consuming task")


# --------------------------------------------------------------------------------------------
# What a stopped step means for persistence: it is recorded as failed, and resuming re-runs it.
# --------------------------------------------------------------------------------------------


def resume_after_stop_demo():
    log = Timeline()
    persister = SQLLitePersister(db_path=":memory:", table_name="burr_state")
    persister.initialize()
    app = application(_respond_sync(log), log, persister=persister)
    _, container = app.stream_result(halt_after=["respond"])
    for item in container:
        if wants_to_stop(item["token"]):
            break
    container.close()
    log(f"persister: last step saved as {persister.load('', 'early-stop-demo')['status']!r}")

    resumed = (
        ApplicationBuilder()
        .with_actions(respond=_respond_sync(log))
        .with_transitions()
        .initialize_from(
            persister, resume_at_next_action=True, default_state={}, default_entrypoint="respond"
        )
        .with_identifiers(app_id="early-stop-demo")
        .build()
    )
    log(f"resume: next action is {resumed.get_next_action().name!r} (it runs again)")
    log.print("Persistence: a stopped step is 'failed' and is re-run on resume")


# --------------------------------------------------------------------------------------------
# Cleanup errors: close() raises them to the caller.
# --------------------------------------------------------------------------------------------


def cleanup_error_demo():
    log = Timeline()
    app = application(_respond_sync(log, cleanup_error=True), log)
    _, container = app.stream_result(halt_after=["respond"])
    for item in container:
        log(f"caller: got {item['token']!r}")
        if wants_to_stop(item["token"]):
            break
    try:
        container.close()
    except ConnectionError as e:
        log(f"caller: close() raised {e!r}")
    log.print("Cleanup errors: close() raises them to the caller")


def visualize():
    """Writes statemachine.png (the app is a single streaming action)."""
    application(_respond_sync(Timeline()), Timeline()).visualize(
        output_file_path="statemachine", include_conditions=True, format="png"
    )


if __name__ == "__main__":
    stop_with_close_demo()
    asyncio.run(stop_with_aclose_demo())
    stop_iterate_with_closing_demo()
    asyncio.run(client_disconnect_demo())
    resume_after_stop_demo()
    cleanup_error_demo()
