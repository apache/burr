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
State
=====

.. _state:

.. note::

    Burr's ``State`` API enables actions to talk to each other, and enables you to persist data.
    Burr has a ``State`` API that allows you to manipulate state in a functional way.

The :py:class:`State <burr.core.state.State>` class provides the ability to manipulate state for a given action. It is entirely immutable,
meaning that you can only create new states from old ones, not modify them in place.


State manipulation is done through calling methods on the ``State`` class. Because state is immutable,
each write returns a new ``State`` object. The most common writes are:

.. literalinclude:: ../../tests/docs/recipes/state.py
   :language: python
   :start-after: # docs:start:manipulate-state
   :end-before: # docs:end:manipulate-state

.. warning::

    The ``State`` object can only be treated immutably! Calling ``state.update(foo=bar)`` will do nothing if you don't use the value returned by the call.

.. warning::

    State contains a set of "private" variables that start with `__`. -- E.G. `__SEQUENCE_ID`. These are internal to Burr, used by the application to track state.
    Any modifications to them outside of the framework is considered undefined behavior -- it could be dropped, or error out (we reserve the right to alter this later).

The read operations extend from those in the `Mapping <https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping>`_
interface, but there are a few extra:

.. literalinclude:: ../../tests/docs/recipes/state.py
   :language: python
   :start-after: # docs:start:read-state
   :end-before: # docs:end:read-state

When an update action is run, the state is first subsetted to get just the keys that are being read from,
then the action is run, and a new state is written to. This state is merged back into the original state
after the action is complete. Pseudocode:

.. code-block:: python

    current_state = ...
    read_state = current_state.subset(action.reads)
    result = action.run(new_state)
    write_state = current_state.subset(action.writes)
    new_state = action.update(result, new_state)
    current_state = current_state.merge(new_state)

If you're used to thinking about version control, this is a bit like a commit/checkout/merge mechanism.

Reloading Prior State
---------------------
Note, if state is serializable, it means that if stored, it can be reloaded. This is useful for
reloading state from a previous invocation (for debugging or as part of the application), or for storing state in a database.
We have capabilities here, see the :ref:`state-persistence <state-persistence>` section.
