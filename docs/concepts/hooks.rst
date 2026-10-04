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


=====
Hooks
=====

.. _hooks:
.. note::

    Hooks allow you to customize every aspect of Burr's execution, plugging in whatever tooling,
    observability framework, or debugging tool you need.

Burr has a system of lifecycle adapters (adapted from the similar `Hamilton <https://github.com/apache/hamilton>`_ concept), which allow you to run tooling before and after
various places in a node's execution. For instance, you could:

1. Log every step as a trace in datadog
2. Add a time-delay to your steps to allow for rendering
3. Add a print statement to every step to see what happened (E.G. implement the printline in cowsay above)
4. Synchronize state/updates to an external database
5. Put results on a queue to feed to some monitoring system

Note some of the above are yet to be implemented.

To implement hooks, you subclass any number of the :ref:`available lifecycle hooks <hooksref>`.
These have synchronous and asynchronous versions, and your hook can subclass as many as you want
(as long as it doesn't do both the synchronous and asynchronous versions of the same hook).

To use them, you pass them into the :py:class:`ApplicationBuilder <burr.core.application.ApplicationBuilder>` as a ``*args`` list of hooks. For instance,
a hook that prints out the nodes name during execution looks like this.
We implement the pre/post run step hooks.

.. code-block:: python

    class PrintLnHook(PostRunStepHook, PreRunStepHook):
        def pre_run_step(self, *, state: "State", action: "Action", **future_kwargs: Any):
            print(f"Starting action: {action.node.name}")

        def post_run_step(
            self,
            *,
            state: "State",
            action: "Action",
            result: Optional[dict],
            sequence_id: int,
            exception: Exception,
            **future_kwargs: Any,
        ):
            print(f"Finishing action: {action.node.name}")

To include this in the application, you pass it into the :py:meth:`with_hooks <burr.core.application.ApplicationBuilder.with_hooks>` method.

.. code-block:: python

    app = (
        ApplicationBuilder()
        .with_hooks(PrintLnHook())
        ...
        .build())

Recording executions in tests
-----------------------------

``InMemoryExecutionRecorder`` captures action inputs, results, exceptions, and
business-state changes without configuring a tracking backend. This is useful for
asserting an agent's route or inspecting a local execution loop:

.. code-block:: python

    from burr.lifecycle import InMemoryExecutionRecorder

    recorder = InMemoryExecutionRecorder()
    app = ApplicationBuilder().with_hooks(recorder).build()

    app.run(halt_after=["final_answer"])
    assert [record.action for record in recorder.records] == [
        "plan",
        "call_tool",
        "final_answer",
    ]

Each record is immutable and includes ``app_id``, ``partition_key``,
``sequence_id``, inputs, result, exception, and a tuple of ``StateChange`` values.
Private Burr state keys prefixed with ``__`` are excluded. Call ``clear()`` to
reuse the recorder between tests.

.. note::

    There are synchronous and asynchronous hooks. Synchronous hooks will be called with both synchronous and asynchronous run methods
    (all of ``step``, ``astep``, ``iterate``, ``aiterate``, ``run``, and ``arun``), whereas synchronous hooks will only be called with
    the asynchronous methods (``astep``, ``aiterate``, ``arun``).

.. warning::
    Hook order is currently undefined -- they happen to be called now in the order in which they are defined. We will likely
    alter them to be called in the order they are defined (for `pre...`) hooks and in reverse order for `post...` hooks,
    but this is not yet implemented.

Read more about the hook API in the :ref:`hooks section <hooksref>`.
