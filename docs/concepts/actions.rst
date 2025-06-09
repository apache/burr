=======
Actions
=======

.. _actions:

.. note::

    Actions are the core building block of Burr. They read from state and write to state.
    They can be synchronous and asynchonous, and have both a ``sync`` and ``async`` API.
    There are both function and class-based APIs.


Actions do the heavy-lifting in a workflow. They should contain all complex compute. You can define actions
either through a class-based or function-based API. If actions implement ``async def run`` then will be run in an
asynchronous context (and thus require one of the async application functions).

.. note::
    When implementing asynchronous actions with ``async def run``, you must also override the ``is_async`` method
    to return ``True``. This tells the framework to execute the action in an asynchronous context:

    .. code-block:: python

        class AsyncAction(Action):
            @property
            def is_async(self) -> bool:
                return True

            async def run(self, state: State) -> dict:
                # Async implementation
                ...


Actions have two primary responsibilities:

1. ``run`` -- compute a result
2. ``update`` -- modify the state

The ``run`` method should return a dictionary of the result and the ``update`` method should return
the updated state, given the results of the ``run`` method.
They declare their dependencies so the framework knows *which* state variables they read and write. This allows the
framework to optimize the execution of the workflow. We call (1) a ``Function`` and (2) a ``Reducer`` (similar to `Redux <https://redux.js.org/>`_, if you're familiar with frontend UI technology).

There are two APIs for defining actions: class-based and function-based. They are largely equivalent, but differ in use.

- use the function-based API when you want to write something quick and terse that reads from a fixed set of state variables
- use the class-based API when you want to leverage inheritance or parameterize the action in more powerful ways

.. _functionbasedactions:

----------------------
Function-based actions
----------------------

You can define actions by decorating a function with the :py:func:`@action <burr.core.action.action>` decorator. These
can return either just the updated state or a tuple of the result and the state. For example:

.. code-block:: python

    from burr.core import action, State

    @action(reads=["var_from_state"], writes=["var_to_update"])
    def custom_action(state: State) -> State:
        return state.update(var_to_update=state["var_from_state"] + 1)

    app = ApplicationBuilder().with_actions(
        custom_action=custom_action
    )...


Conceptually, these combine the ``update`` and ``run`` methods into a single function, and they're both executed at the same time.
You also have the option of returning the intermediate results, which is useful for tracking/debugging. The code
above is equivalent to returning an empty dictionary instead of the results.

.. code-block:: python

    from burr.core import action, State

    @action(reads=["var_from_state"], writes=["var_to_update"])
    def custom_action(state: State) -> State
        return results, state.update(var_to_update=var_from_state + 1)

    app = ApplicationBuilder().with_actions(
        custom_action=custom_action
    )...



Function-based actions can take in parameters which are akin to passing in constructor parameters. This is done through the :py:meth:`bind <burr.core.action.bind>` method:

.. code-block:: python

    @action(reads=["var_from_state"], writes=["var_to_update"])
    def custom_action(state: State, increment_by: int) -> State:
        return state.update(var_to_update=state["var_from_state"] + increment_by)

    app = ApplicationBuilder().with_actions(
        custom_action=custom_action.bind(increment_by=2)
    )...

This is the same as ``functools.partial``, but it is more explicit and easier to read. If an action has parameters that are not
bound, they will be referred to as inputs. For example:

.. code-block:: python

    @action(reads=["var_from_state"], writes=["var_to_update"])
    def custom_action(state: State, increment_by: int) -> State:
        return state.update(var_to_update=state["var_from_state"] + increment_by)

    app = ApplicationBuilder().with_actions(
        custom_action=custom_action
    )...

Will require the inputs to be passed in at runtime. See below for how to do that. You can use default values to set optional inputs as well:

.. code-block:: python

    @action(reads=["var_from_state"], writes=["var_to_update"])
    def custom_action(state: State, increment_by: int = 1) -> State:
        result = {"var_to_update": state["var_from_state"] + increment_by}
        return state.update(var_to_update=state["var_from_state"] + increment_by)

    app = ApplicationBuilder().with_actions(
        custom_action=custom_action
    )...

This means that the application does not *need* the inputs to be set.

Note: to access application-level metadata such as ``app_id``, ``partition_key``, ``sequence_id``, and ``action_name`` in your running application, you can have the :py:class:`ApplicationContext <burr.core.application.ApplicationContext>`
injected into your Burr Actions. This is done by adding ``__context`` to the action signature:

.. code-block:: python

    from burr.core import action, State, ApplicationContext

    @action(reads=[...], writes=[...])
    def my_action(state: State, __context: ApplicationContext) -> State:
        app_id = __context.app_id
        partition_key = __context.partition_key
        action_name = __context.action_name
        sequence_id = __context.sequence_id
        ...



-------------------
Class-Based Actions
-------------------

.. _classbasedactions:


You can define an action by implementing the :py:class:`Action <burr.core.action.Action>` class:

.. code-block:: python

    from burr.core import Action, State

    class CustomAction(Action):
        @property
        def reads(self) -> list[str]:
            return ["var_from_state"]

        def run(self, state: State) -> dict:
            return {"var_to_update": state["var_from_state"] + 1}

        @property
        def writes(self) -> list[str]:
            return ["var_to_update"]

        def update(self, result: dict, state: State) -> State:
            return state.update(**result)

You then pass the action to the :py:class:`ApplicationBuilder <burr.core.application.ApplicationBuilder>`:

.. code-block:: python

    from burr.core import ApplicationBuilder

    app = ApplicationBuilder().with_actions(
        custom_action=CustomAction()
    )...


Note that if the action has inputs, you have to define the optional ``inputs`` property:

.. code-block:: python

    from burr.core import Action, State

    class CustomAction(Action):
        @property
        def reads(self) -> list[str]:
            return ["var_from_state"]

        def run(self, state: State, increment_by: int) -> dict:
            return {"var_to_update": state["var_from_state"] + increment_by}

        @property
        def writes(self) -> list[str]:
            return ["var_to_update"]

        def update(self, result: dict, state: State) -> State:
            return state.update(**result)

        @property
        def inputs(self) -> list[str]:
            return ["increment_by"]


See below for how to pass in inputs at runtime. If you want to use optional inputs with the class-based API, ``inputs`` will return a tuple
of (required, optional) inputs. For example:

.. code-block:: python

    from burr.core import Action, State

    class CustomAction(Action):
        ...
        def inputs(self) -> Tuple[list[str], list[str]]:
            return ["increment_by"], ["optional_input"]

Note your code will have to handle the case where ``optional_input`` is not passed in (e.g. by setting the appropriate kwargs to the `run(...)` method.

If your action needs to know the current `partition_key`, `app_id`, or `sequence_id`, you can request the `__context` variable
be injected into the action. This is done by adding `__context` to the `inputs` property as well as the run method:

.. code-block:: python

    from burr.core import Action, State, ApplicationContext

    class Counter(Action):
        @property
        def reads(self) -> list[str]:
            return ["counter"]

        def run(self,
                state: State,
                increment_by: int,
                # add __context here
                __context: ApplicationContext) -> dict:
            # can access the app_id from the __context
            print(__context.app_id, __context.partition_key, __context.sequence_id)
            return {"counter": state["counter"] + increment_by}

        @property
        def writes(self) -> list[str]:
            return ["counter"]

        def update(self, result: dict, state: State) -> State:
            return state.update(**result)

        @property
        def inputs(self) -> list[str]:
            # add __context here
            return ["increment_by", "__context"]

Refer to :py:class:`Action <burr.core.action.Action>` for more documentation.


.. _inputref:

--------------
Runtime Inputs
--------------

Actions can declare parameters that are not part of the state. Use this to:

1. Provide variables that can be bound to an action. E.g. API clients, DB clients, etc.
2. Provide inputs that are required as part of the application to function, e.g. human input, configuration, etc.

For example using the function based API, consider the following action:

.. code-block:: python

    @action(reads=["..."], writes=["..."])
    def my_action(state: State, client: Client, prompt: str) -> State:
        """client & `prompt` here are something we need to pass in."""
        context = client.get_data(state["..."])
        result = llm_call(prompt, context) # some LLM call...
        return state.update(**result)

We need to pass in `client` and `prompt` somehow. Here are the ways to do that:

.. code-block:: python


    # (1) bind values
    app = (
        ApplicationBuilder()
          # we can "bind" values to an action
          .with_actions(my_action=my_action.bind(client=client))
        ...
        .build()
    )

    # (2) pass them in at runtime
    app.run( # or app.step, app.iterate, app.astep, etc.\n"
        halt_..., # your halt logic\n"
        inputs={"prompt": "this will be passed into `prompt`"} # <-- we pass in values here
    )

For instance, say you have a chatbot. The first step will likely declare the ``input`` parameter ``prompt`` --
it will take that, process it, and put the result in state. The subsequent steps will read the result of that from state.

---------------
Tagging Actions
---------------

You can tag actions with a list of strings -- this effectively functions as a "alias" for the action,
so that a single alias can refer to multiple actions. This allows you to refer to a set of actions
that have similar capabilities as one, using a variety of :ref:`application <applications>` APIs.

.. code-block:: python

    @action(reads=["..."], writes=["..."], tags=["response_to_display"])
    def text_response(state: State, client: Client, prompt: str) -> State:
        """client & `prompt` here are something we need to pass in."""
        context = client.get_data(state["..."])
        result = llm_call(prompt, context) # some LLM call...
        return state.update(**result)

This can be referred to either as the name of the action within the application, and/or as the tag
``response_to_display`` -- referred to as ``@tag:response_to_display`` in the ``halt_after`` or ``halt_before`` parameters
of :py:func:`Application.run <burr.core.application.Application.run>`, :py:func:`Application.iterate <burr.core.application.Application.iterate>`, etc.
APIs.

In all function-based APIs, you can pass in a list of tags with the ``tags`` parameter.
In class-based APIs, you can set the ``tags`` property.
