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

Welcome to the Apache Burr Ecosystem page! This page showcases integrations, examples, and resources to help you build better applications with Burr.

.. note::
   This page is a work in progress. If you have an integration or example you'd like to share, please `open a PR <https://github.com/apache/burr/pulls>`_!

---------------------
🚀 Interactive Tutorials
---------------------

* `Burr Examples <https://github.com/apache/burr/tree/main/examples>`_
  Explore a wide range of examples demonstrating Burr's capabilities, from simple chatbots to complex multi-agent systems.

---------------------
Built-in Integrations
---------------------

Burr integrates deeply with the Python data and AI ecosystem. Here are some of the key integrations available in our `examples` directory.

LLM & AI Frameworks
-------------------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Example
   * - **OpenAI**
     - Build agents using OpenAI's powerful models.
     - `OpenAI Examples <https://github.com/apache/burr/tree/main/examples/openai-compatible-agent>`_
   * - **Haystack**
     - Build end-to-end NLP pipelines.
     - `Haystack Integration <https://github.com/apache/burr/tree/main/examples/haystack-integration>`_
   * - **Instructor**
     - Structured outputs for LLMs.
     - `Instructor Examples <https://github.com/apache/burr/tree/main/examples/instructor-gemini-flash>`_

Orchestration & Data
--------------------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Example
   * - **Hamilton**
     - Define dataflows for modular, testable applications.
     - `Hamilton Integration <https://github.com/apache/burr/tree/main/examples/hamilton-integration>`_
   * - **Ray**
     - Scale your Burr applications with distributed computing.
     - `Ray Examples <https://github.com/apache/burr/tree/main/examples/ray>`_

Web & API
---------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Example
   * - **FastAPI**
     - Serve your Burr agents as high-performance APIs.
     - `FastAPI Streaming <https://github.com/apache/burr/tree/main/examples/streaming-fastapi>`_
   * - **Streamlit**
     - Build interactive web apps for your agents.
     - `Streamlit Examples <https://github.com/apache/burr/tree/main/examples/demo_react_app>`_

Databases & Vector Stores
-------------------------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Example
   * - **LanceDB**
     - Serverless vector database for RAG applications.
     - `RAG with LanceDB <https://github.com/apache/burr/tree/main/examples/rag-lancedb-ingestion>`_
   * - **Qdrant**
     - Vector similarity search engine.
     - `Qdrant Examples <https://github.com/apache/burr/tree/main/examples/conversational-rag>`_

Observability
-------------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Integration
     - Description
     - Example
   * - **OpenTelemetry**
     - Instrument your applications for observability.
     - `OpenTelemetry Integration <https://github.com/apache/burr/tree/main/examples/opentelemetry>`_
