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

"""Primitives for durable execution: the suspend control-flow signal, the
determinism error, and the records persisted to support resume."""

import dataclasses
from typing import Any, Dict, Optional


class _Suspended(BaseException):
    """Internal control-flow signal raised by ``ApplicationContext.suspend()``.

    Subclasses ``BaseException`` (not ``Exception``) on purpose: a user
    ``try/except Exception`` wrapping an LLM/IO call inside an action must NOT
    swallow it. The run loop catches it explicitly. It is never an error and is
    never logged or persisted as a failure.
    """

    def __init__(
        self,
        channel: str,
        schema_json: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ):
        self.channel = channel
        self.schema_json = schema_json
        self.metadata = metadata
        super().__init__(f"Execution suspended on channel '{channel}'")


class DeterminismError(Exception):
    """Raised on resume when ``ctx.durable()`` calls do not replay in the same
    order, or with the same keys, as the recorded journal. This converts a
    silent footgun (lost re-execution or stale cache) into a loud failure."""


@dataclasses.dataclass
class SuspensionRecord:
    """Everything needed to resume a suspended run. Persisted when an action
    calls ``suspend()``. ``metadata``, ``inputs`` and ``state`` are serialized
    through ``burr.core.serde``."""

    suspension_id: str
    partition_key: Optional[str]
    app_id: str
    sequence_id: int
    position: str  # name of the suspended action
    channel: str
    schema_json: Optional[dict]
    metadata: Optional[dict]
    inputs: Dict[str, Any]
    state: Dict[str, Any]  # entry state of the suspended action
    created_at: str
    resolved: bool = False


@dataclasses.dataclass
class JournalEntry:
    """One memoized ``ctx.durable()`` sub-step. ``result`` is serialized through
    ``burr.core.serde``."""

    partition_key: Optional[str]
    app_id: str
    sequence_id: int
    step_key: str
    call_index: int
    result: Any


def supports_durable_storage(persister) -> bool:
    """True if the persister overrides the durable-storage methods. When False,
    the Application stores suspensions and journal entries inside the State."""
    from burr.core.persistence import (
        AsyncBaseStatePersister,
        BaseStatePersister,
    )

    base = AsyncBaseStatePersister if persister.is_async() else BaseStatePersister
    return type(persister).save_suspension is not base.save_suspension


# --- In-state fallback codec --------------------------------------------------
# When the persister has no dedicated storage, suspensions and journal entries
# ride inside a reserved State namespace, which the existing PersisterHook saves.

DURABLE_STATE_KEY = "__burr_durable__"


def write_suspension_into_state(state, record: "SuspensionRecord"):
    """Return a new State with the suspension record embedded."""
    bucket = dict(state.get(DURABLE_STATE_KEY, {}) or {})
    bucket["suspension"] = dataclasses.asdict(record)
    return state.update(**{DURABLE_STATE_KEY: bucket})


def read_suspension_from_state(state, channel: str) -> "Optional[SuspensionRecord]":
    bucket = state.get(DURABLE_STATE_KEY, {}) or {}
    raw = bucket.get("suspension")
    if raw is None or raw.get("channel") != channel:
        return None
    return SuspensionRecord(**raw)


def write_journal_into_state(state, entries: "list"):
    """Return a new State with the journal entries embedded."""
    bucket = dict(state.get(DURABLE_STATE_KEY, {}) or {})
    bucket["journal"] = [dataclasses.asdict(e) for e in entries]
    return state.update(**{DURABLE_STATE_KEY: bucket})


def read_journal_from_state(state) -> "list":
    bucket = state.get(DURABLE_STATE_KEY, {}) or {}
    return [JournalEntry(**raw) for raw in bucket.get("journal", [])]
