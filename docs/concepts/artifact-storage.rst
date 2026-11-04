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
you explicitly call :py:meth:`ArtifactRef.read <burr.core.artifacts.ArtifactRef.read>` (or its
async counterpart, :py:meth:`ArtifactRef.aread <burr.core.artifacts.ArtifactRef.aread>`, for an
``AsyncArtifactStore``) when you actually need them.

This is an opt-in mechanism, with two ways to use it:

1. **Explicitly, from actions** -- an action writes the blob and keeps the ref in state (below).
2. **Through serialization** -- a type-based or field-based serializer externalizes the value
   while state is being persisted/tracked, so actions can keep the live value in state (see
   :ref:`artifact-serde`).

Either way, Burr never decides on its own what to store -- your actions or your registered
serializers are always the ones calling ``put_artifact``/``get_artifact``.

A complete, runnable example (using the local filesystem, so it needs no cloud credentials) is
available at `examples/artifact-storage <https://github.com/apache/burr/tree/main/examples/artifact-storage>`_.

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

``put_artifact`` never returns a ref that doesn't describe what's actually stored. If the key
already holds content -- because you've written it before, or because a concurrent writer got
there first -- its digest is checked: identical content is a no-op, anything else raises a
``ValueError``. That has a consequence worth designing for when you pass an explicit ``key``
(rather than relying on content-addressing): reusing it requires identical bytes. If an action
writes non-deterministic output (e.g. an LLM response) under a fixed key and is then retried, or
the application is resumed after a crash and re-runs that action, the new bytes differ and
``put_artifact`` raises. **Use the default, content-addressed keys for non-deterministic
output**, and reserve explicit keys for content that is stable for a given key.

Backends write *create-if-absent* -- an existing object is not overwritten -- so concurrent
writers can't clobber each other: the local backend publishes via a temp file and a hard link,
and :ref:`S3 <s3-artifacts-integration>` uses conditional writes. Concurrent writers of
*different* content under the same explicit key therefore still collide (one wins, the others
get a ``ValueError``); coordinating such writers is up to the caller. Two caveats: on
filesystems without hard links the local backend falls back to a rename, which can replace a
concurrently-written file; and a crash mid-write can leave a ``.tmp-artifact-*`` file in the
store directory, which is safe to delete.

:py:class:`LocalFileSystemArtifactStore <burr.core.artifacts.LocalFileSystemArtifactStore>` writes
are also atomic and reject keys that would resolve outside ``root_dir`` (including through
symlinks), so readers never observe partial files and artifacts can't be written outside the
configured store directory.

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

Unlike ``with_state_persister``, ``with_object_store`` does not add a persister or tracker of its
own -- the store is only used by your actions and by the serializers you register (see
:ref:`artifact-serde`). It's a way to configure and share the store, so you can swap
implementations (local disk in dev, S3 in prod) in one place.

.. note::

    ``__context`` is only injected if it appears in your action's signature -- see
    :ref:`State Persistence <state-persistence>` for more on ``ApplicationContext``.

Using an artifact store from async actions
--------------------------------------------

:py:class:`ArtifactStore <burr.core.artifacts.ArtifactStore>` is synchronous -- calling it from
an async action blocks the event loop for the duration of each ``put``/``get`` (e.g. a network
round-trip to S3). For async applications, use an
:py:class:`AsyncArtifactStore <burr.core.artifacts.AsyncArtifactStore>` instead (e.g.
:py:class:`AsyncS3ArtifactStore <burr.integrations.artifacts.s3.AsyncS3ArtifactStore>`), and
build the application with :py:meth:`abuild <burr.core.application.ApplicationBuilder.abuild>`:

.. code-block:: python

    from burr.core import action, State, ApplicationContext
    from burr.core.artifacts import AsyncArtifactStore
    from burr.integrations.artifacts.s3 import AsyncS3ArtifactStore

    @action(reads=[], writes=["pdf_doc"])
    async def ingest_pdf(state: State, pdf_bytes: bytes, __context: ApplicationContext) -> State:
        store: AsyncArtifactStore = __context.object_store
        ref = await store.put_artifact(pdf_bytes, media_type="application/pdf")
        return state.update(pdf_doc=ref)

    object_store = await AsyncS3ArtifactStore.acreate(bucket="my-bucket")
    app = await (
        ApplicationBuilder()
        .with_actions(ingest_pdf, ...)
        .with_transitions(...)
        .with_state(...)
        .with_entrypoint(...)
        .with_object_store(object_store)
        .abuild()
    )

An async object store can be attached via either :py:meth:`build
<burr.core.application.ApplicationBuilder.build>` or :py:meth:`abuild
<burr.core.application.ApplicationBuilder.abuild>` -- this matters because a sync state
persister/initializer forces ``build()`` even when the application is otherwise run
asynchronously. The store is only rejected once a *synchronous* execution method (``step()``,
``run()``, ``iterate()``, etc.) is actually called, since awaiting it there would require an
event loop; calling an async execution method (``astep()``, ``arun()``, ``aiterate()``) works
regardless of which builder method was used. An ``ArtifactStore`` (sync) can still be used from
``abuild()``-built applications, but, as with a sync state persister, it will block the event
loop while it runs.

:py:meth:`AsyncS3ArtifactStore.acreate <burr.integrations.artifacts.s3.AsyncS3ArtifactStore.acreate>`
opens and owns an ``aiobotocore`` client; use ``async with`` or call ``await
object_store.aclose()`` (idempotent) to release it once you're done. See
:ref:`the S3 integration docs <s3-artifacts-integration>` for an example.

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
    * - AWS S3 (async)
      - :py:class:`AsyncS3ArtifactStore <burr.integrations.artifacts.s3.AsyncS3ArtifactStore>`
      - ``pip install "apache-burr[s3]"`` (includes ``aiobotocore``)

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
        def put(self, data: bytes, key: str) -> Optional[bool]:
            ...  # write data under key unless it already exists -- never overwrite.
            # return True if this call created it, False if it already existed

        def get(self, key: str) -> bytes:
            ...  # raise FileNotFoundError if key does not exist

        def exists(self, key: str) -> bool:
            ...

``put_artifact`` and ``get_artifact`` (digest computation/verification, content-addressed keys)
are provided for free by the base class, so you don't need to reimplement them for a new backend.
If ``put`` can't tell whether it created the object (returning ``None``), ``put_artifact`` verifies
the stored content after the write instead. Override ``digest(key)`` if your backend can report a
stored object's SHA-256 more cheaply than downloading it (the S3 store reads it from object
metadata).

If your backend's I/O is itself async (e.g. a cloud SDK with a native async client), subclass
:py:class:`AsyncArtifactStore <burr.core.artifacts.AsyncArtifactStore>` instead and implement
``async def put/get/exists`` -- it provides the same ``put_artifact``/``get_artifact`` helpers,
just awaited.

If you use :py:class:`RayExecutor <burr.integrations.ray.RayExecutor>` (or any executor that
pickles tasks) for parallel sub-applications, the store is pickled along with them -- make sure
it can be (e.g. drop/rebuild network clients in ``__getstate__``/``__setstate__``).

.. _artifact-serde:

Externalizing values through serialization
-------------------------------------------

Writing artifacts from actions means the action has to know which values are large. Often it's
more natural to keep the live value (a ``PDF``, a dataframe, a long report) in state and decide
*how it is persisted* in one place -- Burr's :doc:`serde` layer. For that, the application's
object store is made available to serializers.

Whenever an application configured with ``with_object_store(...)`` serializes or deserializes
state -- in its state persister, its tracker, while loading state via
:py:meth:`initialize_from <burr.core.application.ApplicationBuilder.initialize_from>`, and in
sub-applications (including ones run on Ray workers) -- every serializer and deserializer receives
a :py:class:`SerializationContext <burr.core.serde.SerializationContext>` as the
``serialization_context`` keyword argument. Burr propagates it; you don't configure it per
persister or tracker. This works for both kinds of serde registration:

.. code-block:: python

    from burr.core import serde, state
    from burr.core.artifacts import ArtifactRef
    from burr.core.serde import SerializationContext

    class PDF:
        """Holds its bytes, or -- once loaded from persisted state -- a ref it reads them from lazily."""

        def __init__(self, data: bytes = None, ref: ArtifactRef = None, store=None):
            self._data, self.ref, self._store = data, ref, store

        @property
        def data(self) -> bytes:
            if self._data is None:
                if self._store is None:
                    raise ValueError("PDF was loaded without an object store")
                self._data = self.ref.read(self._store)
            return self._data

    # type-based: every PDF in state is externalized
    @serde.serialize.register(PDF)
    def serialize_pdf(value: PDF, serialization_context: SerializationContext = None, **kwargs) -> dict:
        # a lazily-loaded PDF already has a ref, so re-saving it doesn't download it
        ref = value.ref or serialization_context.require_object_store().put_artifact(
            value.data, media_type="application/pdf"
        )
        return {serde.KEY: "pdf", "ref": serde.serialize(ref)}

    @serde.deserializer.register("pdf")
    def deserialize_pdf(value: dict, serialization_context: SerializationContext = None, **kwargs) -> PDF:
        # no store needed to load -- only to read the data later
        store = serialization_context.object_store if serialization_context is not None else None
        return PDF(ref=serde.deserialize(value["ref"]), store=store)

    # field-based: only the `attachment` field is externalized, with the same functions
    state.register_field_serde("attachment", serialize_pdf, deserialize_pdf)

A runnable version of this (persisting with SQLite, then resuming) is in
``serde_application.py`` in the
`artifact-storage example <https://github.com/apache/burr/tree/main/examples/artifact-storage>`_.

A few things to know:

* **Return a lazy value with the same interface as the live one.** After resuming, actions read
  whatever the deserializer returned, so it must behave like the original value -- returning a bare
  :py:class:`ArtifactRef <burr.core.artifacts.ArtifactRef>` breaks any action that runs after a
  resume. Hydrating eagerly would work but defeats the purpose, since state is deserialized
  whenever it's loaded (resuming, forking, browsing history). A lazy wrapper that keeps the ref and
  the store (from ``serialization_context``) and loads on first access, as above, does both --
  and since it only needs the store once the data is read, state still loads where there's no
  context (e.g. calling ``persister.load()`` yourself). With an
  :py:class:`AsyncArtifactStore <burr.core.artifacts.AsyncArtifactStore>`, give the wrapper an
  ``async def load()`` (using :py:meth:`ArtifactRef.aread <burr.core.artifacts.ArtifactRef.aread>`)
  instead of a property, and have async actions ``await value.load()``.
* **Serialization happens on every step.** State is re-serialized after each action, so the
  serializer runs each time. Reusing the ref of an already-stored value (as ``serialize_pdf``
  does) avoids re-uploading it; for a live value, content-addressed keys make the repeated write a
  cheap no-op.
* **Sync vs. async.** ``State.serialize``/``State.deserialize`` are synchronous; their async
  counterparts :py:meth:`State.aserialize <burr.core.state.State.aserialize>` /
  :py:meth:`State.adeserialize <burr.core.state.State.adeserialize>` await serializers registered
  as ``async def`` -- which is what you need for an
  :py:class:`AsyncArtifactStore <burr.core.artifacts.AsyncArtifactStore>`. Burr's async persisters
  (``AsyncSQLitePersister``, ``AsyncPostgreSQLPersister``, ``AsyncRedisBasePersister``) use them.
  Synchronous callers -- sync persisters, and the trackers (``LocalTrackingClient``,
  ``S3TrackingClient``) -- raise a clear error if they reach an async serializer, so with an async
  store, track externalized fields through an async persister only, or give them a synchronous
  serializer.
* **Outside of an application** (e.g. calling ``persister.load(...)`` yourself), pass the context
  explicitly -- ``state.serialize(serialization_context=SerializationContext(object_store=store))``
  -- or set it for a block with ``with serde.serialization_context(...):``. Serializers that need a
  store should call ``serialization_context.require_object_store()``, which raises a clear error
  when none is configured.

Interaction with serialization
--------------------------------

``ArtifactRef`` itself is a plain, frozen dataclass registered with :doc:`serde` out of the box, so
it serializes/deserializes as part of normal :py:class:`State <burr.core.state.State>`
(de)serialization with no extra setup required. Deserializing a ref only recreates the small
dataclass -- it never fetches the underlying bytes on its own, so browsing history, forking, or
replaying an application never triggers unexpected I/O against your artifact store.
