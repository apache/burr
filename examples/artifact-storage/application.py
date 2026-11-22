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

"""Demonstrates Burr's artifact/blob store: large values (e.g. documents, images, model
outputs) are written to a backend of your choice -- here, the local filesystem, so this example
needs no cloud credentials -- and only a small, content-addressed ``ArtifactRef`` is kept in
state. A later action reads the artifact back out using that reference.

See the README for how to swap in ``AsyncS3ArtifactStore`` for async applications backed by S3.
"""

import tempfile
from typing import Optional

from burr.core import Application, ApplicationBuilder, ApplicationContext, Result, State, action
from burr.core.artifacts import ArtifactRef, LocalFileSystemArtifactStore


@action(reads=[], writes=["document"])
def write_document(state: State, __context: ApplicationContext, content: bytes) -> State:
    """Writes `content` to the object store and keeps only the resulting reference in state."""
    ref: ArtifactRef = __context.object_store.put_artifact(content, media_type="text/plain")
    print(f"Wrote {ref.size_bytes} bytes to the object store under key '{ref.key}'")
    return state.update(document=ref)


@action(reads=["document"], writes=["recovered_text"])
def read_document(state: State, __context: ApplicationContext) -> State:
    """Reads the artifact back out using the reference stored in state."""
    recovered_bytes = __context.object_store.get_artifact(state["document"])
    return state.update(recovered_text=recovered_bytes.decode("utf-8"))


def application(storage_dir: Optional[str] = None) -> Application:
    """Builds the application.

    :param storage_dir: Directory the :py:class:`LocalFileSystemArtifactStore` writes artifacts
        to. Defaults to a fresh temporary directory so this example has no side effects.
    """
    object_store = LocalFileSystemArtifactStore(storage_dir or tempfile.mkdtemp())
    return (
        ApplicationBuilder()
        .with_actions(
            write_document=write_document,
            read_document=read_document,
            result=Result("recovered_text"),
        )
        .with_transitions(
            ("write_document", "read_document"),
            ("read_document", "result"),
        )
        .with_entrypoint("write_document")
        .with_state()
        .with_object_store(object_store)
        .build()
    )


if __name__ == "__main__":
    app = application()
    app.visualize(
        output_file_path="statemachine", include_conditions=True, include_state=True, format="png"
    )
    original_content = b"This document is too large to keep in state directly."
    action_, result, state = app.run(halt_after=["result"], inputs={"content": original_content})
    print(f"Recovered: {state['recovered_text']!r}")
    assert state["recovered_text"] == original_content.decode("utf-8")
