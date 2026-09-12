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


================
Artifact Storage
================

.. _artifact-storage:

.. note::

    Burr comes with an optional object/blob storage abstraction for large values (files,
    images, dataframes, model weights, etc...) that you don't want to embed directly in
    :py:class:`State <burr.core.state.State>`. This is separate from :doc:`state-persistence` --
    it's for the *values* your actions produce/consume, not the state machine's bookkeeping.

TL;DR
-----

:py:class:`State <burr.core.state.State>` is fully re-serialized to your persister/tracker
after every action. If you put a large binary blob (a PDF, an image, a big dataframe) directly
in state, that entire blob gets re-written on every subsequent step, even if it never changes.

Burr's artifact storage API solves this by giving you a place to write the blob once
(an :py:class:`ArtifactStore <burr.core.artifacts.ArtifactStore>`), and a small,
content-addressed handle to keep in state instead (an
:py:class:`ArtifactRef <burr.core.artifacts.ArtifactRef>`). The ref serializes/deserializes like
any other state value, but loading it back does **not** eagerly fetch the underlying bytes --
you explicitly call :py:meth:`ArtifactRef.read <burr.core.artifacts.ArtifactRef.read>` (or
``store.get_artifact(ref)``) when you actually need them.

This is an opt-in, explicit mechanism. Burr never reads from or writes to an artifact store on
its own -- your actions are always the ones calling ``put_artifact``/``get_artifact``.

Why not just put the bytes in State?
-------------------------------------

Consider an action that ingests an uploaded PDF and a later action that summarizes it:

.. code-block:: python

    @action(reads=[], writes=["pdf_bytes"])
    def ingest_pdf(state: State, pdf_bytes: bytes) -> State:
        return state.update(pdf_bytes=pdf_bytes)  # the whole PDF is now in State

    @action(reads=["pdf_bytes"], writes=["summary"])
    def summarize(state: State) -> State:
        summary = call_llm(state["pdf_bytes"])
        return state.update(summary=summary)

Every time ``State`` is persisted or tracked after this point (including for actions that have
nothing to do with the PDF), the full PDF bytes are re-serialized along with everything else.
This gets expensive quickly, and it also means large binary data ends up embedded in your
persistence layer and shown as raw JSON in the tracking UI.

Storing an artifact reference instead
--------------------------------------

Use an :py:class:`ArtifactStore <burr.core.artifacts.ArtifactStore>` to store the blob once, and
keep only the small :py:class:`ArtifactRef <burr.core.artifacts.ArtifactRef>` -- a key, size,
SHA-256 digest, and optional media type -- in state:

.. code-block:: python

    from burr.core import action, State, ApplicationContext
    from burr.core.artifacts import ArtifactStore

    @action(reads=[], writes=["pdf_doc"])
    def ingest_pdf(state: State, pdf_bytes: bytes, __context: ApplicationContext) -> State:
        store: ArtifactStore = __context.object_store
        ref = store.put_artifact(pdf_bytes, media_type="application/pdf")
        return state.update(pdf_doc=ref)  # only the small ref is in State now

    @action(reads=["pdf_doc"], writes=["summary"])
    def summarize(state: State, __context: ApplicationContext) -> State:
        store: ArtifactStore = __context.object_store
        pdf_bytes = state["pdf_doc"].read(store)  # explicit, lazy fetch
        summary = call_llm(pdf_bytes)
        return state.update(summary=summary)

``put_artifact`` computes a SHA-256 digest of the data and, unless you pass an explicit ``key``,
uses that digest as the storage key. This makes writes idempotent and content-addressed --
storing the same bytes twice (even across app runs) is a no-op, so you get de-duplication for
free without any bookkeeping of your own.

``get_artifact`` (and ``ArtifactRef.read``) re-computes the digest of whatever comes back from
the store and compares it to ``ref.digest`` by default, raising a ``ValueError`` if they don't
match -- this catches corrupted or overwritten data early rather than silently returning bad
bytes.

Making a store available to actions
------------------------------------

Rather than having every action construct or import its own store, configure one on the
:py:class:`ApplicationBuilder <burr.core.application.ApplicationBuilder>` with
:py:meth:`with_object_store <burr.core.application.ApplicationBuilder.with_object_store>`. It's
then available to any action via :py:class:`ApplicationContext <burr.core.application.ApplicationContext>`
(``__context.object_store``), the same way :py:meth:`with_state_persister <burr.core.application.ApplicationBuilder.with_state_persister>`
and :py:meth:`with_tracker <burr.core.application.ApplicationBuilder.with_tracker>` expose the
persister/tracker.

.. code-block:: python

    from burr.core import ApplicationBuilder
    from burr.core.artifacts import LocalFileSystemArtifactStore

    app = (
        ApplicationBuilder()
        .with_actions(ingest_pdf, summarize, ...)
        .with_transitions(...)
        .with_state(...)
        .with_entrypoint(...)
        .with_object_store(LocalFileSystemArtifactStore(root_dir="./blobs"))
        .build()
    )

Unlike ``with_state_persister``, ``with_object_store`` does not register a lifecycle hook --
Burr never calls into the store itself. It's purely a way to configure and share the store, so
you can swap implementations (local disk in dev, S3 in prod) in one place.

.. note::

    ``__context`` is only injected if it appears in your action's signature -- see
    :ref:`State Persistence <state-persistence>` for more on ``ApplicationContext``.

Supported Backends
-------------------

.. list-table:: Burr Implemented Artifact Stores
    :header-rows: 1
    :widths: auto

    * - Backend
      - Class
      - Extra dependency
    * - Local disk
      - :py:class:`LocalFileSystemArtifactStore <burr.core.artifacts.LocalFileSystemArtifactStore>`
      - none (stdlib only)
    * - AWS S3
      - :py:class:`S3ArtifactStore <burr.integrations.artifacts.s3.S3ArtifactStore>`
      - ``pip install "apache-burr[s3]"``

See :ref:`the API reference <artifactsref>` for full details, and
:ref:`the S3 integration reference <s3-artifacts-integration>` for setup instructions.

Implementing your own backend
------------------------------

To back artifacts with a different store (GCS, Azure Blob Storage, a database, ...),
subclass :py:class:`ArtifactStore <burr.core.artifacts.ArtifactStore>` and implement three
methods -- ``put``, ``get``, and ``exists``:

.. code-block:: python

    from burr.core.artifacts import ArtifactStore

    class MyCustomArtifactStore(ArtifactStore):
        def put(self, data: bytes, key: str) -> None:
            ...  # write data under key -- must be idempotent

        def get(self, key: str) -> bytes:
            ...  # raise FileNotFoundError if key does not exist

        def exists(self, key: str) -> bool:
            ...

``put_artifact`` and ``get_artifact`` (digest computation/verification, content-addressed keys)
are provided for free by the base class, so you don't need to reimplement them for a new backend.

Interaction with serialization
--------------------------------

``ArtifactRef`` is a plain, frozen dataclass registered with :doc:`serde` out of the box, so it
serializes/deserializes as part of normal :py:class:`State <burr.core.state.State>` (de)serialization
with no extra setup required. Deserializing a ref only recreates the small dataclass -- it never
fetches the underlying bytes on its own, so browsing history, forking, or replaying an
application never triggers unexpected I/O against your artifact store.
