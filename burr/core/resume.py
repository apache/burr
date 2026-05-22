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

from typing import Any, Optional

from burr.core.durable import (
    read_journal_from_state,
    read_suspension_from_state,
    supports_durable_storage,
)


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
    if schema_json is None:
        return
    try:
        import jsonschema
    except ImportError:
        return  # validation is best-effort without jsonschema installed
    jsonschema.validate(instance=payload, schema=schema_json)


def _rebuild(persister, graph, app_id, partition_key, record):
    from burr.core.application import ApplicationBuilder
    from burr.core.state import State

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

    Idempotent: resuming an already-resolved suspension is a no-op that returns
    the current state.
    """
    record = _load_suspension(persister, partition_key, app_id, channel)
    if record is None:
        raise ValueError(
            f"No suspension found for app_id={app_id!r}, "
            f"partition_key={partition_key!r}, channel={channel!r}."
        )
    if record.resolved:
        loaded = persister.load(partition_key, app_id)
        return loaded["state"] if loaded else record.state

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
        record.resolved = True  # in-state fallback: best-effort

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
    """Async mirror of resume(). Use with async actions and async persisters."""
    is_async = persister.is_async()
    if is_async:
        record = await persister.load_suspension(partition_key, app_id, channel)
    else:
        record = _load_suspension(persister, partition_key, app_id, channel)
    if record is None:
        raise ValueError(
            f"No suspension found for app_id={app_id!r}, "
            f"partition_key={partition_key!r}, channel={channel!r}."
        )
    if record.resolved:
        if is_async:
            loaded = await persister.load(partition_key, app_id)
        else:
            loaded = persister.load(partition_key, app_id)
        return loaded["state"] if loaded else record.state

    _validate_payload(record.schema_json, payload)

    app = _rebuild(persister, graph, app_id, partition_key, record)
    app._resume_signals = {channel: payload}
    if is_async and supports_durable_storage(persister):
        app._loaded_journal = await persister.load_journal(
            partition_key, app_id, record.sequence_id
        )
    else:
        app._loaded_journal = _load_journal(
            persister, partition_key, app_id, record.sequence_id, record.state
        )
    app._suspended = None

    await app.arun(halt_after=[])

    if supports_durable_storage(persister):
        if is_async:
            await persister.mark_suspension_resolved(record.suspension_id)
        else:
            persister.mark_suspension_resolved(record.suspension_id)
    else:
        record.resolved = True

    return app.state
