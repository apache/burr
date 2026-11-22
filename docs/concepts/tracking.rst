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


.. _tracking:

=============
Tracking Burr
=============

.. note::

    Burr's telemetry system is built in and easy to integrate. It allows you to understand
    the flow of your application, and watch it make decisions in real time. You can run it
    with sample projects by running ``burr`` in the terminal after ``pip install "apache-burr[start]"``.

Burr comes with a telemetry system that allows tracking a variety of information for debugging,
both in development and production.

The data model for tracking is simple:

1. **Projects** are the top-level grouping of data (the first page). This is specified in the constructor for the
   :py:meth:`with_tracker <burr.core.application.ApplicationBuilder.with_tracker>`, as the only required argument.
2. **Applications** get logged to projects. An application would be considered similar to a "trace" in distributed
   tracing systems. This is (optionally) specified as the ``app_id`` argument for the :py:meth:`with_tracker <burr.core.application.ApplicationBuilder.with_tracker>`
   method. A single ``application`` has shared state path across all its steps.
3. **Steps** are the individual steps that are executed in the state machine. The Burr UI will show the state of the
   state machine at the time of the step execution, as well as the input to and results of the step.

.. _trackingclientref:

---------------
Tracking Client
---------------

When you use :py:meth:`with_tracker <burr.core.application.ApplicationBuilder.with_tracker>`, you add a tracker to Burr.
This is a lifecycle hook that does the following:

#. Logs the static representation of the state machine
#. Logs any information before/after step execution, including
    - The step name
    - The step input
    - The state at time of execution
    - The timestamps

This currently defaults to (and only supports) the :py:class:`LocalTrackingClient <burr.tracking.LocalTrackingClient>` class, which
writes to a local file system, although we will be making it pluggable in the future. It will, by default, write to the directory
``~/.burr``.

.. _asynchronous-applications:

Asynchronous applications
^^^^^^^^^^^^^^^^^^^^^^^^^
If your application serializes through ``async def`` serializers -- typically because it has an
:py:class:`AsyncArtifactStore <burr.core.artifacts.AsyncArtifactStore>` attached -- the tracker has to
``await`` that I/O as well. Burr selects the client for you at build time:

.. list-table::
    :header-rows: 1

    * - Application
      - Client
      - Why
    * - ``.abuild()`` + ``AsyncArtifactStore``
      - :py:class:`AsyncLocalTrackingClient <burr.tracking.AsyncLocalTrackingClient>`
      - serializers are coroutines and must be awaited
    * - ``.abuild()`` + ``ArtifactStore`` (or no store)
      - :py:class:`LocalTrackingClient <burr.tracking.LocalTrackingClient>`
      - nothing to await; keeps the historical behavior
    * - ``.build()`` + ``ArtifactStore`` (or no store)
      - :py:class:`LocalTrackingClient <burr.tracking.LocalTrackingClient>`
      - same as above
    * - ``.build()`` + ``AsyncArtifactStore``, run with ``.arun()``
      - :py:class:`AsyncLocalTrackingClient <burr.tracking.AsyncLocalTrackingClient>`
      - the store still has to be awaited, so the async hooks are required

The choice depends on the *configuration*, not on how the application was built, and it is made when
the application is built -- so it does not matter whether you call ``with_tracker`` before or after
``with_object_store``.

Why a separate client, rather than one client with both hook families?
    Burr dispatches ``pre_run_step``/``post_run_step`` to *both* the synchronous and the asynchronous
    hook families (``call_all_lifecycle_hooks_sync_and_async``). A class that registered both would log
    every step twice, so :py:class:`AsyncLocalTrackingClient <burr.tracking.AsyncLocalTrackingClient>`
    implements only the asynchronous step hooks and shares the rest of the implementation with
    :py:class:`LocalTrackingClient <burr.tracking.LocalTrackingClient>` through a common, hook-free base.

What stays synchronous
    Only the two step hooks (and, for streaming, the stream hooks) are asynchronous. Everything else --
    ``post_application_create``, the span hooks, and ``do_log_attributes`` -- remains synchronous,
    because that is how Burr dispatches them: the OpenTelemetry span processor calls the span hooks from
    whichever thread ends the span. In particular, **attribute logging is outside the async-serde
    boundary**: attributes are written to the span as plain values and are not awaited, so an
    asynchronous serializer registered for an attribute's type will not be used there.

The log format is identical
    Both clients write the same ``BeginEntryModel``/``EndEntryModel`` JSONL records, so the Burr UI,
    the tracking server, and either client's ``initialize_from`` all work unchanged. Large values are
    still stored as artifact references (when an object store is configured) rather than inline.
    Appending a line to the JSONL file stays synchronous in both clients -- only serialization and
    object-store I/O are awaited.

How async step hooks are dispatched
    The ``pre`` hook, the action, and the ``post`` hook of an asynchronous step all run in the
    **same** asyncio task. ``call_all_lifecycle_hooks_sync_and_async`` awaits each asynchronous
    hook in the caller's task rather than gathering them into child tasks: ``asyncio.gather`` starts
    each hook in a new task with a *copy* of the current ``contextvars.Context``, so a value a
    ``pre`` hook sets (an OpenTelemetry span, the serialization context) would not be visible to
    the action or to the ``post`` hook, and a context token created there could not be detached
    later. Running them in one task keeps the trace tree correctly parented, restores the context
    reliably, and isolates concurrent applications from each other. Synchronous hooks are still
    called first, then the asynchronous ones, in registration order.

    Two consequences are worth knowing when writing a hook. Asynchronous hooks no longer run
    concurrently -- they are sequential, so I/O in two hooks no longer overlaps. And a
    ``ContextVar`` set inside a hook is visible to the hooks that run after it **and remains set in
    the calling task**, whereas with ``gather`` each hook had its own copy of the context.

Resuming with the async client
    :py:class:`AsyncLocalTrackingClient <burr.tracking.AsyncLocalTrackingClient>` is an
    :py:class:`AsyncBaseStateLoader <burr.core.persistence.AsyncBaseStateLoader>`, so it can be passed
    to ``initialize_from(...)`` just like the synchronous one. The deserializer re-seeds the
    serialization memo, so a resumed run does not re-upload artifacts it just read back.

Passing your own tracker
    If you pass a client instance to ``with_tracker``, Burr uses it exactly as given -- it is never
    silently swapped for the other variant. If it is the wrong kind for your execution mode (a
    synchronous client in an application that has to await its serializers), you will see the
    synchronous client used as-is; pass the matching variant yourself.

Debugging via Reloading Prior State
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Because the tracking client writes to the file system, you can reload the state of the state machine at any time. This is
useful for debugging, because you can quickly recreate the issue by running the state machine with the same point in time.

To do so, you'd use the classmethod _load()_ on the :py:class:`LocalTrackingClient <burr.tracking.LocalTrackingClient>`.

For example, to debug your Burr Application, you'd have some control flow like this using the `.initialize_from(...)` and `fork_from_*` functionality:

.. code-block:: python

    from burr.tracking import LocalTrackingClient

    prior_app_id = ... # some value
    sequence_id = ... # None or some prior step
    partition_key = "SOME_VALUE" # use None if not using a partition key

    project_name = "PROJECT_NAME"
    tracker = LocalTrackingClient(project=project_name)
    app = (
        ApplicationBuilder()
        .with_graph(base_graph) # your graph
        .initialize_from(
            tracker, # local tracker above
            resume_at_next_action=True,
            default_state={}, # your default state
            default_entrypoint="SOME_DEFAULT", # your default entry point
            fork_from_app_id=prior_app_id,
            fork_from_sequence_id=sequence_id,
            fork_from_partition_key=partition_key
        )
        .with_tracker(tracker)  # tracking + checkpointing in one line.
        .build()
    )

---------------
Tracking Server
---------------

The tracking server (now) is meant for visualizing the state machine and the steps that have been executed. You can
run it with the following command:

.. code-block:: bash

    burr

This will start a server on port 7241, and open up a browser window with the UI for you to explore.


Launch Burr UI from a notebook
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You can launch the Burr UI from a notebook or Google Colab using the ``%burr_ui`` "IPython magic".
This will show the Burr UI web app in an iframe below the cell. Pass ``--no-iframe`` to print its URL
instead (see :ref:`ui-notebook` for all options).

.. code-block:: python

    # in one cell - show the UI inline:
    %load_ext burr.integrations.notebook
    %burr_ui

    # or print the URL instead of embedding the UI:
    %burr_ui --no-iframe
    # → "Burr UI: http://127.0.0.1:7241"

.. code-block:: python

    # But you need to expose the port to the browser:
    from google.colab import output
    output.serve_kernel_port_as_window(7241) # this will open a new window
    output.serve_kernel_port_as_iframe(7241) # this will inline in an iframe

---------------------------------------------
Mount Burr UI inside an existing FastAPI app
---------------------------------------------

You can embed the Burr UI inside an existing FastAPI application using the
``mount_burr_ui`` helper.

Example:

.. code-block:: python

    from fastapi import FastAPI
    from burr.tracking.server.run import mount_burr_ui

    app = FastAPI()

    # Mount Burr UI under /burr
    mount_burr_ui(app, path="/burr")

This allows you to run the Burr tracking UI alongside your own FastAPI
application in the same server process.
