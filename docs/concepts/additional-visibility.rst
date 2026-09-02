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


=====================
Additional Visibility
=====================

.. note::

    Burr comes with the ability to see inside your actions. This is a very pluggable framework
    that comes with the default tracking client, but can also be hooked up to tools such as `OpenTelemetry <https://opentelemetry.io/>`_ (OTel)

----------
Quickstart
----------
Below is a quick start. For more in depth documentation see the next few sections.

If you want to:
    (a) automatically instrument LLM API calls, and
    (b) see them show up in the Burr UI,

you can do the following:

    1. Determine the LLM API you want to instrument (e.g. OpenAI, Anthropic, etc...). \
       See `openllmetry repo <https://github.com/traceloop/openllmetry/tree/main/packages>`_ for available options.
    2. Use the local tracker and flip the `use_otel_tracing` flag to True in the ``ApplicationBuilder``.

Here's an example to instrument OpenAI:

.. code-block:: bash

    # install the appropriate openllmetry package
    pip install opentelemetry-instrumentation-openai


.. code-block:: python

    # add the right imports
    from opentelemetry.instrumentation.openai import OpenAIInstrumentor
    OpenAIInstrumentor().instrument()  # this instruments openai clients

    # create the local tracker
    tracker = LocalTrackingClient(project="your-project")
    app = (
        ApplicationBuilder()
        .with_graph(base_graph)
        #... whatever you do normally here
        .with_tracker(tracker, use_otel_tracing=True)  # set use_otel_tracing to True
        .build()
    )
    # use your app as you normally would -- go to the Burr UI and see additional spans!



-------
Tracing
-------

Burr comes with a tracing capability to see recursive spans inside an action. This is similar to
the `OpenTelemetry <https://opentelemetry.io/>`_ sdk, although it is simplified significantly.

To add the tracing capability, the action first has to declare a ``__tracer`` input. This is a
an object that instantiates spans and tracks state.

Then, using the ``__tracer`` as a callable, you can instantiate spans and track state.

For the function-based API, this would look as follows:

.. code-block:: python

    from burr.visibility import TracerFactory
    from burr.core import action

    @action(reads=['prompt'], writes=['response'])
    def my_action(state: State, __tracer: TracerFactory) -> State:
        with __tracer('create_prompt'):
            modified_prompt = _modify_prompt(state["prompt"])
            with __tracer('check_prompt_safety'):
                if _is_unsafe(modified_prompt):
                    modified_prompt = _fix(modified_prompt)
        with __tracer('call_llm', dependencies=['create_prompt']):
            response = _query(prompt=modified_prompt)
        return state.update({'response': response})


This would create the following traces:

#. ``create_prompt``
#. ``check_prompt_safety`` as a child of ``create_prompt``
#. ``call_llm`` as a causal dependent of ``create_prompt``

Dependencies are used to express [dag](-style structures of spans within actions. This is useful for gaining visibility into the internal structure
of an action, but is likely best used with integrations with micro-orchestration systems for implementing actions, such as Hamilton or Lanchain.
This maps to the `span link <https://opentelemetry.io/docs/concepts/signals/traces/#span-links>`_ concept in OpenTelemetry.

Note that, on the surface, this doesn't actually *do* anything. It has to be paired with the appropriate hooks.
These just function as callbacks (on enter/exit). The :py:class:`LocalTrackingClient <burr.tracking.LocalTrackingClient>`, used by the
:ref:`tracking <tracking>` feature forms one of these hooks, but we will be adding more, including:

1. An OpenTelemetry client
2. A DataDog client

.. note::

    The class-based API can leverage this by declaring ``inputs`` as ``__tracer`` and then using the ``__tracer`` inside the ``run`` method.

------------
Observations
------------

You can make observations on the state by calling out to the :py:meth:`log_attribute <burr.visibility.ActionSpanTracer.log_attribute>` or :py:meth:`log_attributes <burr.visibility.ActionSpanTracer.log_attributes>` method on the ``__tracer`` context manager
or the root tracer factory. Note: the `trace()` decorator explained below can substitute for the following approach in many cases.

This allows you to log any arbitrary observations (think token count prompt, whatnot) that may not be part of state/results.

For instance:

.. code-block:: python

    from burr.visibility import TracerFactory
    from burr.core import action

    @action(reads=['prompt'], writes=['response'])
    def my_action(state: State, __tracer: TracerFactory) -> State:
        __tracer.log_attributes(prompt_length=len(state["prompt"]), prompt=state["prompt"])

        # note: see `@trace()` below as an alternative to this approach.
        with __tracer('create_prompt') as t:
            modified_prompt = _modify_prompt(state["prompt"])
            t.log_attributes(modified_prompt=modified_prompt)
            with __tracer('check_prompt_safety') as t:
                if is_unsafe:=_is_unsafe(modified_prompt):
                    modified_prompt = _fix(modified_prompt)
                t.log_attributes(fixed_prompt=modified_prompt, is_unsafe=is_unsafe)
        with __tracer('call_llm', dependencies=['create_prompt']):
            response = _query(prompt=modified_prompt)
            t.log_attributes(response=response.message, tokens=response.tokens)
        return state.update({'response': response.message})

The above will log quite a few attributes, prompt length, response tokens, etc... The observation can be any serializable object.

Note that we are currently building out the capability to wrap a class and "auto-log" standard attributes.

You can read more in the :ref:`reference documentation <visibility>`.


-----------------
Tracing Functions
-----------------

You can observe non-burr functions, which will show up as part of your traces. To do this, you simply need to decorate the
function with the :py:func:`@trace <burr.visibility.tracing.trace>` decorator. This will automatically create a span
for the function (within the appropriate context), and log as attributes the parameters + return value.

For instance:

.. code-block:: python

    from burr.core import action
    from burr.visibility import trace

    @trace()
    def _modify_prompt(prompt: str) -> str:
        return ...

    @trace()
    def _fix(prompt: str) -> str:
        return ...

    @trace()
    def _query(prompt: str) -> Response:
        return ...

    @action(reads=['prompt'], writes=['response'])
    def my_action(state: State) -> State:
        modified_prompt = _modify_prompt(state["prompt"])
        if _is_unsafe(modified_prompt):
              modified_prompt = _fix(modified_prompt)
        response = _query(prompt=modified_prompt)
        return state.update({'response': response})


This will create spans for the ``_modify_prompt``, ``_fix``, and ``_query`` functions, and log the parameters and return values. You can opt out of logging parameters or return values and adding a filter to the decorator to exclude certain parameters.
To contrast what you can instrument manually, the ``@trace`` decorator allows you to get more visibility and replace manual code such as the following (though you can happily combine the two approaches):

.. code-block:: python

    from burr.visibility import TracerFactory
    from burr.core import action
    @action(reads=['prompt'], writes=['response'])
    def my_action(state: State, __tracer: TracerFactory) -> State:
        with __tracer('create_prompt'):
            modified_prompt = _modify_prompt(state["prompt"])
            with __tracer('check_prompt_safety'):
                if _is_unsafe(modified_prompt):
                    modified_prompt = _fix(modified_prompt)
        with __tracer('call_llm', dependencies=['create_prompt']):
            response = _query(prompt=modified_prompt)
        return state.update({'response': response})


This will create spans for the ``_modify_prompt``, ``_fix``, and ``_query`` functions, and log the parameters and return values.
You can opt out of logging parameters or return values and adding a filter to the decorator to exclude certain parameters.

.. _opentelref:

--------------
OpenTelemetry
--------------

While Burr does not support the entire `OpenTelemetry <https://opentelemetry.io/>`_
spec, it does have integrations that allows it to (a) log to OpenTelemetry and (b)
capture OpenTelemetry events with tracking.

These features are currently experimental, but we expect the API to remain largely stable.

Capturing OpenTelemetry events
------------------------------

Burr can capture OpenTelemetry traces/spans that are logged from within a Burr step.
These get tracked in the UI, which can display traces and attributes, as explained above.

To do this, you just have to set the ``use_otel_tracing`` flag on :py:meth:`with_tracker <burr.core.application.ApplicationBuilder.with_tracker>`
function in the ``ApplicationBuilder``. This will automatically capture all OpenTelemetry traces, mixing them with Burr traces. Take the following (contrived)
example:

.. code-block:: python

    from burr.visibility import TracerFactory
    from burr.core import action
    from opentelemetry import trace
    otel_tracer = trace.get_tracer(__name__)

    @action(reads=['prompt'], writes=['response'])
    def my_action(state: State, __tracer: TracerFactory) -> State:
        with __tracer:
            # Burr logging
            __tracer.log_attributes(prompt_length=len(state["prompt"]), prompt=state["prompt"])
            # OpenTelemetry Tracer
            with otel_tracer.start_as_current_span('create_prompt') as span:
                modified_prompt = _modify_prompt(state["prompt"])
                span.set_attributes(dict(modified_prompt=modified_prompt))
            # Back to Burr tracer
            with __tracer('call_llm', dependencies=['create_prompt']):
                response = _query(prompt=modified_prompt)
                t.log_attributes(response=response.message, tokens=response.tokens)
        return state.update({'response': response.message})

    app = (
        ApplicationBuilder()
        .with_actions(my_action, ...)
        .with_state(...)
        .with_transitions(...)
        .with_tracker("local", project="my_project", use_otel_tracing=True)
        .with_entrypoint("prompt", "my_action")
        .build()
    )

While this is contrived, it illustrates that you can mix/match Burr/OpenTelemetry. This is valuable
when you have a Burr action that calls out to a function that is instrumented via OpenTelemetry (
of which there are a host of integrations).

Note that this currently does not support logging remote traces, but we plan to have a
more complete integration in the future.

If you do not enable ``use_otel_tracing``, this will all be a no-op.

Logging to OpenTelemetry
-------------------------

Burr can also log to any OpenTelemetry provider, again enabling mixing/matching of spans. To do this,
you simply need to pass an instance of the :py:class:`OpenTelemetryBridge <burr.integrations.opentelemetry.OpenTelemetryBridge>` to the
:py:meth:`with_hooks <burr.core.application.ApplicationBuilder.with_hooks>` method of the ``ApplicationBuilder``. This will automatically
log all spans to the OpenTelemetry provider of choice (and you are responsible for initializes
it as you see fit).

.. code-block:: python

    from burr.integrations.opentelemetry import OpenTelemetryBridge

    otel_tracer = trace.get_tracer(__name__)
    app = (
        ApplicationBuilder()
        .with_actions(my_action, ...)
        .with_state(...)
        .with_transitions(...)
        .with_hooks(OpenTelemetryBridge(tracer=otel_tracer))
        .with_entrypoint("prompt", "my_action")
        .build()
    )


With this you can log to any OpenTelemetry provider.


Instrumenting libraries
-----------------------

One way to gain observability is to **instrument** a library with OpenTelemetry. This involves importing an object that will automatically patch the library in order to produce and report telemetry (learn more about `autoinstrumentation <https://opentelemetry.io/docs/zero-code/python/>`_). The Python community has implemented `instrumentation for many popular libraries <https://opentelemetry-python-contrib.readthedocs.io/en/latest/>`_ (FastAPI, AWS Lambda, requests, etc.).

This snippet enables automatically logging HTTP requests done via the ``requests`` library:

.. code-block:: python

    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    RequestsInstrumentor().instrument()


This works with both of the integrations above, and simple requires the
``opentelemetry-instrumentation-YYY`` package (where ``YYY`` is the library you want to instrument, openai in this case).


LLM-specific Telemetry
~~~~~~~~~~~~~~~~~~~~~~

`Openllmetry <https://github.com/traceloop/openllmetry/>`_ is a project implementing autoinstrumentation for components of LLM stacks (LLM providers, vector databases, frameworks, etc.). This enables tracking prompts, token counts, temperature, vector search operations, etc.

The following instruments the ``openai`` Python library

.. code-block:: python

    from opentelemetry.instrumentation.openai import OpenAIInstrumentor
    OpenAIInstrumentor().instrument()


Burr's ``init_instruments()``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Burr integration for OpenTelemetry includes the convenience function ``init_instruments()``. You can provide it the names of modules to instrument as strings and it will try to instrument them. This feature has good IDE autocompletion support. Another benefit is the ability to instrument multiple libraries at once.

The following instruments the module ``openai`` (equivalent to the previous snippet) along with ``lancedb`` and ``fastapi``.

.. code-block:: python

    from burr.integrations.opentelemetry import init_instruments
    init_instruments("openai", "lancedb", "fastapi")


Specifying the keyword argument ``init_all=True`` will try to instrument currently imported libraries with the instrumentation packages installed.

You can get the logger to view in detail which library is instrumented.

.. code-block:: python

    import logging
    from burr.integrations.opentelemetry import init_instruments

    logger = logging.getLogger("burr.integrations.opentelemetry")
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG)

    init_instruments(init_all=True)
