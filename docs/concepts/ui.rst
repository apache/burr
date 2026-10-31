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


.. _ui:

==============
Burr UI Server
==============

The Burr UI server is a local web application for visualizing and debugging
AI applications built with Burr. It reads the execution data recorded by the
:ref:`tracking client <trackingclientref>` — the component that writes each
step's inputs, outputs, and state to disk as your app runs — and presents it
as a browsable, step-by-step interface.

Use it to understand how your application moved through its state machine,
inspect what data each action received and returned, and replay any prior
run from an exact point in time for debugging.

------------
Installation
------------

The UI server is not included in the base ``apache-burr`` package. Install
it with the ``start`` extra:

.. code-block:: bash

    pip install "apache-burr[start]"

This installs the server and all its dependencies (FastAPI, uvicorn, click,
and others) along with the bundled demo projects.

.. note::

    If you are on Python 3.13 and encounter an import error related to
    ``pandas`` after installation, run:

    .. code-block:: bash

        pip install --upgrade pandas

    This is a known compatibility issue between older pandas releases and
    Python 3.13.

--------------------------
Demo Data and First Launch
--------------------------

When you run ``burr`` for the first time, it automatically copies four demo
projects into ``~/.burr`` so you can explore the UI immediately — no app of
your own required. These demos include a chatbot, a counter, a conversational
RAG pipeline, and a chatbot with traces.

For example, after running ``burr``, open your browser to
``http://localhost:7241`` and you will see:

.. code-block:: text

    counter             — a simple counting app (great for learning the basics)
    conversational-rag  — a retrieval-augmented generation chatbot
    chatbot_with_traces — a chatbot with detailed tracing enabled
    chatbot             — a multi-modal chatbot demo

Click any project to browse its runs, then click a run to see its steps.

To skip copying demo data (for example, if you have already explored them
and only want to see your own projects):

.. code-block:: bash

    burr --no-copy-demo_data

--------------------------
Command-Line Options
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Option
     - Description
   * - ``--port INTEGER``
     - Run the server on a different port. Default is 7241. Example:
       ``burr --port 8080`` starts the server at ``http://localhost:8080``.
   * - ``--host TEXT``
     - Bind to a specific host. Default is ``127.0.0.1`` (your machine only).
       Use ``0.0.0.0`` to expose the server on your local network or inside
       a Docker container: ``burr --host 0.0.0.0``.
   * - ``--no-open``
     - Start the server without automatically opening a browser window.
       Useful when running on a remote machine or in a script:
       ``burr --no-open``.
   * - ``--no-copy-demo_data``
     - Skip copying the four demo projects into ``~/.burr`` on startup.
       Use this once you have already explored the demos and only want to
       see your own projects.
   * - ``--backend [local|s3]``
     - Choose where run data is stored. Default is ``local`` (reads from
       ``~/.burr`` on your filesystem). Use ``s3`` to connect to an
       Amazon S3 bucket instead: ``burr --backend s3``.
   * - ``--dev-mode``
     - Automatically restarts the server when the Burr source code changes.
       Only useful if you are actively developing Burr itself — not needed
       for regular use.

---------------------
What You Can Do
---------------------

Browse Your Projects
^^^^^^^^^^^^^^^^^^^^

The landing page lists every project that has been tracked. Each project
groups together all the runs of one application. For example, if you built
a customer support chatbot and ran it 10 times with different inputs, all
10 runs appear under one project.

**Try it:** Click **Projects** in the left sidebar. Click the ``demo_chatbot``
project. You will see 6 runs listed — each one a separate conversation the
demo app had.

Explore the Demo Projects
^^^^^^^^^^^^^^^^^^^^^^^^^

The four demo projects give you real, pre-recorded data to explore before
you have written any Burr code of your own. They show you what a real
agentic AI application looks like in practice.

**Try it:** Click the ``demo_chatbot`` project, then click
``chat-1-giraffe``. You will see 30 steps — a full conversation where
the user asked the chatbot to draw a giraffe.

Inspect Every Step of a Run
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Click any run to see a numbered list of every action that executed, in
order. Each row shows the action name and whether it succeeded or failed.
Click any step to see the full state at that moment.

**Try it:** Click step 0 in any run. The right panel shows the **State**
at that step — the data your application was carrying at that exact moment.

Compare State Before and After an Action
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For any step, you can see what the state looked like before the action ran,
after it ran, and exactly what changed. This is useful for understanding
what each action actually does.

**Try it:** Click any step, then click the **difference** button in the
top right of the State panel. Only the values that changed at that step
are shown — everything else is hidden.

View the Source Code of Any Action
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Every step links directly to the source code of the action that ran it.

**Try it:** Click any step, then click the **Code** tab in the top right.
You will see the exact Python function that executed at that step.

Replay a Run from Any Point
^^^^^^^^^^^^^^^^^^^^^^^^^^^

The **Reproduce** tab on any step gives you the code needed to reload
the application's state from that exact point in time. This lets you
re-run your application starting from a specific step — useful for
debugging a failure without having to replay the entire run from scratch.

**Try it:** Click any step in a run, then click the **Reproduce** tab.
You will see a code snippet you can paste into your own code to restore
that state.

Watch a Run in Real Time
^^^^^^^^^^^^^^^^^^^^^^^^

The **Live** button streams steps as they are executed. To use it:

1. Start the Burr UI server in one terminal: ``burr``
2. Open ``http://localhost:7241`` in your browser
3. In a second terminal, run any Burr application that has
   ``.with_tracker()`` configured
4. Click **Live** in the UI — new steps will appear automatically
   as your application executes them

-------------------------------
Launch from a Notebook
-------------------------------

You can launch the Burr UI from a Jupyter notebook or Google Colab using the
``%burr_ui`` IPython magic:

.. code-block:: python

    # Load the extension then launch the UI
    %load_ext burr.integrations.notebook
    %burr_ui

    # Output: Burr UI: http://127.0.0.1:7241

For Google Colab, expose the port to the browser:

.. code-block:: python

    from google.colab import output
    output.serve_kernel_port_as_window(7241)   # opens a new window
    output.serve_kernel_port_as_iframe(7241)   # inlines in an iframe

--------------------------------
Embed in a FastAPI Application
--------------------------------

You can mount the Burr UI inside an existing FastAPI application using
``mount_burr_ui``. This is useful if you are already running a FastAPI
server for your AI application and want the UI available on the same
server rather than as a separate process.

.. code-block:: python

    from fastapi import FastAPI
    from burr.tracking.server.run import mount_burr_ui

    app = FastAPI()

    # Mount Burr UI under /burr
    # The UI will be accessible at http://localhost:8000/burr
    mount_burr_ui(app, path="/burr")

----------------------------------
Making Your App Appear in the UI
----------------------------------

To have your application's runs show up in the UI, add ``.with_tracker()``
when building it:

.. code-block:: python

    from burr.core import ApplicationBuilder
    from burr.tracking import LocalTrackingClient

    app = (
        ApplicationBuilder()
        .with_graph(your_graph)
        .with_tracker(LocalTrackingClient(project="my-project"))
        .build()
    )

Without this line, your app runs but nothing is recorded. With it, every
step is automatically written to ``~/.burr`` and appears in the UI under
the project name you specified.

For more on the tracking client and how data is stored, see :ref:`tracking`.
