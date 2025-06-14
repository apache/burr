.. _statetyping:

============
Typing State
============

.. note::

    Burr allows you to specify types for your state. This enables more self-documenting, easy-to-write actions,
    allows you to type your entire application object for downstream consumption, and provides a way to inspect
    the state of your application prior to execution (for use by a web-server/other typing system). This is done
    through the use of pydantic schemas.

For a quick-start guide, see the `example <https://github.com/DAGWorks-Inc/burr/tree/main/examples/typed-state>`_


Burr has two approaches to specifying a schema for a state. These can work together as long as they specify clashing state:

1. Application-level typing
2. Action-level typing

These enable a host of other extensions/capabilities.

While these are built for pydantic, the typing system is intended to be pluggable, and we plan to add further integrations
(dataclasses, typed dicts, etc...).


Application-level Typing
------------------------

To type at the application level, you can use the :py:meth:`ApplicationBuilder.with_typing burr.core.application.ApplicationBuilder.with_typing` method.
This takes in a :py:class:`TypingSystem burr.core.typing.TypingSystem` object, which specifies how to gather types from/assign types to the state.

This looks as follows:

First, define a pydantic model for your application:

.. code-block:: python

    from pydantic import BaseModel

    class ApplicationState(pydantic.BaseModel):
        chat_history: List[dict[str, str]] = pydantic.Field(default_factory=list)
        prompt: Optional[str] = None
        mode: Optional[Literal["text", "image"]] = None
        response: Optional[dict[str, str]] = None

Then, we can use this model to type our application:

.. code-block:: python

    from burr.core import ApplicationBuilder
    from burr.integrations.pydantic import PydanticTypingSystem

    app = (
        ApplicationBuilder()
        .with_actions(...)
        .with_entrypoint(...)
        .with_transitions(...)
        .with_typing(PydanticTypingSystem(ApplicationState))
        .with_state(ApplicationState())
        .build()
    )

Your application is now typed with that pydantic model. If you're using an appropriate typing
integration in your IDE (E.G. pylance), it will know that the state of your application is of type
``MyApplicationState``.

When you have this you'll be able to run:

.. code-block:: python

    action_ran, result, state = app.run(inputs=...)
    state.data # of type ApplicationState -- do what you want with this!


Action-level typing
-------------------

You can also define type computations on on the action-level:

.. code-block:: python

    from burr.core import action

    @action.pydantic(reads=["prompt", "chat_history"], writes=["response"])
    def image_response(state: ApplicationState, model: str = "dall-e-2") -> ApplicationState:
        client = _get_openai_client()
        result = client.images.generate(
            model=model, prompt=state.prompt, size="1024x1024", quality="standard", n=1
        )
        response = result.data[0].url
        state.response = {"content": response, "type": MODES[state.mode], "role": "assistant"}
        return state

Note three interesting choices here:

1. The state is typed as a pydantic model
2. The return type is the same pydantic model
3. We mutate the state in place, rather than returning a new state

This is a different action API -- it effectively subsets the state on input,
gives you that object, then subsets the state on output, and merges it back.

Thus if you try to refer to a state variable that you didn't specify in the reads/writes,
it will give an error.

Mutating in place is OK as this produces a new object for each execution run. For now, you will
want to be careful about lists/list pointers -- we are working on that.


Application + Action-level typing
---------------------------------

Application-level typing has the benefit of giving you application-level IDE autocompletion and allowing you to specify
the schema. Action level typing makes it easier to write actions, and allows for more flexible/modular actions without specifying
the whole state in advance.

You can use them both as long as the types match up. If not, this will error out.

.. note::

    We have not yet implemented validation on more than just the action level -- this is coming soon!
