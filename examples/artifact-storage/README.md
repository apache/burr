<!--
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
-->

# Artifact / object storage

This example shows how to use Burr's artifact (blob) store to keep large values -- documents,
images, model outputs, etc. -- out of `State` directly. Instead, an action writes the bytes to
a store of your choice and keeps only a small, content-addressed `ArtifactRef` in state; a later
action reads the bytes back out using that reference.

This keeps `State` (which gets serialized/persisted/tracked) small and fast, while the actual
payload lives in whatever backend makes sense for your deployment -- local disk for development,
S3 (or another object store) in production.

## Prerequisites
```bash
pip install -r requirements.txt
```

## Running the demo
```bash
python application.py
```

or

```bash
pip install jupyter
jupyter notebook
```

and running the notebook.

## Explanation

`application.py` configures a `LocalFileSystemArtifactStore` (stdlib-only, so this example needs
no cloud credentials) via `ApplicationBuilder.with_object_store()`. The store is exposed to every
action through `ApplicationContext.object_store`:

1. `write_document` calls `__context.object_store.put_artifact(content)`, which writes `content`
   to the store and returns an `ArtifactRef` (key + digest + size, no raw bytes) -- that's what
   gets saved into state, not `content` itself.
2. `read_document` calls `__context.object_store.get_artifact(state["document"])` to fetch the
   bytes back out, verifying them against the digest recorded in the `ArtifactRef`.
3. Running the graph end-to-end shows the recovered text matches what was originally written.

See [the artifact storage concept docs](https://burr.apache.org/concepts/artifact-storage/) and
[the artifacts API reference](https://burr.apache.org/reference/artifacts/) for more detail,
including collision/atomicity semantics for the local backend.

### Externalizing values through serde (`serde_application.py`)

`application.py` writes the artifact explicitly from an action. Alternatively, actions can keep the
*live* value in state and let a serializer externalize it whenever state is persisted --
`serde_application.py` shows this:

1. A `Document` type is registered with `burr.core.serde`. Its serializer receives the
   application's object store through the `serialization_context` keyword argument, writes the
   content with `put_artifact`, and returns only the small reference.
2. The application persists state with a `SQLitePersister` -- so what's in the database is the
   reference, not the document.
3. The script stops after the first step and resumes (`initialize_from`). The deserializer
   returns a lazy `Document` -- same interface as the live one -- so `count_words` works
   unchanged, and the content is only downloaded when it first reads it.

```bash
python serde_application.py
```

The same works for field-level serde (`register_field_serde`). See
[the concept docs](https://burr.apache.org/concepts/artifact-storage/#artifact-serde) for the
sync/async rules.

### Async applications and S3

This example sticks to the synchronous, local-filesystem store to avoid requiring AWS
credentials. If you're building an async application (one built with
`ApplicationBuilder.abuild()`), use
[`AsyncS3ArtifactStore`](https://burr.apache.org/reference/integrations/s3/) instead of a
synchronous store -- it's backed by `aiobotocore` so it won't block the event loop. It owns an
underlying client that should be cleaned up with `async with`:

```python
async with await AsyncS3ArtifactStore.acreate(bucket="my-bucket") as object_store:
    app = await (
        ApplicationBuilder()
        .with_object_store(object_store)
        ...
        .abuild()
    )
    await app.arun(...)
# the underlying aiobotocore client is closed automatically here, even on exception.
```
