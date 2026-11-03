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

"""Client disconnects in a streaming FastAPI endpoint.

Run with ``uvicorn server:app``, then ``curl -N --max-time 1 localhost:8000/chat`` (curl hangs up
after a second, like a user closing the tab). The server log shows the LLM connection being closed
right away and the step reported to hooks as failed with ``CancelledError``.
"""

import asyncio
import contextlib
import logging
from typing import AsyncGenerator, Optional, Tuple

from fastapi import FastAPI
from starlette.responses import StreamingResponse

from burr.core import ApplicationBuilder, State
from burr.core.action import streaming_action
from burr.lifecycle import PostRunStepHook

logger = logging.getLogger("uvicorn.error")
app = FastAPI()


@streaming_action(reads=[], writes=["response"])
async def respond(state: State) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
    logger.info("respond: open LLM connection")
    try:
        response = ""
        for i in range(50):
            await asyncio.sleep(0.1)  # waiting for the next chunk from the LLM
            token = f"token-{i} "
            response += token
            yield {"token": token}, None
        yield {"token": ""}, state.update(response=response)
    finally:
        logger.info("respond: close LLM connection")


class LogStep(PostRunStepHook):
    # A *sync* hook: see the README for why async post-step hooks need care on disconnect.
    def post_run_step(self, *, action, exception: Optional[BaseException], **future_kwargs):
        logger.info("post_run_step: %s exception=%r", action.name, exception)


def chat_application():
    return (
        ApplicationBuilder()
        .with_actions(respond=respond)
        .with_transitions()
        .with_entrypoint("respond")
        .with_state(State())
        .with_hooks(LogStep())
        .build()
    )


@app.get("/chat")
async def chat() -> StreamingResponse:
    burr_app = chat_application()

    async def sse():
        # `aclosing` makes leaving this block -- normally, on error, or because the server
        # cancelled us when the client went away -- close the in-flight action immediately.
        async with contextlib.aclosing(burr_app.astream_iterate(halt_after=["respond"])) as steps:
            async for _, container in steps:
                async for item in container:
                    yield f"data: {item['token']}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")
