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


====================
Applications
====================

.. _applications:

.. note::

    Applications tie everything in Burr together. They specify which actions should be included,
    how they connect (including conditional edges), and how to run.

Applications form the core representation of the state machine. You build them with the ``ApplicationBuilder``.
Here is the minimum that is required:

1. A ``**kwargs`` of actions passed to ``with_actions(...)``
2. Any relevant transitions (with conditions)
3. An entry point -- this is the first action to execute

This is shown in the example from :ref:`getting started <simpleexample>`

.. code-block:: python

    from burr.core import ApplicationBuilder, default, expr
    app = (
        ApplicationBuilder()
        .with_actions(human_input, ai_response)
        .with_transitions(
            ("human_input", "ai_response"),
            ("ai_response", "human_input")
        ).with_state(chat_history=[])
        .with_entrypoint("human_input")
        .build()
    )

-------
Running
-------

There are four APIs for executing an application.

``step``/``astep``
------------------

Returns the tuple of the action, the result of that action, and the new state. Call this if you want to run the application step-by-step.

.. code-block:: python

    action, result, state = application.step()

If you're in an async context, you can run `astep` instead:

.. code-block:: python

    action, result, state = await application.astep()


Step can also take in ``inputs`` as a dictionary, which will be passed to the action's run function as keyword arguments.
This is specifically meant for a "human in the loop" scenario, where the action needs to ask for input from a user. In this case,
the control flow is meant to be interrupted to allow for the user to provide input. See :ref:`inputs <inputref>` and
:ref:`human in the loop <human-in-the-loop>` for more information.

.. code-block:: python

    action, result, state = application.step(inputs={"prompt": input()})

``iterate``/``aiterate``
------------------------

Iterate just runs ``step`` in a row, functioning as a generator:

.. code-block:: python

    for action, result, state in application.iterate(halt_after=["final_action_1", "final_action_2"]):
        print(action.name, result)

You can also run ``aiterate`` in an async context:

.. code-block:: python

    async for action, result, state in application.aiterate():
        print(action.name, result)


In the synchronous context this also has a return value of a tuple of:


#. the action that was specified in ``halt_after`` or ``halt_before``. In the `after` case the action will have already run. In the ``before`` case the action will not have run.

#. The result of that action, in the ``halt_after`` case, else None in the ``halt_before`` case.

#. The state of the application at the time of halting.

You can access this by looking at the ``value`` variable of the ``StopIteration`` exception that is thrown
at the end of the loop, as is standard for python generators.
See the function implementation of ``run`` to show how this is done.

In the async context, this does not return anything (asynchronous generators are not allowed a return value).

If you want it to (attempt to) run forever, you can pass empty lists to ``halt_after`` and ``halt_before``.

.. note::
    You can add inputs to ``iterate``/``aiterate`` by passing in a dictionary of inputs through the ``inputs`` parameter.
    This will only apply to the first action. Actions that are not the first but require inputs are considered undefined behavior.

.. warning::
    The state machine has the capability of halting even if it does not reach one of the specified conditions -- if there are
    no more transitions to take. This, however, is not a supported feature (and will log a warning). This is considered undefined behavior
    -- use at your own risk, and consider adding a halting condition, or a default transition to a terminal.

``run``/``arun``
----------------

Run just calls out to ``iterate`` and returns the final state.

The ``halt_after`` and ``halt_before`` keyword arguments specify when to break out of running the state machine
and return control back. ``halt_after`` will stop after the specified action(s) has run, and ``halt_before`` will stop before the specified action(s) has run.
If multiple are specified, it will stop after the first one encountered, and the return values will be for that action.

.. code-block:: python

    action, result, state = application.run(
        halt_after=["final_action_1", "final_action_2"]
    )


In the async context, you can run ``arun``:

.. code-block:: python

    action, result, state = await application.arun(
        halt_after=["final_action_1", "final_action_2"]
    )

.. note::
    You can add inputs to ``run``/``arun`` in the same way as you can with ``iterate`` -- it will only apply to the first action.

``run`` and ``arun`` largely have the same behavior as ``iterate`` and ``aiterate``.

``stream_result``/``astream_result``
------------------------------------

These allow you to stream responses back. Note they work best with streaming actions.
Read about them in the :ref:`streaming <streaming>` section.

---------
Graph API
---------

The application exposes a graph API, allowing you to specify it as a graph separate from application concerns.
While you likely won't use this in your first few applications, it will become useful when you want to run it
in a web-server (create a graph once, application many times), import the graph from another context, or run it in multiple contexts.


.. code-block:: python

    from burr.core import ApplicationBuilder, GraphBuilder
    graph = (
        GraphBuilder()
        .with_actions(human_input, ai_response)
        .with_transitions(
            ("human_input", "ai_response"),
            ("ai_response", "human_input")
        ).build()
    )
    app = (
        ApplicationBuilder()
        .with_graph(graph)
        .with_state(chat_history=[])
        .with_entrypoint("human_input")
        .build()
    )

You can read more about it in the :py:class:`GraphBuilder docs <burr.core.graph.GraphBuilder>`.

----------
Inspection
----------

You can ask various questions of the state machine using publicly-supported APIs:

- ``application.graph`` will give you a static representation of the state machine with enough information to visualize
- ``application.state`` will give you the current state of the state machine. Note that if you modify it the results will not show up -- state is immutable! Modify the state through actions.

See the :ref:`application docs <applicationref>`
