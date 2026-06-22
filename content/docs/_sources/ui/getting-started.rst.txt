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


.. _ui-getting-started:

===============
Getting Started
===============

-----------
Quick Start
-----------

Install Burr with the UI extras and launch the server:

.. code-block:: bash

    pip install "apache-burr[start]"
    burr

This starts the tracking server on port ``7241`` and opens the UI in your browser.

------------------
Connect Your App
------------------

Any application that uses :py:meth:`with_tracker <burr.core.application.ApplicationBuilder.with_tracker>`
will automatically appear in the UI:

.. code-block:: python

    from burr.core import ApplicationBuilder

    app = (
        ApplicationBuilder()
        .with_actions(...)
        .with_transitions(...)
        .with_tracker("local", project="my-project")
        .build()
    )

Run your application and then open ``http://localhost:7241`` to see your project,
its application runs, and the step-by-step trace.

-----------------------
Reloading Prior State
-----------------------

Because the tracking client writes to the local filesystem (``~/.burr`` by default), you
can reload state from any past run for debugging:

.. code-block:: python

    from burr.tracking import LocalTrackingClient

    tracker = LocalTrackingClient(project="my-project")
    app = (
        ApplicationBuilder()
        .with_graph(base_graph)
        .initialize_from(
            tracker,
            resume_at_next_action=True,
            default_state={},
            default_entrypoint="my-entrypoint",
            fork_from_app_id="<prior-app-id>",
            fork_from_sequence_id=None,
            fork_from_partition_key=None,
        )
        .with_tracker(tracker)
        .build()
    )

See :ref:`tracking` for the full tracking client reference.
