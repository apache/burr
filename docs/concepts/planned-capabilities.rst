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


==================
Roadmap and Status
==================

This page is a status report on notable Apache Burr capabilities, accurate as of October 2026.
It records where each item stands -- shipped, in review, under discussion, or planned -- rather than
making commitments or ranking priorities. Work happens in the open: proposals and design discussions
go to the ``dev@burr.apache.org`` mailing list, and code goes through pull requests on
`GitHub <https://github.com/apache/burr>`_. If something you need is missing, open an issue or start
a thread.

-------
Shipped
-------

Available in the current release.

* **State persistence and rehydration.** Save and reload application state with
  ``ApplicationBuilder.initialize_from`` and the persister API. Built-in persisters cover in-memory,
  SQLite, PostgreSQL, MongoDB, and Redis, with async variants. See
  `State Persistence <https://burr.apache.org/concepts/state-persistence/>`_.
* **Annotations in the tracking UI.** Annotate steps and spans of a run from the Burr UI; data lives
  alongside the tracked application. See `Tracking <https://burr.apache.org/concepts/tracking/>`_
  (introduced in `#383 <https://github.com/apache/burr/pull/383>`_).
* **Restricted condition expressions.** ``Condition.safe_expr`` evaluates transition expressions under
  an allowlisted AST grammar, for conditions that come from untrusted sources. See
  `Conditions/Transitions <https://burr.apache.org/reference/conditions/>`_
  (`#820 <https://github.com/apache/burr/pull/820>`_).
* **Integrations.** Hamilton, Haystack, LangChain, Langfuse, OpenTelemetry (including Traceloop),
  Pydantic, Ray, Amazon Bedrock, and Streamlit. See
  `Integrations <https://burr.apache.org/reference/integrations/>`_.
* **Dark mode in the UI.** Follows the system preference with a manual toggle
  (`#830 <https://github.com/apache/burr/pull/830>`_).
* **Security policy.** A published reporting process and security model in
  `SECURITY.md <https://github.com/apache/burr/blob/main/SECURITY.md>`_
  (`#944 <https://github.com/apache/burr/pull/944>`_).

---------
In review
---------

Open pull requests. Listing here means the code exists and is being reviewed, not that it will merge
as-is.

* **Exception transitions** via ``on_error`` capture and wildcard routing --
  `#796 <https://github.com/apache/burr/pull/796>`_ (tracks
  `issue #30 <https://github.com/apache/burr/issues/30>`_; this supersedes the earlier
  ``error(APIException)`` sketch that used to live on this page).
* **Durable execution** (suspend/resume with a durable journal on the context) --
  `#786 <https://github.com/apache/burr/pull/786>`_; see the design discussion below.
* **Visual builder and workspace mode** in the Burr UI --
  `#687 <https://github.com/apache/burr/pull/687>`_.
* **Claude Code skill** for working on Burr applications --
  `#644 <https://github.com/apache/burr/pull/644>`_.
* **Artifact/blob store** for large state values --
  `#931 <https://github.com/apache/burr/pull/931>`_.
* **Lower-level parallel streaming** -- `#836 <https://github.com/apache/burr/pull/836>`_.
* **Mermaid graph visualization** -- `#861 <https://github.com/apache/burr/pull/861>`_.
* **Aerospike persister** -- `#936 <https://github.com/apache/burr/pull/936>`_.
* **Google Sheets persister** -- `#932 <https://github.com/apache/burr/pull/932>`_.
* ``Application.get_prior_action`` -- `#943 <https://github.com/apache/burr/pull/943>`_.
* **OrcaRouter agent example** -- `#896 <https://github.com/apache/burr/pull/896>`_.
* **TypeScript implementation** of the core state machine --
  `#728 <https://github.com/apache/burr/pull/728>`_.
* **LiteLLM AI gateway integration** -- `#803 <https://github.com/apache/burr/pull/803>`_
  (closed by inactivity on 2026-10-05 after the author added the requested end-to-end example;
  revivable).

----------------
Under discussion
----------------

Design threads on ``dev@burr.apache.org`` and open issues without an implementation yet.

* **Durable execution design** --
  `[DISCUSS] Durable execution in Burr <https://lists.apache.org/thread/v9nrtms7nq5noqj2ottw0r0tntohl8s5>`_
  (May--October 2026); the implementation proposal is `#786`_ above.
* **Builder direction** (code-picture-code round-tripping, Pyodide, roadmap) --
  `[DISCUSS] Builder direction <https://lists.apache.org/thread/l9y4nk98wtn2rhpj9xgxszpbvq4psh7c>`_
  and the earlier
  `[discuss] Graph builder UI <https://lists.apache.org/thread/hst35owhcl8swv967rxlh9tpx75gwlrq>`_
  (March 2026); related to `#687`_ above.
* **Google Sheets persister design** --
  `[DISCUSS] Google Sheets Persister design <https://lists.apache.org/thread/z6rmcsqb5b8t1o80z64cmnok6r6r23yy>`_
  and `issue #213 <https://github.com/apache/burr/issues/213>`_; related to `#932`_ above.
* **Interceptor lifecycle hook** --
  `[discuss] adding interceptor lifecycle hook <https://lists.apache.org/thread/k4sq37opkmx0pywp40kqwqkc7x3yyvgn>`_
  (November 2025, no implementation yet).
* **Exception transitions** -- `issue #30`_ remains open while `#796`_ is reviewed.

-------
Planned
-------

Intentions carried over from the previous version of this page that have not shipped and have no open
pull request. No dates are attached.

* **Build-time graph validation.** Walk the graph at build time and flag impossible situations, such as
  an action that reads a state field no action writes and no initial state provides.
* **Evaluation on annotations.** Metrics, custom callbacks, and LLM-as-judge over annotated runs, plus
  SDK support for programmatic annotation, export, and search.
* **FastAPI integration** for serving Burr applications without hand-writing the REST layer.
* **More storage backends** beyond the persisters listed above.
