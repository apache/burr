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
Transitions
====================

.. _transitions:

.. note::

    While actions form the steps taken in an `application`, transitions decide which one to do next.
    They make decisions based on state. You can use them to specify which model to call, whether a conversation is
    over, or any other decision that needs to be made based on the current state.

Transitions define explicitly how actions are connected and which action is available next for any given state.
You can think of them as edges in a graph.

They have three main components:
- The ``from`` state
- The ``to`` state
- The ``condition`` that must be met to move from the ``from`` state to the ``to``

----------
Conditions
----------

Conditions have a few APIs, but the most common are the three convenience functions:

.. code-block:: python

    from burr.core import when, expr, default
    with_transitions(
        ("from", "to", when(foo="bar"),  # will evaluate when the state has the variable "foo" set to the value "bar"
        ("from", "to", expr('epochs>100')) # will evaluate to True when epochs is greater than 100
        ("from", "to", default)  # will always evaluate to True
        ("from", "to") # leaving out a third conditions we allow defaults
    )


``when()`` also supports comparison operators via Django-style ``__`` suffixes:

.. code-block:: python

    from burr.core import when
    with_transitions(
        ("check", "adult", when(age__gte=18)),       # age >= 18
        ("check", "child", when(age__lt=18)),         # age < 18
        ("check", "valid", when(score__gt=0, score__lte=100)),  # 0 < score <= 100
        ("check", "active", when(status__in=["active", "pending"])),  # membership
        ("check", "tagged", when(tags__contains="python")),  # collection contains value
        ("check", "clean", when(status__notin=["banned", "suspended"])),  # not in
        ("check", "changed", when(status__ne="initial")),  # not equal
        ("check", "missing", when(value__is=None)),  # identity check
        ("check", "present", when(value__isnot=None)),  # not-identity check
    )

Available operators:

- ``key=value`` — exact equality (default, unchanged)
- ``key__eq=value`` — explicit equality
- ``key__ne=value`` — not equal
- ``key__gt=value`` — greater than
- ``key__gte=value`` — greater than or equal
- ``key__lt=value`` — less than
- ``key__lte=value`` — less than or equal
- ``key__in=[values]`` — value is in the given collection
- ``key__notin=[values]`` — value is not in the given collection
- ``key__contains=value`` — collection/string in state contains the value
- ``key__is=value`` — identity check (``is``), useful for ``None``/``True``/``False``
- ``key__isnot=value`` — negated identity check (``is not``)

Multiple keyword arguments are ANDed together. For more complex expressions, use ``expr()``.

Conditions are evaluated in the order they are specified, and the first one that evaluates to True will be the transition that is selected
when determining which action to run next. If no condition evaluates to ``True``, the application execution will stop early.

The ``~`` operator will invert a condition. For instance:

.. code-block:: python

    from burr.core import when, expr
    with_transitions(
        ("from", "to", ~when(foo="baz"),  # will evaluate to True when foo != baz
        ("from", "to", ~expr('epochs<=100')) # will evaluate to True when epochs hits 101
    )

All keys present in the condition (E.G. ``foo`` and ``epochs`` above) must be present in the state for the condition to work. It will error otherwise.

.. note::

    The ``default`` condition is a special case, and will always evaluate to ``True``. It is useful for defining a "catch-all" transition
    that will be selected if no other condition is met. If you pass a tuple of length 2 to :py:meth:`with_transitions <burr.core.application.ApplicationBuilder.with_transitions>`, the
    default condition will be used.

See the :ref:`transition docs <transitionref>` for more information on the transition API.
