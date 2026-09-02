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


=================
Streaming Actions
=================
.. _streaming:

.. note::

    Burr actions can stream results! This enables you to display results to the user as
    tokens are streamed in.


Actions can be implemented as streaming results. This enables a lower time-to-first-token and a more interactive
interface in the case of AI applications or streaming in of metrics in a model-training application. Broadly,
this is a tool to enable quicker user interaction in longer running actions that require user focus.

Like other actions, these can be implemented both as functions and as classes, and can use synchronous or asynchronous APIs.

They are used differently from regular actions -- the application wraps their result in a
:py:class:`StreamingResultContainer <burr.core.action.StreamingResultContainer>`, or a
:py:class:`AsyncStreamingResultContainerAsync <burr.core.action.AsyncStreamingResultContainer>` for async streaming actions.

----------
Definition
----------
.. _streaming_actions:

Streaming actions can be implemented as a class or a function, just like actions. However, they have a few additional rules:

#. They give intermediate results to the user as they are produced in the form of a generator
#. They are responsible for determining the relationship between the intermediate results and the final result
#. They yield intermediate results to the framework, and the last yield is the final result (with everything joined). Don't forget the last yield!


The function-based streaming action is fairly simple. Note that
we yield a tuple of the result and the state update. The state update is ``None`` for intermediate results and
the final state for the final result.

.. code-block:: python

    from burr.core.action import streaming_action

    @streaming_action(reads=["prompt"], writes=["prompt"])
    def streaming_chat_call(state: State, **run_kwargs) -> Generator[Tuple[dict, Optional[State], None, None]]:
        client = openai.Client()
        response = client.chat.completions.create(
            model='gpt-3.5-turbo',
            messages=[{
                'role': 'user',
                'content': state["prompt"]
            }],
            temperature=0,
            stream=True,
        )
        buffer = []
        for chunk in response:
            delta = chunk.choices[0].delta.content
            buffer.append(delta)
            yield {'response': delta}, None # No state update on intermediate results
        full_response = ''.join(buffer)
        yield {'response': full_response}, state.append(response=full_response) # Update state on final results

A class-based streaming action might look like this:

.. code-block:: python

    from burr.core.action import StreamingAction

    class StreamingChatCall(StreamingAction):
        def stream_run(self, state: State, **run_kwargs) -> Generator[dict, None, None]:
            client = openai.Client()
            response = client.chat.completions.create(
                model='gpt-3.5-turbo',
                messages=[{
                    'role': 'user',
                    'content': state["prompt"]
                }],
                temperature=0,
                stream=True,
            )
            buffer = []
            for chunk in response:
                delta = chunk.choices[0].delta.content
                buffer.append(delta)
                yield {'response': delta}
            full_response = ''.join(buffer)
            yield {'response': full_response}

        @property
        def reads(self) -> list[str]:
            return ["prompt"]

        @property
        def writes(self) -> list[str]:
            return ["response"]

        def update(self, result: dict, state: State) -> State:
            return state.append(response=result["response"])

The logic is split between ``stream_run``, which is responsible for generating the intermediate results and
joining them into the final result, and update, which is responsible for collecting the final result and
updating the state. The final ``yield`` statement in ``stream_run`` is used to return the final result to the framework,
which is passed to ``update``. Note that the class-based variant separates out run/update into two methods, meaning
that it only yields the ``result`` and not the state update. The function-based variant, above, combined the two.

``async`` streaming actions are also supported. The corresponding function-based async looks like this:

.. collapse:: <code>fn_based_async</code>

    .. code-block:: python

        from burr.core.action import streaming_action

        @streaming_action(reads=["prompt"], writes=["prompt"])
        async def streaming_chat_call(state: State, **run_kwargs) -> AsyncGenerator[Tuple[dict, Optional[State]], None]:
            client = openai.AsyncClient()
            response = await client.chat.completions.create(
                model='gpt-3.5-turbo',
                messages=[{
                    'role': 'user',
                    'content': state["prompt"]
                }],
                temperature=0,
                stream=True,
            )
            buffer = []
            async for chunk in response: # loop over in async
                delta = chunk.choices[0].delta.content
                buffer.append(delta)
                yield {'response': delta}, None # No state update on intermediate results
            full_response = ''.join(buffer)
            yield {'response': full_response}, state.append(response=full_response) # Update state on final results

The class-based async streaming action will look like this:

.. collapse:: <code>class_based_async</code>

    .. code-block:: python

        from burr.core.action import StreamingAction

        class StreamingChatCallAsync(StreamingAction):
            async def stream_run(self, state: State, **run_kwargs) -> AsyncGenerator[dict, None]:
                client = openai.Client()
                response = await client.chat.completions.create(
                    model='gpt-3.5-turbo',
                    messages=[{
                        'role': 'user',
                        'content': state["prompt"]
                    }],
                    temperature=0,
                    stream=True,
                )
                buffer = []
                async for chunk in response:
                    delta = chunk.choices[0].delta.content
                    buffer.append(delta)
                    yield {'response': delta}
                full_response = ''.join(buffer)
                yield {'response': full_response}

            @property
            def reads(self) -> list[str]:
                return ["prompt"]

            @property
            def writes(self) -> list[str]:
                return ["response"]

            def update(self, result: dict, state: State) -> State:
                return state.append(response=result["response"])

-----
Usage
-----

When you call out to :py:meth:`stream_result <burr.core.application.Application.stream_result>` (as well as its corresponding async implementation
:py:meth:`astream_result <burr.core.application.Application.astream_result>` on a streaming action, you will get
a :py:class:`StreamingResultContainer <burr.core.action.StreamingResultContainer>`, or a :py:class:`AsyncStreamingResultContainerAsync <burr.core.action.AsyncStreamingResultContainer>`
object.

This object is effectively a cached iterator. You can use it as follows:

.. code-block:: python

    action, streaming_result = application.stream_result(
        halt_after='streaming_response', inputs={"prompt": prompt}
    )
    for result in streaming_result:
        print(result) # one by one

    result, state = streaming_result.get()
    print(result) # get the result

.. code-block:: python

    action, async_streaming_result = await application.astream_result(
        halt_after='streaming_response', inputs={"prompt": prompt}
    )
    async for result in async_streaming_result:
        print(result) # one by one

    result, state = await async_streaming_result.get()
    print(result) #  all at once


Thus you can run this in a web-service, a streamlit app, etc...

--------------
Considerations
--------------

All hooks/state update will be called once the iterator completes, or an exception interrupts the iterator
and it has to be cleaned up. You can call ``.stream_result()`` or ``.astream_result()`` on non-streaming
results, and it will return a ``StreamingResultContainer`` with an empty iterator that returns the result.
If streaming items are run as intermediate nodes in the graph, they will be run as normal actions
(effectively fully exhausted), and the result will be returned as a single item. Currently
you cannot use synchronous streaming actions as asynchronous streaming actions, but we will likely be
adding a bridge.

In version ``0.18.0`` we changed the synchronous method of streaming to
be consistent with the asynchronous method. If you're using the old version, there are a few changes you'll have to make (for the function-based API):

1. The return type of the streaming action should be ``Generator[Tuple[dict, Optional[State], None, None]]`` instead of ``Generator[dict, None, Tuple[dict, State]]``.
2. All intermediate results should be yielded as ``yield {'response': delta}, None`` instead of ``yield {'response': delta}``.
3. The final result will be a ``yield`` instead of a ``return``
