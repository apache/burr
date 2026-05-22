..
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


=================
Durable Execution
=================

.. _durable-execution:

.. note::

    Durable execution lets an action pause mid-run (``__context.suspend()``),
    survive process restarts, and resume exactly where it stopped when an
    external event arrives. Sub-steps memoized with ``__context.durable()``
    are replayed from a journal on re-run so they never execute twice.

What is durable execution?
--------------------------

Some workflows cannot finish in a single continuous execution:

* **Human-in-the-loop.** An action drafts content and waits for a human to
  approve it before the workflow proceeds. The process may be restarted many
  times while waiting.
* **External-event wait.** An action triggers a webhook and must wait for the
  callback, which could arrive seconds or days later.
* **Crash resilience.** Long-running inference or IO inside an action can be
  checkpointed so that a restart does not redo expensive work already completed
  before the crash.

Burr addresses all three scenarios with two primitives on
:py:class:`ApplicationContext <burr.core.application.ApplicationContext>`:
``suspend()`` for pausing the run and ``durable()`` / ``adurable()`` for
memoizing sub-steps so they survive a suspend/resume boundary.

Suspending a run: ``suspend()``
--------------------------------

Call ``__context.suspend(channel)`` inside an action to pause the entire run
and wait for an external payload on the named *channel*. The call raises an
internal control-flow signal that the run loop catches; the run stops and a
:py:class:`SuspensionRecord <burr.core.durable.SuspensionRecord>` is persisted.

On resume the action **re-runs from the top**. When execution reaches the same
``suspend(channel)`` call again, the already-delivered payload is returned
instead of raising the signal.

.. code-block:: python

    from burr.core import action, State

    @action(reads=["draft"], writes=["review_decision"])
    def review(state: State, __context) -> State:
        # Optional: memoize an expensive step before suspending (see below).
        summary = __context.durable(
            "summarize",
            lambda d: f"SUMMARY: {d[:50]}...",
            state["draft"],
        )
        # Suspend until a human posts a payload to "human_approval".
        payload = __context.suspend(
            "human_approval",
            metadata={"summary": summary},
        )
        return state.update(review_decision=payload)

Signature::

    __context.suspend(
        channel: str,
        *,
        schema: Optional[type] = None,
        metadata: Optional[dict] = None,
    ) -> Any

* ``channel`` -- a stable name for this suspension point.
* ``schema`` -- optional Pydantic model or dataclass; when supplied, a dict
  payload is coerced via ``schema(**payload)`` before being returned.
* ``metadata`` -- free-form dict stored with the suspension record; useful for
  surfacing context to the UI or a webhook handler.
* **Return value** -- the ``payload`` delivered by :py:func:`resume()
  <burr.core.resume.resume>` when the run is resumed.

.. warning::

    ``_Suspended`` inherits from ``BaseException``, not ``Exception``. Do not
    wrap ``__context.suspend()`` calls inside ``asyncio.shield()``,
    ``try/except BaseException``, or any other guard that catches
    ``BaseException`` -- doing so will swallow the signal and prevent the run
    from suspending correctly.


Memoizing sub-steps: ``durable()`` and ``adurable()``
------------------------------------------------------

Because the action re-runs from the top on resume, any side-effectful or
expensive work executed *before* the ``suspend()`` call will execute again.
Use ``__context.durable(key, fn, *args, **kwargs)`` to memoize a sub-step so
it runs exactly once regardless of how many times the action is re-executed.

On the first run ``fn`` is called and its result is written to an append-only
*journal*. On re-run the same ``key`` is looked up in the journal and the
cached result is returned without calling ``fn`` again.

.. code-block:: python

    @action(reads=["content"], writes=["result"])
    def process(state: State, __context) -> State:
        # Expensive LLM call -- runs once, replayed on resume.
        summary = __context.durable(
            "llm_summarize",
            call_llm,           # fn
            state["content"],   # *args
        )

        # Async variant -- use inside async actions.
        # embedding = await __context.adurable("embed", fetch_embedding, summary)

        payload = __context.suspend("approval", metadata={"summary": summary})
        return state.update(result=payload)

Signatures::

    __context.durable(key: str, fn: Callable, *args, **kwargs) -> Any
    await __context.adurable(key: str, fn: Callable, *args, **kwargs) -> Any

* ``key`` -- a stable, unique identifier for this sub-step (see determinism
  contract below).
* ``fn`` -- a callable (or coroutine function for ``adurable``) whose result
  should be memoized.
* ``*args, **kwargs`` -- forwarded to ``fn`` on first execution only.

.. note::

    Do not call ``suspend()`` from inside a ``durable()`` fn. The fn must be
    a pure computation that returns a value.


The determinism contract
-------------------------

The run loop identifies journal entries by position (call index) and key. For
replay to work correctly, every re-run of the same action invocation must call
``durable()`` / ``adurable()`` in **exactly the same order** with **exactly
the same keys**. Violations raise :py:exc:`DeterminismError
<burr.core.durable.DeterminismError>` immediately (fail-loud).

Rules:

1. **Stable key per call site.** Use a string literal, not a runtime value
   that may change (e.g., a timestamp or UUID).

2. **Stable call order.** The set and order of ``durable()`` calls must be
   identical on every re-run of the same invocation.

3. **No non-deterministic branching.** Do not gate a ``durable()`` call on
   a condition that may differ between the first run and the re-run:

   .. code-block:: python

       # BAD -- the branch may not be taken on resume.
       if random.random() > 0.5:
           ctx.durable("step", fn)

       # GOOD -- key is unconditional.
       result = ctx.durable("step", fn)

4. **No ``suspend()`` inside ``durable()`` fn.** The fn must return a plain
   value; calling ``suspend()`` inside it raises ``_Suspended`` before the
   result is recorded and corrupts the journal.

5. **Mismatch raises ``DeterminismError``.** If ``key`` or call order differs
   between runs, a :py:exc:`DeterminismError <burr.core.durable.DeterminismError>`
   is raised, converting a silent footgun into a loud failure.


Resuming a suspended run: ``resume()``
---------------------------------------

When the external event arrives (webhook, form POST, timer, etc.), call
:py:func:`resume() <burr.core.resume.resume>` (sync) or
:py:func:`aresume() <burr.core.resume.aresume>` (async). Both helpers
reload the suspension from the persister, rebuild the Application, set the
resume payload, and run the graph to the next halt, suspend, or completion.

.. code-block:: python

    from burr.core import resume

    # Synchronous resume (e.g., inside a Flask route handler):
    final_state = resume(
        persister=persister,
        graph=graph,
        app_id="my-app-run-001",
        partition_key=None,
        channel="human_approval",
        payload={"approved": True},
    )

    # Asynchronous resume (e.g., inside a FastAPI route handler):
    from burr.core.resume import aresume

    final_state = await aresume(
        persister=persister,
        graph=graph,
        app_id="my-app-run-001",
        partition_key=None,
        channel="human_approval",
        payload={"approved": True},
    )

Both functions return the final :py:class:`State <burr.core.state.State>` after
the resumed run completes or reaches the next suspension.

**Idempotency.** For persisters with durable storage (see below), resuming an
already-resolved suspension is an idempotent no-op: the call returns the
latest persisted state unchanged. The ``resolved`` flag on the
:py:class:`SuspensionRecord <burr.core.durable.SuspensionRecord>` prevents
double-execution. For custom persisters without durable storage, a second
``resume()`` call after the first completes raises ``ValueError``.


Persister support
-----------------

First-party persisters ship with dedicated storage tables or collections for
suspension records and journal entries, providing strong resume-once semantics:

.. list-table::
   :header-rows: 1
   :widths: 25 20 55

   * - Backend
     - Driver
     - Class
   * - SQLite (sync)
     - sqlite3
     - :ref:`SQLitePersister <syncsqliteref>`
   * - SQLite (async)
     - aiosqlite
     - :ref:`AsyncSQLitePersister <asyncsqliteref>`
   * - PostgreSQL (sync)
     - psycopg2
     - :ref:`PostgreSQLPersister <syncpostgresref>`
   * - PostgreSQL (async)
     - asyncpg
     - :ref:`AsyncPostgreSQLPersister <asyncpostgresref>`
   * - Redis (sync)
     - redis
     - :ref:`RedisBasePersister <syncredisref>`
   * - Redis (async)
     - redis.asyncio
     - :ref:`AsyncRedisBasePersister <asyncredisref>`
   * - MongoDB
     - pymongo
     - :ref:`MongoDBBasePersister <syncmongoref>`

**Custom persisters** work transparently through an in-state fallback: the
:py:class:`SuspensionRecord <burr.core.durable.SuspensionRecord>` and journal
entries are embedded inside the reserved ``__burr_durable__`` key in
:py:class:`State <burr.core.state.State>`, which the existing persister hook
saves automatically. This is correct and requires no code changes, but it does
not provide the idempotency guarantees of the dedicated durable-storage
methods.

To opt in to durable storage for a custom persister, override all five methods
on :py:class:`BaseStatePersister <burr.core.persistence.BaseStatePersister>`:
``save_suspension``, ``load_suspension``, ``save_journal_entry``,
``load_journal``, and ``mark_suspension_resolved``.


``_Suspended`` and ``BaseException``
--------------------------------------

The internal control-flow signal ``_Suspended`` inherits from ``BaseException``
so that a user ``try/except Exception`` block inside an action does not
accidentally catch it. The run loop catches it explicitly. It is never logged
as a failure.

This means you must not wrap ``__context.suspend()`` calls in constructs that
catch ``BaseException``:

.. code-block:: python

    # BAD -- asyncio.shield catches BaseException and re-raises CancelledError;
    # _Suspended will be swallowed or mishandled.
    result = await asyncio.shield(__context.suspend("ch"))

    # GOOD -- call suspend directly.
    result = __context.suspend("ch")


Example
-------

A complete human-in-the-loop draft-review-finalize workflow is available in
the ``examples/durable-execution/`` directory of the repository. It
demonstrates:

* Using ``durable()`` to memoize an LLM summary before suspending.
* Calling ``suspend("human_approval")`` to pause the workflow.
* Using ``resume()`` to deliver the human's decision and finish the run.

See :ref:`available persisters here <persistersref>` for the full list of
backends that support the durable-storage APIs.
