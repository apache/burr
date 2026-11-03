<!--
     Licensed to the Apache Software Foundation (ASF) under one
     or more contributor license agreements.  See the NOTICE file
     distributed with this work for additional information
     regarding copyright ownership.  The ASF licenses this file
     to you under the Apache License, Version 2.0 (the
     "License"); you may not use this file except in compliance
     with the License.  You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

     Unless required by applicable law or agreed to in writing,
     software distributed under the License is distributed on an
     "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
     KIND, either express or implied.  See the License for the
     specific language governing permissions and limitations
     under the License.
-->

# Stopping a streaming action early

Streaming actions often hold something open while they stream, such as an HTTP connection to an LLM, a
database cursor, or a tracing span. They release it in a `finally` block or a `with` exit. When you stop
reading a stream before it ends (the user hits "stop", a moderation check trips, a token budget runs out,
the client disconnects), you want three things:

1. **The action's cleanup runs now**, not whenever the garbage collector gets to it.
2. **The step is reported honestly.** Hooks, trackers and persisters see it as *failed*, not completed, so
   resuming the application re-runs it.
3. **The state is not updated.** A half-finished response is never committed.

This example shows the patterns that give you all three. Every demo in [application.py](application.py)
prints a timeline of what happened, so you can see when the resource is released and what Burr
reports. Run it with:

```bash
python application.py
```

![statemachine](statemachine.png)

## The patterns

### 1. Stop reading, then `close()` the container

```python
action, container = app.stream_result(halt_after=["respond"])
for item in container:
    send_to_user(item["token"])
    if wants_to_stop(item):
        break
container.close()  # async: await container.aclose()

result, state = container.get()  # (None, state without the update)
```

`close()` / `aclose()` stops the action and runs its cleanup. Calling it more than once is safe. Once
the stream has finished normally, it does nothing (the step is still reported as completed).

**Always call it after a `break`.** A `break` on its own stops *you* from reading, but the action's
cleanup only runs when the container is closed or garbage-collected.

### 2. Use `contextlib.closing` / `contextlib.aclosing` around `stream_iterate`

```python
import contextlib

with contextlib.closing(app.stream_iterate(halt_after=["respond"])) as steps:
    for action, container in steps:
        for item in container:
            ...
            if wants_to_stop(item):
                break
        break
# leaving the block closed the in-flight action

async with contextlib.aclosing(app.astream_iterate(halt_after=["respond"])) as steps:
    async for action, container in steps:
        ...
```

This is the most robust option: however you leave the block (`break`, `return`, an exception, or
the task being cancelled), the in-flight action is closed. **Prefer this whenever you use
`stream_iterate` / `astream_iterate`.**

### 3. Client disconnects (web servers): cancellation does the work

When a client disconnects, ASGI servers such as Starlette/FastAPI *cancel* the task that is
producing the response. If your response generator uses pattern 2, that cancellation unwinds
the Burr action immediately. See [server.py](server.py):

```python
@app.get("/chat")
async def chat():
    async def sse():
        async with contextlib.aclosing(burr_app.astream_iterate(halt_after=["respond"])) as steps:
            async for _, container in steps:
                async for item in container:
                    yield f"data: {item['token']}\n\n"
    return StreamingResponse(sse(), media_type="text/event-stream")
```

```bash
uvicorn server:app
curl -N --max-time 1 localhost:8000/chat     # hang up after a second
# server log:
#   respond: open LLM connection
#   respond: close LLM connection
#   post_run_step: respond exception=CancelledError(...)
```

To stop a stream *from another task*, cancel the consuming task (as the server does). Don't call
`aclose()` on a container that another task is iterating: you can't close an async generator while
it's running.

## What gets reported

| How the stream ended | `post_run_step(exception=...)` | persister status | state updated? | on resume |
|---|---|---|---|---|
| read to the end | `None` | `completed` | yes | next action |
| `close()` / `aclose()` / `closing` before the end | `GeneratorExit()` | `failed` | no | **same action runs again** |
| task cancelled (e.g. client disconnect) | `CancelledError()` | `failed` | no | **same action runs again** |
| the action raised | that exception | `failed` | no | same action runs again |

So in a `post_run_step` hook, `exception is not None` means "this step did not complete". If you
want to tell a deliberate stop apart from a real failure:

```python
def post_run_step(self, *, exception, **kwargs):
    if exception is None:
        ...  # completed
    elif isinstance(exception, (GeneratorExit, asyncio.CancelledError)):
        ...  # stopped early by the caller / client
    else:
        ...  # a real error
```

Note that `GeneratorExit` and `CancelledError` derive from `BaseException`, not `Exception`.

## Things to know

- **Cleanup errors.** If the action's `finally` raises while it is being closed, `close()` / `aclose()`
  raises that error to you. See `cleanup_error_demo` in [application.py](application.py).
- **Use sync hooks/persisters to record client disconnects.** On a disconnect, Starlette/FastAPI
  cancels the whole response task. Sync `post_run_step` hooks (and sync persisters) still run and
  see the `CancelledError`. *Async* `post_run_step` hooks (and async persisters) are cancelled
  before they start, so they never record the stopped step. Shielding inside the hook does not
  help, because the hook body never runs.
- **Sync vs async.** Everything above works the same way for `stream_result`/`stream_iterate`
  (with `close()` / `contextlib.closing`) and `astream_result`/`astream_iterate` (with `aclose()` /
  `contextlib.aclosing`).

See also the [streaming actions docs](https://burr.apache.org/concepts/streaming-actions/) and the
[streaming-fastapi](../streaming-fastapi) example for a full chatbot.
