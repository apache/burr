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


.. _langfuseintegrationref:

--------
Langfuse
--------

`Langfuse <https://langfuse.com>`_ is an open-source LLM engineering platform with
tracing/observability capabilities. Burr integrates with it through the
OpenTelemetry-native Langfuse Python SDK, building on the
:ref:`opentelemetry integration <opentelintegrationref>`.

Install the integration:

.. code-block:: bash

    pip install "apache-burr[langfuse]"

Then add the bridge as a hook -- credentials are read from the standard
``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``, and ``LANGFUSE_HOST``
environment variables:

.. code-block:: python

    from burr.core import ApplicationBuilder
    from burr.integrations.langfuse import LangfuseBridge

    app = (
        ApplicationBuilder()
        .with_graph(graph)
        .with_entrypoint("prompt")
        .with_hooks(LangfuseBridge())
        .build()
    )
    app.run(halt_after=["response"])  # logs one trace to Langfuse

Each application execution call becomes a Langfuse trace, each step becomes a span
(with state/inputs/results captured as observation input/output), and spans opened
through Burr's :ref:`tracing API <opentelref>` become nested spans. Any additional
OpenTelemetry LLM instrumentation (e.g. ``opentelemetry-instrumentation-openai``)
appears nested within the corresponding Burr step.

See the following resources for more information:

- `Example in the repository <https://github.com/apache/burr/tree/main/examples/integrations/langfuse>`_
- `Langfuse OpenTelemetry docs <https://langfuse.com/integrations/native/opentelemetry>`_

Reference for the various useful methods:

.. autoclass:: burr.integrations.langfuse.LangfuseBridge
    :members:

    .. automethod:: __init__

.. autofunction:: burr.integrations.langfuse.burr_span_export_filter
