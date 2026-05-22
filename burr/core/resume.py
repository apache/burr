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

"""Top-level resume helpers for durable execution."""

import warnings
from typing import Any, Optional

from burr.core.durable import (
    read_journal_from_state,
    read_suspension_from_state,
    supports_durable_storage,
)
from burr.core.state import State


def _load_suspension(persister, partition_key, app_id, channel):
    if supports_durable_storage(persister):
        return persister.load_suspension(partition_key, app_id, channel)
    loaded = persister.load(partition_key, app_id)
    if loaded is None:
        return None
    return read_suspension_from_state(loaded["state"], channel)


def _load_journal(persister, partition_key, app_id, sequence_id, state):
    if supports_durable_storage(persister):
        return persister.load_journal(partition_key, app_id, sequence_id)
    return read_journal_from_state(state)


def _validate_payload(schema_json, payload):
    """Validate *payload* against *schema_json* using jsonschema.

    Schema validation requires the optional ``jsonschema`` package. When it is
    absent, validation is skipped and a warning is emitted.
    """
    if schema_json is None:
        return
    try:
        import jsonschema
    except ImportError:
        warnings.warn(
            "jsonschema is not installed; skipping resume payload schema validation. "
            "Install jsonschema to enable validation.",
            stacklevel=3,
        )
        return
    jsonschema.validate(instance=payload, schema=schema_json)


def _rebuild(persister, graph, app_id, partition_key, record):
    from burr.core.application import ApplicationBuilder

    app = (
        ApplicationBuilder()
        .with_graph(graph)
        .with_identifiers(app_id=app_id, partition_key=partition_key)
        .with_entrypoint(record.position)
        .with_state(State(record.state))
        .with_state_persister(persister)
        .build()
    )
    return app


def resume(
    *,
    persister,
    graph,
    app_id: str,
    partition_key: Optional[str],
    channel: str,
    payload: Any,
):
    """Resume a suspended run by delivering ``payload`` to ``channel``.

    Reloads the suspension, rebuilds the Application from ``graph`` + ``persister``,
    re-runs the suspended action from the top (durable sub-steps replay from the
    journal, ``suspend(channel)`` returns ``payload``), and runs to the next halt,
    suspend, or completion.

    Idempotency: resuming an already-resolved suspension is an idempotent no-op for
    persisters with durable storage (those implementing ``save_suspension`` /
    ``load_suspension`` / ``mark_suspension_resolved``). For persisters without
    durable storage, the suspension lives in ``state['__burr_durable__']`` and is
    overwritten as the resumed run progresses; a second ``resume()`` call after the
    first completes raises ``ValueError``.
    """
    record = _load_suspension(persister, partition_key, app_id, channel)
    if record is None:
        raise ValueError(
            f"No suspension found for app_id={app_id!r} "
            f"(never suspended, or already resolved on a persister without durable storage)."
        )
    if record.resolved:
        loaded = persister.load(partition_key, app_id)
        return loaded["state"] if loaded else State(record.state)

    _validate_payload(record.schema_json, payload)

    app = _rebuild(persister, graph, app_id, partition_key, record)
    app._resume_signals = {channel: payload}
    app._loaded_journal = _load_journal(
        persister, partition_key, app_id, record.sequence_id, record.state
    )
    app._suspended = None

    app.run(halt_after=[])  # run to completion or the next suspend

    if supports_durable_storage(persister):
        persister.mark_suspension_resolved(record.suspension_id)
    else:
        # In-state fallback does not durably mark suspensions resolved; a second resume will raise (see docstring).
        pass

    return app.state


async def aresume(
    *,
    persister,
    graph,
    app_id: str,
    partition_key: Optional[str],
    channel: str,
    payload: Any,
):
    """Resume a suspended run by delivering ``payload`` to ``channel``.

    Runs the async action loop (``await app.arun(...)``), so async actions are
    fully supported. Requires a **sync** persister in this release; passing an
    async persister raises :exc:`NotImplementedError`. Full async-persister
    support is deferred to a later milestone.

    :param persister: A sync state persister (durable or non-durable). Async
        persisters are not supported in this release and raise
        :exc:`NotImplementedError`.
    :param graph: The :class:`~burr.core.graph.Graph` to rebuild the application.
    :param app_id: Identifier of the application run to resume.
    :param partition_key: Partition key used when the run was persisted.
    :param channel: Name of the suspension channel to deliver ``payload`` to.
    :param payload: Value returned by ``suspend(channel)`` inside the action.

    **Idempotency:**

    * *Durable persisters* -- resuming an already-resolved suspension is an
      idempotent no-op: the call returns the latest persisted state unchanged.
    * *Sync non-durable persisters* -- the suspension lives in
      ``state['__burr_durable__']`` and is overwritten as the resumed run
      progresses. A second ``aresume()`` call after the first completes raises
      :exc:`ValueError`.
    """
    if persister.is_async():
        raise NotImplementedError(
            "aresume() does not support async persisters in this release; "
            "use a sync persister (durable or non-durable). Async actions are "
            "still supported with a sync persister."
        )
    record = _load_suspension(persister, partition_key, app_id, channel)
    if record is None:
        raise ValueError(
            f"No suspension found for app_id={app_id!r} "
            f"(never suspended, or already resolved on a persister without durable storage)."
        )
    if record.resolved:
        loaded = persister.load(partition_key, app_id)
        return loaded["state"] if loaded else State(record.state)

    _validate_payload(record.schema_json, payload)

    app = _rebuild(persister, graph, app_id, partition_key, record)
    app._resume_signals = {channel: payload}
    app._loaded_journal = _load_journal(
        persister, partition_key, app_id, record.sequence_id, record.state
    )
    app._suspended = None

    await app.arun(halt_after=[])

    if supports_durable_storage(persister):
        persister.mark_suspension_resolved(record.suspension_id)
    else:
        # In-state fallback does not durably mark suspensions resolved; a second resume will raise (see docstring).
        pass

    return app.state
