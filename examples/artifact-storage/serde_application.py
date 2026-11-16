# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Demonstrates externalizing large values through Burr's serde layer instead of from actions.

Here the actions keep the *live* value (a ``Document``) in state. A type-based serializer --
which receives the application's object store through ``serialization_context`` -- writes the
document's bytes to the store whenever state is persisted, so the persisted state only holds a
small ``ArtifactRef``. Resuming deserializes it into a lazy ``Document`` that only downloads its
content when an action first reads it.
"""

import os
import tempfile
from typing import Optional

from burr.core import Application, ApplicationBuilder, Result, State, action, serde
from burr.core.artifacts import ArtifactRef, LocalFileSystemArtifactStore
from burr.core.persistence import SQLitePersister
from burr.core.serde import SerializationContext


class Document:
    """Stands in for any large value you'd rather not embed in persisted state. Either holds its
    content, or (once loaded from persisted state) a reference it reads the content from lazily."""

    def __init__(self, content: bytes = None, ref: ArtifactRef = None, store=None):
        self._content = content
        self.ref = ref
        self._store = store

    @property
    def content(self) -> bytes:
        if self._content is None:
            if self._store is None:
                raise ValueError(
                    "Document was loaded without an object store, so it can't be read."
                )
            self._content = self.ref.read(self._store)
        return self._content


@serde.serialize.register(Document)
def serialize_document(
    value: Document, serialization_context: SerializationContext = None, **kwargs
) -> dict:
    # a lazily-loaded document already has a ref, so re-saving it doesn't download it
    ref = value.ref or serialization_context.require_object_store().put_artifact(
        value.content, media_type="text/plain"
    )
    return {serde.KEY: "example_document", "ref": serde.serialize(ref)}


@serde.deserializer.register("example_document")
def deserialize_document(
    value: dict, serialization_context: SerializationContext = None, **kwargs
) -> Document:
    # lazy: actions get a Document, but its content is only fetched when first read -- so loading
    # also works without a store (e.g. calling `persister.load()` outside of the application)
    store = serialization_context.object_store if serialization_context is not None else None
    return Document(ref=serde.deserialize(value["ref"]), store=store)


@action(reads=[], writes=["document"])
def receive_document(state: State, content: bytes) -> State:
    return state.update(document=Document(content))


@action(reads=["document"], writes=["word_count"])
def count_words(state: State) -> State:
    return state.update(word_count=len(state["document"].content.split()))


def application(
    storage_dir: str, app_id: str = "serde-example", resume: bool = False
) -> Application:
    """Builds the application, persisting state to SQLite and artifacts to ``storage_dir``.

    :param storage_dir: Directory holding both the SQLite database and the artifact store.
    :param app_id: Application ID to persist under / resume.
    :param resume: Whether to resume ``app_id`` from its persisted state.
    """
    persister = SQLitePersister.from_values(db_path=os.path.join(storage_dir, "state.db"))
    persister.initialize()
    builder = (
        ApplicationBuilder()
        .with_actions(receive_document, count_words, result=Result("word_count"))
        .with_transitions(("receive_document", "count_words"), ("count_words", "result"))
        .with_identifiers(app_id=app_id)
        .with_state_persister(persister)
        .with_object_store(LocalFileSystemArtifactStore(os.path.join(storage_dir, "artifacts")))
    )
    if resume:
        builder = builder.initialize_from(
            persister,
            resume_at_next_action=True,
            default_state={},
            default_entrypoint="receive_document",
        )
    else:
        builder = builder.with_entrypoint("receive_document")
    return builder.build()


def main(storage_dir: Optional[str] = None) -> None:
    storage_dir = storage_dir or tempfile.mkdtemp()
    content = b"A document far too large to keep embedded in persisted state. " * 1000

    # run only the first step, as if the process stopped there
    application(storage_dir).step(inputs={"content": content})

    resumed = application(storage_dir, resume=True)
    document = resumed.state["document"]
    print(f"Resumed with a lazy Document referencing {document.ref.size_bytes} bytes")

    *_, state = resumed.run(halt_after=["result"])  # count_words reads the content here
    print(f"Word count: {state['word_count']}")
    assert state["word_count"] == len(content.split())


if __name__ == "__main__":
    main()
