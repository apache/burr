===========================
Sync vs Async Applications
===========================

TL;DR
------

Burr gives you the ability to write synchronous (standard python) and asynchronous (``async def``/``await``) Burr applications. You then run these applications in some sort of python context (e.g. script, web-service, aws lambda, etc). Whether you choose to write your Burr application using Burr's synchronous or asynchronous features depends on where you plan to run your Burr application. At a high level:

1. Use the ``async`` interfaces when you have I/O-heavy applications that require horizontal scaling, and have available asynchronous APIs (E.G. async LLM APIs in a web-service like FastAPI)

   * :py:meth:`.abuild() <.ApplicationBuilder.abuild()>`
   * :py:meth:`.aiterate() <.Application.aiterate()>`
   * :py:meth:`.arun() <.Application.arun()>`
   * :py:meth:`.astream_result() <.Application.astream_result()>`

2. Use the synchronous interfaces otherwise -- when you have high CPU-bound applications (running models locally), or do not have async APIs to use:

   * :py:meth:`.build() <.ApplicationBuilder.build()>`
   * :py:meth:`.iterate() <.Application.iterate()>`
   * :py:meth:`.run() <.Application.run()>`
   * :py:meth:`.stream_result() <.Application.stream_result()>`

Checklist for Async Applications
-------------------------------

When building asynchronous applications with Burr, ensure you:

1. **Use async action implementations**:
   * Implement ``async def run`` methods in your actions
   * Override the ``is_async`` property to return ``True`` in all async class-based actions
   * Use ``await`` for all I/O operations inside your actions

2. **Use async builder and application methods**:
   * Use ``.abuild()`` instead of ``.build()``
   * Use ``.arun()``, ``.aiterate()``, and ``.astream_result()`` instead of their sync counterparts

3. **Use async hooks and persisters**:
   * Implement async hooks with ``async def`` methods
   * Use async persisters (e.g., ``AsyncPGPersister`` instead of ``PGPersister``)
   * Properly clean up async resources using context managers or explicit cleanup calls

4. **For parallel actions**:
   * Make ``actions``, ``states``, and ``reduce`` methods async
   * Override ``is_async`` to return ``True``
   * Use ``AsyncGenerator`` return types
   * Use async persisters with connection pools

Comparison
----------

A synchronous Python application processes tasks sequentially for every thread/process it executes, blocking entirely on the result
of the prior call. When using Burr, this means that two (or more) separate Burr applications, if they are to run concurrently, have to be run in separate threads/processes which you manage / control.

Specifically for Burr, this means that you have a 1:1 app -> thread/process mapping (unless you're using :ref:`parallelism <parallelism>` and explicitly multithreading sub-actions).

An asynchronous application can parallelize multiple I/O bound tasks within the confines of a single thread. At the time that
a task blocks on I/O it can give control back to the process, allow it to run other tasks simultaneously.

In the case of Burr, Burr supports this model in running multiple Burr applications, in parallel, on the same as thread (i.e. the asyncio event loop).
Note, however, that you have to ensure your Burr application is async all the way down -- E.G. that every blocking call
is called using `await` -- if it blocks the event loop through a slow, synchronous call, it will block *all* current
applications.

In general, Burr gives you the constructs for synchronous and asynchronous execution. We usually do that by
providing both methods (see specific references for more detail and reach out if you feel like we
are missing a specific implementation). Furthermore, Burr suports the following APIs for both synchronous/asynchronous interfaces:

- :ref:`hooks <hooksref>`
- :ref:`persisters <persistersref>`

Nuances of Sync + Async together
--------------------------------

We encourage to make a decision to either commit fully to sync or async. That said,
there are cases where a hybrid situation may be desirable or unavoidable (testing, prototyping,
legacy code, ...) and we give some options to handle that. The table bellow shows the
possibilities Burr now supports -- combining the set of synchronous/asynchronous.


.. table:: Cases Burr supports
    :widths: auto

    +------------------------------------------------+----------+----------------------------------+
    | Cases                                          | Works?   | Comment                          |
    +================================================+==========+==================================+
    | Sync Hooks <> Sync Builder <> Sync App Run     |  ✅      | This is a standard use           |
    |                                                |          | case highlighted                 |
    |                                                |          | in sync applications             |
    +------------------------------------------------+----------+----------------------------------+
    | Sync Hooks <> Sync Builder <> Async App Run    |  ⚠️      | This will work for now, but it is|
    |                                                |          | not recommended because there    |
    |                                                |          | will be blocking functions       |
    +------------------------------------------------+----------+----------------------------------+
    | Async Hooks <> Sync Builder <> Sync App Run    |  ⚠️      | This will run (if the async hook |
    |                                                |          | is not a persister), but the     |
    |                                                |          | async hooks are ignored -- will  |
    |                                                |          | be deprecated                    |
    +------------------------------------------------+----------+----------------------------------+
    | Async Hooks <> Sync Builder <> Async App Run   |  ⚠️      | This will run (if the async hook |
    |                                                |          | is not a persister), but you     |
    |                                                |          | should really use the async      |
    |                                                |          | builder                          |
    +------------------------------------------------+----------+----------------------------------+
    | Async Hooks <> Async Builder <> Async App Run  |  ✅      | This is a standard use case      |
    |                                                |          | highlighted       in async       |
    |                                                |          | applications                     |
    +------------------------------------------------+----------+----------------------------------+
    | Async Hooks <> Async Builder <> Sync App Run   |  ❌      | Use async run methods            |
    +------------------------------------------------+----------+----------------------------------+
    | Sync Hooks <> Async Builder <> Sync App Run    |  ❌      | Use sync builder                 |
    +------------------------------------------------+----------+----------------------------------+
    | Sync Hooks <> Async Builder <> Async App Run   |  ⚠️      | This will run (if the sync hook  |
    |                                                |          | is not a persister), but you     |
    |                                                |          | should really use the sync       |
    |                                                |          | builder                          |
    +------------------------------------------------+----------+----------------------------------+
