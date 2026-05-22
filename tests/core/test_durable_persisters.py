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

import os

import pytest

from burr.core.durable import JournalEntry, SuspensionRecord, supports_durable_storage
from burr.core.persistence import SQLitePersister

_pg_integration = pytest.mark.skipif(
    os.environ.get("BURR_CI_INTEGRATION_TESTS") != "true",
    reason="Skipping integration tests",
)


@pytest.fixture
def sqlite_persister():
    persister = SQLitePersister.from_values(":memory:")
    persister.initialize()
    yield persister


def _record(resolved=False):
    return SuspensionRecord(
        suspension_id="sus-1", partition_key="pk", app_id="app",
        sequence_id=4, position="review", channel="approval",
        schema_json={"type": "object"}, metadata={"summary": "s"},
        inputs={"x": 1}, state={"draft": "d"},
        created_at="2026-05-22T00:00:00", resolved=resolved,
    )


def test_sqlite_supports_durable_storage(sqlite_persister):
    assert supports_durable_storage(sqlite_persister) is True


def test_sqlite_suspension_round_trip(sqlite_persister):
    sqlite_persister.save_suspension(_record())
    loaded = sqlite_persister.load_suspension("pk", "app", "approval")
    assert loaded.suspension_id == "sus-1"
    assert loaded.state == {"draft": "d"}
    assert loaded.inputs == {"x": 1}
    assert loaded.schema_json == {"type": "object"}
    assert loaded.resolved is False


def test_sqlite_load_suspension_returns_resolved_record(sqlite_persister):
    # Contract: load_suspension returns the record whether or not it is
    # resolved; the caller checks record.resolved for resume-once idempotency.
    sqlite_persister.save_suspension(_record())
    sqlite_persister.mark_suspension_resolved("sus-1")
    loaded = sqlite_persister.load_suspension("pk", "app", "approval")
    assert loaded is not None
    assert loaded.resolved is True


def test_sqlite_mark_resolved_is_conditional(sqlite_persister):
    sqlite_persister.save_suspension(_record())
    first = sqlite_persister.mark_suspension_resolved("sus-1")
    second = sqlite_persister.mark_suspension_resolved("sus-1")
    # First call resolves a row; second call resolves nothing (resume-once).
    assert first is True
    assert second is False


def test_sqlite_journal_round_trip(sqlite_persister):
    sqlite_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "summarize", 0, "result-a")
    )
    sqlite_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "translate", 1, "result-b")
    )
    journal = sqlite_persister.load_journal("pk", "app", 4)
    assert [e.call_index for e in journal] == [0, 1]
    assert [e.result for e in journal] == ["result-a", "result-b"]


# ---------------------------------------------------------------------------
# PostgreSQL durable storage tests — skipped unless BURR_CI_INTEGRATION_TESTS=true
# ---------------------------------------------------------------------------


@pytest.fixture
def pg_persister():
    from burr.integrations.persisters.b_psycopg2 import PostgreSQLPersister

    persister = PostgreSQLPersister.from_values(
        db_name=os.environ.get("POSTGRES_DB", "postgres"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        table_name="burr_state_durable_test",
    )
    persister.initialize()
    yield persister
    # Teardown: drop durable + state tables so the next run starts clean.
    cursor = persister.connection.cursor()
    cursor.execute("DROP TABLE IF EXISTS burr_suspensions")
    cursor.execute("DROP TABLE IF EXISTS burr_journal")
    cursor.execute("DROP TABLE IF EXISTS burr_state_durable_test")
    persister.connection.commit()
    persister.cleanup()


@_pg_integration
def test_postgres_supports_durable_storage(pg_persister):
    assert supports_durable_storage(pg_persister) is True


@_pg_integration
def test_postgres_suspension_round_trip(pg_persister):
    pg_persister.save_suspension(_record())
    loaded = pg_persister.load_suspension("pk", "app", "approval")
    assert loaded.suspension_id == "sus-1"
    assert loaded.state == {"draft": "d"}
    assert loaded.inputs == {"x": 1}
    assert loaded.schema_json == {"type": "object"}
    assert loaded.resolved is False


@_pg_integration
def test_postgres_load_suspension_returns_resolved_record(pg_persister):
    # Contract: load_suspension returns the record whether or not it is
    # resolved; the caller checks record.resolved for resume-once idempotency.
    pg_persister.save_suspension(_record())
    pg_persister.mark_suspension_resolved("sus-1")
    loaded = pg_persister.load_suspension("pk", "app", "approval")
    assert loaded is not None
    assert loaded.resolved is True


@_pg_integration
def test_postgres_mark_resolved_is_conditional(pg_persister):
    pg_persister.save_suspension(_record())
    first = pg_persister.mark_suspension_resolved("sus-1")
    second = pg_persister.mark_suspension_resolved("sus-1")
    # First call resolves a row; second call resolves nothing (resume-once).
    assert first is True
    assert second is False


@_pg_integration
def test_postgres_journal_round_trip(pg_persister):
    pg_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "summarize", 0, "result-a")
    )
    pg_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "translate", 1, "result-b")
    )
    journal = pg_persister.load_journal("pk", "app", 4)
    assert [e.call_index for e in journal] == [0, 1]
    assert [e.result for e in journal] == ["result-a", "result-b"]


def test_deprecated_postgresql_shim_inherits_durable_storage():
    """The deprecated ``burr.integrations.persisters.postgresql.PostgreSQLPersister``
    is a subclass of the canonical psycopg2 persister, so it must inherit the
    durable-storage overrides without re-declaring them. We don't connect to a
    real database here, only confirm ``supports_durable_storage`` is True on a
    no-arg instance constructed with a dummy connection."""
    from unittest.mock import MagicMock

    from burr.integrations.persisters.postgresql import (
        PostgreSQLPersister as DeprecatedShim,
    )

    instance = DeprecatedShim(connection=MagicMock(), table_name="burr_state_shim_test")
    assert supports_durable_storage(instance) is True
