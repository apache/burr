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


# ---------------------------------------------------------------------------
# asyncpg durable storage tests — skipped unless BURR_CI_INTEGRATION_TESTS=true
# ---------------------------------------------------------------------------

import pytest_asyncio


@pytest_asyncio.fixture
async def asyncpg_persister():
    from burr.integrations.persisters.b_asyncpg import AsyncPostgreSQLPersister

    persister = await AsyncPostgreSQLPersister.from_values(
        db_name=os.environ.get("POSTGRES_DB", "postgres"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        table_name="burr_state_asyncpg_durable_test",
    )
    await persister.initialize()
    yield persister
    conn, acquired = await persister._get_connection()
    try:
        await conn.execute("DROP TABLE IF EXISTS burr_suspensions")
        await conn.execute("DROP TABLE IF EXISTS burr_journal")
        await conn.execute("DROP TABLE IF EXISTS burr_state_asyncpg_durable_test")
    finally:
        await persister._release_connection(conn, acquired)
    await persister.cleanup()


@_pg_integration
@pytest.mark.asyncio
async def test_asyncpg_supports_durable_storage(asyncpg_persister):
    assert supports_durable_storage(asyncpg_persister) is True


@_pg_integration
@pytest.mark.asyncio
async def test_asyncpg_suspension_round_trip(asyncpg_persister):
    await asyncpg_persister.save_suspension(_record())
    loaded = await asyncpg_persister.load_suspension("pk", "app", "approval")
    assert loaded.suspension_id == "sus-1"
    assert loaded.state == {"draft": "d"}
    assert loaded.inputs == {"x": 1}
    assert loaded.schema_json == {"type": "object"}
    assert loaded.resolved is False


@_pg_integration
@pytest.mark.asyncio
async def test_asyncpg_load_suspension_returns_resolved_record(asyncpg_persister):
    # Contract: load_suspension returns the record whether or not it is
    # resolved; the caller checks record.resolved for resume-once idempotency.
    await asyncpg_persister.save_suspension(_record())
    await asyncpg_persister.mark_suspension_resolved("sus-1")
    loaded = await asyncpg_persister.load_suspension("pk", "app", "approval")
    assert loaded is not None
    assert loaded.resolved is True


@_pg_integration
@pytest.mark.asyncio
async def test_asyncpg_mark_resolved_is_conditional(asyncpg_persister):
    await asyncpg_persister.save_suspension(_record())
    first = await asyncpg_persister.mark_suspension_resolved("sus-1")
    second = await asyncpg_persister.mark_suspension_resolved("sus-1")
    # First call resolves a row; second call resolves nothing (resume-once).
    assert first is True
    assert second is False


@_pg_integration
@pytest.mark.asyncio
async def test_asyncpg_journal_round_trip(asyncpg_persister):
    await asyncpg_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "summarize", 0, "result-a")
    )
    await asyncpg_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "translate", 1, "result-b")
    )
    journal = await asyncpg_persister.load_journal("pk", "app", 4)
    assert [e.call_index for e in journal] == [0, 1]
    assert [e.result for e in journal] == ["result-a", "result-b"]


# ---------------------------------------------------------------------------
# aiosqlite durable storage tests — no integration marker, uses :memory: DB
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def aiosqlite_persister():
    from burr.integrations.persisters.b_aiosqlite import AsyncSQLitePersister

    persister = await AsyncSQLitePersister.from_values(db_path=":memory:")
    await persister.initialize()
    yield persister
    await persister.connection.close()


@pytest.mark.asyncio
async def test_aiosqlite_supports_durable_storage(aiosqlite_persister):
    from burr.core.durable import supports_durable_storage

    assert supports_durable_storage(aiosqlite_persister) is True


@pytest.mark.asyncio
async def test_aiosqlite_suspension_round_trip(aiosqlite_persister):
    await aiosqlite_persister.save_suspension(_record())
    loaded = await aiosqlite_persister.load_suspension("pk", "app", "approval")
    assert loaded.suspension_id == "sus-1"
    assert loaded.state == {"draft": "d"}
    assert loaded.inputs == {"x": 1}
    assert loaded.schema_json == {"type": "object"}
    assert loaded.resolved is False


@pytest.mark.asyncio
async def test_aiosqlite_load_suspension_returns_resolved_record(aiosqlite_persister):
    # Contract: load_suspension returns the record whether or not it is
    # resolved; the caller checks record.resolved for resume-once idempotency.
    await aiosqlite_persister.save_suspension(_record())
    await aiosqlite_persister.mark_suspension_resolved("sus-1")
    loaded = await aiosqlite_persister.load_suspension("pk", "app", "approval")
    assert loaded is not None
    assert loaded.resolved is True


@pytest.mark.asyncio
async def test_aiosqlite_mark_resolved_is_conditional(aiosqlite_persister):
    await aiosqlite_persister.save_suspension(_record())
    first = await aiosqlite_persister.mark_suspension_resolved("sus-1")
    second = await aiosqlite_persister.mark_suspension_resolved("sus-1")
    # First call resolves a row; second call resolves nothing (resume-once).
    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_aiosqlite_journal_round_trip(aiosqlite_persister):
    await aiosqlite_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "summarize", 0, "result-a")
    )
    await aiosqlite_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "translate", 1, "result-b")
    )
    journal = await aiosqlite_persister.load_journal("pk", "app", 4)
    assert [e.call_index for e in journal] == [0, 1]
    assert [e.result for e in journal] == ["result-a", "result-b"]


# ---------------------------------------------------------------------------
# Redis durable storage tests — skipped unless BURR_CI_INTEGRATION_TESTS=true
# ---------------------------------------------------------------------------


@pytest.fixture
def redis_persister():
    from burr.integrations.persisters.b_redis import RedisBasePersister

    persister = RedisBasePersister.from_values(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        db=int(os.environ.get("REDIS_DB", "15")),
    )
    persister.connection.flushdb()
    yield persister
    persister.connection.flushdb()
    persister.connection.close()


@_pg_integration
def test_redis_supports_durable_storage(redis_persister):
    assert supports_durable_storage(redis_persister) is True


@_pg_integration
def test_redis_suspension_round_trip(redis_persister):
    redis_persister.save_suspension(_record())
    loaded = redis_persister.load_suspension("pk", "app", "approval")
    assert loaded.suspension_id == "sus-1"
    assert loaded.state == {"draft": "d"}
    assert loaded.inputs == {"x": 1}
    assert loaded.schema_json == {"type": "object"}
    assert loaded.resolved is False


@_pg_integration
def test_redis_load_suspension_returns_resolved_record(redis_persister):
    # Contract: load_suspension returns the record whether or not it is
    # resolved; the caller checks record.resolved for resume-once idempotency.
    redis_persister.save_suspension(_record())
    redis_persister.mark_suspension_resolved("sus-1")
    loaded = redis_persister.load_suspension("pk", "app", "approval")
    assert loaded is not None
    assert loaded.resolved is True


@_pg_integration
def test_redis_mark_resolved_is_conditional(redis_persister):
    redis_persister.save_suspension(_record())
    first = redis_persister.mark_suspension_resolved("sus-1")
    second = redis_persister.mark_suspension_resolved("sus-1")
    # First call resolves; second call is a no-op (resume-once).
    assert first is True
    assert second is False


@_pg_integration
def test_redis_journal_round_trip(redis_persister):
    redis_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "summarize", 0, "result-a")
    )
    redis_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "translate", 1, "result-b")
    )
    journal = redis_persister.load_journal("pk", "app", 4)
    assert [e.call_index for e in journal] == [0, 1]
    assert [e.result for e in journal] == ["result-a", "result-b"]


# ---------------------------------------------------------------------------
# Async Redis durable storage tests — skipped unless BURR_CI_INTEGRATION_TESTS=true
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_redis_persister():
    from burr.integrations.persisters.b_redis import AsyncRedisBasePersister

    persister = AsyncRedisBasePersister.from_values(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        db=int(os.environ.get("REDIS_DB", "15")),
    )
    await persister.connection.flushdb()
    yield persister
    await persister.connection.flushdb()
    await persister.connection.aclose()


@_pg_integration
@pytest.mark.asyncio
async def test_async_redis_supports_durable_storage(async_redis_persister):
    assert supports_durable_storage(async_redis_persister) is True


@_pg_integration
@pytest.mark.asyncio
async def test_async_redis_suspension_round_trip(async_redis_persister):
    await async_redis_persister.save_suspension(_record())
    loaded = await async_redis_persister.load_suspension("pk", "app", "approval")
    assert loaded.suspension_id == "sus-1"
    assert loaded.state == {"draft": "d"}
    assert loaded.inputs == {"x": 1}
    assert loaded.schema_json == {"type": "object"}
    assert loaded.resolved is False


@_pg_integration
@pytest.mark.asyncio
async def test_async_redis_load_suspension_returns_resolved_record(async_redis_persister):
    # Contract: load_suspension returns the record whether or not it is
    # resolved; the caller checks record.resolved for resume-once idempotency.
    await async_redis_persister.save_suspension(_record())
    await async_redis_persister.mark_suspension_resolved("sus-1")
    loaded = await async_redis_persister.load_suspension("pk", "app", "approval")
    assert loaded is not None
    assert loaded.resolved is True


@_pg_integration
@pytest.mark.asyncio
async def test_async_redis_mark_resolved_is_conditional(async_redis_persister):
    await async_redis_persister.save_suspension(_record())
    first = await async_redis_persister.mark_suspension_resolved("sus-1")
    second = await async_redis_persister.mark_suspension_resolved("sus-1")
    # First call resolves; second call is a no-op (resume-once).
    assert first is True
    assert second is False


@_pg_integration
@pytest.mark.asyncio
async def test_async_redis_journal_round_trip(async_redis_persister):
    await async_redis_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "summarize", 0, "result-a")
    )
    await async_redis_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "translate", 1, "result-b")
    )
    journal = await async_redis_persister.load_journal("pk", "app", 4)
    assert [e.call_index for e in journal] == [0, 1]
    assert [e.result for e in journal] == ["result-a", "result-b"]


# ---------------------------------------------------------------------------
# MongoDB (pymongo) durable storage tests — skipped unless BURR_CI_INTEGRATION_TESTS=true
# ---------------------------------------------------------------------------


@pytest.fixture
def mongo_persister():
    from burr.integrations.persisters.b_pymongo import MongoDBBasePersister
    from pymongo import MongoClient

    client = MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
    db_name = os.environ.get("MONGO_DB", "burr_durable_test")
    persister = MongoDBBasePersister(
        client=client, db_name=db_name, collection_name="burr_state_durable_test"
    )
    persister.initialize()
    yield persister
    client.drop_database(db_name)
    client.close()


@_pg_integration
def test_pymongo_supports_durable_storage(mongo_persister):
    assert supports_durable_storage(mongo_persister) is True


@_pg_integration
def test_pymongo_suspension_round_trip(mongo_persister):
    mongo_persister.save_suspension(_record())
    loaded = mongo_persister.load_suspension("pk", "app", "approval")
    assert loaded.suspension_id == "sus-1"
    assert loaded.state == {"draft": "d"}
    assert loaded.inputs == {"x": 1}
    assert loaded.schema_json == {"type": "object"}
    assert loaded.resolved is False


@_pg_integration
def test_pymongo_load_suspension_returns_resolved_record(mongo_persister):
    # Contract: load_suspension returns the record whether or not it is
    # resolved; the caller checks record.resolved for resume-once idempotency.
    mongo_persister.save_suspension(_record())
    mongo_persister.mark_suspension_resolved("sus-1")
    loaded = mongo_persister.load_suspension("pk", "app", "approval")
    assert loaded is not None
    assert loaded.resolved is True


@_pg_integration
def test_pymongo_mark_resolved_is_conditional(mongo_persister):
    mongo_persister.save_suspension(_record())
    first = mongo_persister.mark_suspension_resolved("sus-1")
    second = mongo_persister.mark_suspension_resolved("sus-1")
    # First call resolves a row; second call resolves nothing (resume-once).
    assert first is True
    assert second is False


@_pg_integration
def test_pymongo_journal_round_trip(mongo_persister):
    mongo_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "summarize", 0, "result-a")
    )
    mongo_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "translate", 1, "result-b")
    )
    journal = mongo_persister.load_journal("pk", "app", 4)
    assert [e.call_index for e in journal] == [0, 1]
    assert [e.result for e in journal] == ["result-a", "result-b"]


def test_deprecated_mongodb_shim_inherits_durable_storage():
    """The deprecated ``burr.integrations.persisters.b_mongodb.MongoDBBasePersister``
    is a subclass of the canonical pymongo persister, so it must inherit the
    durable-storage overrides without re-declaring them."""
    from unittest.mock import MagicMock

    from burr.integrations.persisters.b_mongodb import (
        MongoDBBasePersister as DeprecatedMongoShim,
    )

    client = MagicMock()
    instance = DeprecatedMongoShim(client=client, db_name="x", collection_name="y")
    assert supports_durable_storage(instance) is True


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
