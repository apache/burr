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

=========
Ecosystem
=========

Welcome to the Apache Burr Ecosystem page. This page lists all available integrations with documentation and example links.

.. note::
   This page is a work in progress. If you have an integration or example you'd like to share, please `open a PR <https://github.com/apache/burr/pulls>`_!

----

LLM & AI Frameworks
--------------------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Documentation
   * - **OpenAI**
     - Use OpenAI models (and any OpenAI API-compatible server) inside Burr actions.
     - `Example <https://github.com/apache/burr/tree/main/examples/openai-compatible-agent>`__
   * - **LangChain / LCEL**
     - Use LangChain chains and runnables as Burr actions. Includes a custom serialization plugin to persist LangChain objects in state.
     - :doc:`Reference <reference/integrations/langchain>` |
       `Multi-agent example <https://github.com/apache/burr/tree/main/examples/multi-agent-collaboration>`__ |
       `Custom serde example <https://github.com/apache/burr/tree/main/examples/custom-serde>`__
   * - **Haystack**
     - Wrap Haystack ``Component`` objects as Burr ``Action`` using ``HaystackAction``, or convert an entire Haystack pipeline to a Burr graph.
     - :doc:`Reference <reference/integrations/haystack>` |
       `Example <https://github.com/apache/burr/tree/main/examples/haystack-integration>`__
   * - **Instructor**
     - Get structured outputs from LLMs via the Instructor library inside Burr actions.
     - `Example <https://github.com/apache/burr/tree/main/examples/instructor-gemini-flash>`__

----

Orchestration & Dataflows
--------------------------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Documentation
   * - **Hamilton**
     - Embed Hamilton dataflows as Burr actions using the ``Hamilton`` action construct and helper functions ``from_state``, ``from_value``, ``update_state``, and ``append_state``.
     - :doc:`Reference <reference/integrations/hamilton>` |
       `Example <https://github.com/apache/burr/tree/main/examples/hamilton-integration>`__ |
       `Multi-agent example <https://github.com/apache/burr/tree/main/examples/integrations/hamilton>`__

----

Distributed Computing
---------------------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Documentation
   * - **Ray**
     - Run parallel Burr sub-applications on a Ray cluster using ``RayExecutor``.
     - :doc:`Reference <reference/integrations/ray>` |
       `Example <https://github.com/apache/burr/tree/main/examples/ray>`__

----

State Persistence
-----------------

Burr provides pluggable state persisters so your application state survives restarts and scales across services.
See :doc:`reference/persister` for the full API reference.

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Documentation
   * - **SQLite**
     - Lightweight file-based persistence. Ships with Burr (no extra install). Sync and async variants available.
     - :doc:`Reference <reference/persister>`
   * - **PostgreSQL**
     - Production-grade relational database persistence via ``psycopg2`` (sync) and ``asyncpg`` (async).
     - :doc:`Reference <reference/persister>`
   * - **Redis**
     - In-memory key-value store persistence. Sync and async variants available.
     - :doc:`Reference <reference/persister>`
   * - **MongoDB**
     - Document-store persistence via ``pymongo``.
     - :doc:`Reference <reference/persister>`

----

Vector Stores
-------------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Documentation
   * - **LanceDB**
     - Serverless, embedded vector database. Ideal for local or cloud RAG pipelines.
     - `RAG example <https://github.com/apache/burr/tree/main/examples/rag-lancedb-ingestion>`__
   * - **Qdrant**
     - Scalable vector similarity search engine for conversational RAG.
     - `Conversational RAG example <https://github.com/apache/burr/tree/main/examples/conversational-rag>`__

----

Observability
-------------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Documentation
   * - **OpenTelemetry**
     - Export Burr traces to any OpenTelemetry-compatible backend. Burr can also capture traces emitted *within* an action and forward them.
     - :doc:`Reference <reference/integrations/opentelemetry>` |
       `Example <https://github.com/apache/burr/tree/main/examples/opentelemetry>`__ |
       `Blog post <https://blog.dagworks.io/p/9ef2488a-ff8a-4feb-b37f-1d9a781068ac/>`__
   * - **Traceloop / OpenLLMetry**
     - AI-focused OpenTelemetry vendor. Use Traceloop's ``openllmetry`` library together with Burr's OpenTelemetry bridge for LLM-aware tracing.
     - :doc:`Reference <reference/integrations/traceloop>` |
       `Example <https://github.com/apache/burr/tree/main/examples/opentelemetry>`__ |
       `Blog post <https://blog.dagworks.io/p/9ef2488a-ff8a-4feb-b37f-1d9a781068ac/>`__

----

Data Validation & Serialization
--------------------------------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Documentation
   * - **Pydantic**
     - Type-check Burr state fields with Pydantic models, and serialize/deserialize state using Pydantic's serde support.
     - :doc:`Reference <reference/integrations/pydantic>` |
       :doc:`State typing docs <concepts/state-typing>` |
       :doc:`Serde docs <concepts/serde>`
   * - **LangChain serde**
     - Custom serialization plugin to persist LangChain objects (messages, chains, etc.) in Burr state.
     - :doc:`Serde docs <concepts/serde>` |
       `Example <https://github.com/apache/burr/tree/main/examples/custom-serde>`__
   * - **Pandas serde**
     - Custom serialization plugin to persist Pandas ``DataFrame`` objects in Burr state.
     - :doc:`Serde docs <concepts/serde>`
   * - **Pickle serde**
     - Fallback serialization plugin using Python's built-in ``pickle`` for arbitrary objects.
     - :doc:`Serde docs <concepts/serde>`

----

Web & API
---------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Documentation
   * - **FastAPI**
     - Serve Burr applications over HTTP with streaming support via FastAPI and server-sent events (SSE).
     - `Streaming FastAPI example <https://github.com/apache/burr/tree/main/examples/streaming-fastapi>`__ |
       `Web server example <https://github.com/apache/burr/tree/main/examples/web-server>`__
   * - **Streamlit**
     - Debug and visualize Burr state machines interactively in Streamlit apps using utility functions such as ``render_state_machine`` and ``render_explorer``.
     - :doc:`Reference <reference/integrations/streamlit>` |
       `Example <https://github.com/apache/burr/tree/main/examples/simple-chatbot-intro>`__
