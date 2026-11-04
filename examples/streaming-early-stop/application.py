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
``finally`` block. Each ``*_demo`` function below stops the stream early in a different way, and
prints what happened, in order, so you can see when the resource is released and what Burr
reports to hooks/persisters.

In short: sync code just ``break``s; async code ``break``s inside
``async with contextlib.aclosing(...)``.

Run it with ``python application.py``. See README.md for the explanation.
"""

import asyncio
import contextlib
import logging
from typing import AsyncGenerator, Generator, List, Optional, Tuple

import anyio

from burr.core import Application, ApplicationBuilder, State
from burr.core.action import streaming_action
from burr.core.persistence import AsyncInMemoryPersister, SQLLitePersister
from burr.lifecycle import PostRunStepHook, PostRunStepHookAsync

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


def _report(log: Timeline, action, exception: Optional[BaseException]):
    outcome = "completed" if exception is None else f"failed with {exception!r}"
    log(f"post_run_step: {action.name} {outcome}")


class ReportStep(PostRunStepHook):
    """Stands in for any hook/tracker/persister: shows how each step was reported."""

    def __init__(self, log: Timeline):
        self.log = log

    def post_run_step(self, *, action, exception: Optional[BaseException], **future_kwargs):
        _report(self.log, action, exception)


class ReportStepAsync(PostRunStepHookAsync):
    """The same, for async applications: don't mix sync hooks into an async app."""

    def __init__(self, log: Timeline):
        self.log = log

    async def post_run_step(self, *, action, exception: Optional[BaseException], **future_kwargs):
        _report(self.log, action, exception)


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


def _builder(respond, hook) -> ApplicationBuilder:
    return (
        ApplicationBuilder()
        .with_actions(respond=respond)
        .with_transitions()
        .with_hooks(hook)
        .with_identifiers(app_id="early-stop-demo")
    )


def application(
    respond, log: Timeline, persister: Optional[SQLLitePersister] = None
) -> Application:
    builder = _builder(respond, ReportStep(log)).with_entrypoint("respond").with_state(State())
    if persister is not None:
        builder = builder.with_state_persister(persister)
    return builder.build()


async def async_application(
    respond, log: Timeline, persister: Optional[AsyncInMemoryPersister] = None
) -> Application:
    """Async app: async hooks, async persister, built with ``abuild()``."""
    builder = _builder(respond, ReportStepAsync(log)).with_entrypoint("respond").with_state(State())
    if persister is not None:
        builder = builder.with_state_persister(persister)
    return await builder.abuild()


def wants_to_stop(token: str) -> bool:
    """Stand-in for "the user hit stop", a moderation check, a token budget, ..."""
    return token == "tokens "


# --------------------------------------------------------------------------------------------
# Sync: just break.
# --------------------------------------------------------------------------------------------


def sync_break_demo():
    log = Timeline()
    app = application(_respond_sync(log), log)
    _, container = app.stream_result(halt_after=["respond"])
    for item in container:
        log(f"caller: got {item['token']!r}")
        if wants_to_stop(item["token"]):
            break  # the action's cleanup runs here, then the step is reported
    log("caller: after the loop")
    result, state = container.get()  # the step did not finish: no result, state not updated
    log(f"caller: get() -> result={result!r}, 'response' in state={'response' in state}")
    log.print("Sync: break")


def sync_iterate_break_demo():
    log = Timeline()
    app = application(_respond_sync(log), log)
    for _, container in app.stream_iterate(halt_after=["respond"]):
        for item in container:
            log(f"caller: got {item['token']!r}")
            if wants_to_stop(item["token"]):
                break
        break
    log("caller: after the loop")
    log.print("Sync: break out of stream_iterate")


# --------------------------------------------------------------------------------------------
# Async: break inside `async with contextlib.aclosing(...)`.
# --------------------------------------------------------------------------------------------


async def async_aclosing_demo():
    log = Timeline()
    app = await async_application(_respond_async(log), log)
    _, container = await app.astream_result(halt_after=["respond"])
    async with contextlib.aclosing(container):
        async for item in container:
            log(f"caller: got {item['token']!r}")
            if wants_to_stop(item["token"]):
                break
    log("caller: left the `async with` block")
    log.print("Async: break inside contextlib.aclosing(container)")


async def async_iterate_aclosing_demo():
    log = Timeline()
    app = await async_application(_respond_async(log), log)
    async with contextlib.aclosing(app.astream_iterate(halt_after=["respond"])) as steps:
        async for _, container in steps:
            async for item in container:
                log(f"caller: got {item['token']!r}")
                if wants_to_stop(item["token"]):
                    break
            break
    log("caller: left the `async with` block")
    log.print("Async: break inside contextlib.aclosing(app.astream_iterate(...))")


async def async_break_without_aclose_demo():
    log = Timeline()
    app = await async_application(_respond_async(log), log)
    _, container = await app.astream_result(halt_after=["respond"])
    async for item in container:
        if wants_to_stop(item["token"]):
            break
    log("caller: after the loop -- nothing has been cleaned up yet")
    await asyncio.sleep(0.01)  # ...the event loop gets to it later, in the background
    log("caller: some time later")
    log.print("Async without aclosing: cleanup is left to the event loop (avoid)")


# --------------------------------------------------------------------------------------------
# Cancelling the consuming task: from your own code, and from a web server on client disconnect.
# --------------------------------------------------------------------------------------------


async def cancel_task_demo():
    """E.g. a "stop" endpoint cancelling the task that streams to the user."""
    log = Timeline()
    app = await async_application(_respond_async(log, delay=0.05), log)

    async def stream_to_user():
        async with contextlib.aclosing(app.astream_iterate(halt_after=["respond"])) as steps:
            async for _, container in steps:
                async for item in container:
                    log(f"caller: got {item['token']!r}")

    task = asyncio.create_task(stream_to_user())
    await asyncio.sleep(0.12)
    log("caller: task.cancel()")
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    log.print("Cancelling the consuming task: hooks see CancelledError")


async def client_disconnect_demo():
    """What Starlette/FastAPI do on a client disconnect: cancel an anyio cancel scope.

    Unlike ``task.cancel()``, a cancel scope keeps cancelling every ``await`` inside it, so Burr's
    await on the async ``post_run_step`` hooks is cancelled too. The action's cleanup starts (an
    ``await`` in it would be cancelled too, unless shielded), and since nothing is saved for the
    stopped step, resuming re-runs it.
    """
    log = Timeline()
    persister = AsyncInMemoryPersister()
    app = await async_application(_respond_async(log, delay=0.05), log, persister=persister)

    async def stream_to_client():
        async with contextlib.aclosing(app.astream_iterate(halt_after=["respond"])) as steps:
            async for _, container in steps:
                async for item in container:
                    log(f"server: sent {item['token']!r}")

    async with anyio.create_task_group() as response:
        response.start_soon(stream_to_client)
        await asyncio.sleep(0.12)
        log("server: client disconnected -> cancel the response")
        response.cancel_scope.cancel()

    log(f"persister: saved for this run: {await persister.load(None, 'early-stop-demo')!r}")
    resumed = await (
        _builder(_respond_async(log), ReportStepAsync(log))
        .initialize_from(
            persister, resume_at_next_action=True, default_state={}, default_entrypoint="respond"
        )
        .with_state_persister(persister)
        .abuild()
    )
    log(f"resume: next action is {resumed.get_next_action().name!r} (it runs again)")
    log.print("Web server: client disconnect (async hooks don't run, resume is unaffected)")


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
# Cleanup errors: hooks always see them; close() raises them (every time) if you want them.
# --------------------------------------------------------------------------------------------


def cleanup_error_demo():
    log = Timeline()
    app = application(_respond_sync(log, cleanup_error=True), log)
    _, container = app.stream_result(halt_after=["respond"])
    for item in container:
        if wants_to_stop(item["token"]):
            break  # the error is reported to hooks and logged; the break itself doesn't raise
    try:
        container.close()
    except ConnectionError as e:
        log(f"caller: close() raised {e!r}")
    log.print("Cleanup errors: reported to hooks, and raised by close()")


def visualize():
    """Writes statemachine.png (the app is a single streaming action)."""
    application(_respond_sync(Timeline()), Timeline()).visualize(
        output_file_path="statemachine", include_conditions=True, format="png"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)  # hide the cleanup-error warning in this demo
    sync_break_demo()
    sync_iterate_break_demo()
    asyncio.run(async_aclosing_demo())
    asyncio.run(async_iterate_aclosing_demo())
    asyncio.run(async_break_without_aclose_demo())
    asyncio.run(cancel_task_demo())
    asyncio.run(client_disconnect_demo())
    resume_after_stop_demo()
    cleanup_error_demo()
