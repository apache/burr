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
import pickle

import psycopg2
import psycopg2.extensions
import pytest

from burr.core import state
from burr.integrations.persisters.b_asyncpg import AsyncPostgreSQLPersister
from burr.integrations.persisters.b_psycopg2 import PostgreSQLPersister

if not os.environ.get("BURR_CI_INTEGRATION_TESTS") == "true":
    pytest.skip("Skipping integration tests", allow_module_level=True)


@pytest.fixture
def postgresql_persister():
    persister = PostgreSQLPersister.from_values(
        db_name="postgres",
        user="postgres",
        password="postgres",
        host="localhost",
        port=5432,
        table_name="testtable",
    )
    persister.initialize()
    yield persister
    persister.cleanup()


def test_save_and_load_state(postgresql_persister):
    postgresql_persister.save("pk", "app_id", 1, "pos", state.State({"a": 1, "b": 2}), "completed")
    data = postgresql_persister.load("pk", "app_id", 1)
    assert data["state"].get_all() == {"a": 1, "b": 2}


def test_list_app_ids(postgresql_persister):
    postgresql_persister.save("pk", "app_id1", 1, "pos1", state.State({"a": 1}), "completed")
    postgresql_persister.save("pk", "app_id2", 2, "pos2", state.State({"b": 2}), "completed")
    app_ids = postgresql_persister.list_app_ids("pk")
    assert "app_id1" in app_ids
    assert "app_id2" in app_ids


def test_failed_save_does_not_poison_the_connection(postgresql_persister):
    """A rejected insert is rolled back, so later calls on the same persister still work."""
    postgresql_persister.save("txn", "app", 1, "pos", state.State({"a": 1}), "completed")
    with pytest.raises(psycopg2.errors.UniqueViolation):
        postgresql_persister.save("txn", "app", 1, "pos", state.State({"a": 1}), "completed")
    assert postgresql_persister.load("txn", "app", 1)["state"].get_all() == {"a": 1}
    assert postgresql_persister.list_app_ids("txn") == ["app"]
    postgresql_persister.save("txn", "app", 2, "pos", state.State({"a": 2}), "completed")
    assert postgresql_persister.load("txn", "app")["sequence_id"] == 2


def _is_idle(persister):
    return (
        persister.connection.get_transaction_status() == psycopg2.extensions.TRANSACTION_STATUS_IDLE
    )


def test_reads_leave_no_transaction_open(postgresql_persister):
    postgresql_persister.save("txn-read", "app", 1, "pos", state.State({"a": 1}), "completed")
    postgresql_persister.load("txn-read", "app")
    assert _is_idle(postgresql_persister)
    postgresql_persister.load("txn-read", "missing")
    assert _is_idle(postgresql_persister)
    postgresql_persister.list_app_ids("txn-read")
    assert _is_idle(postgresql_persister)
    fresh = PostgreSQLPersister.from_values(
        db_name="postgres",
        user="postgres",
        password="postgres",
        host="localhost",
        port=5432,
        table_name="testtable",
    )
    try:
        assert fresh.is_initialized()
        assert _is_idle(fresh)
    finally:
        fresh.cleanup()


def test_interrupted_call_rolls_back(postgresql_persister):
    """A KeyboardInterrupt mid-statement must not leave the transaction open."""
    real = postgresql_persister.connection

    class InterruptingCursor:
        def __init__(self):
            self.cursor = real.cursor()

        def execute(self, *args, **kwargs):
            self.cursor.execute(*args, **kwargs)
            raise KeyboardInterrupt()

    class ConnectionProxy:
        def cursor(self):
            return InterruptingCursor()

        def __getattr__(self, name):
            return getattr(real, name)

    interrupted = PostgreSQLPersister(ConnectionProxy(), table_name="testtable")
    with pytest.raises(KeyboardInterrupt):
        interrupted.load("txn-interrupt", "app")
    assert real.get_transaction_status() == psycopg2.extensions.TRANSACTION_STATUS_IDLE


def test_persister_works_inside_a_callers_connection_block(postgresql_persister):
    """Callers who wrap the persister in their own ``with connection`` block keep working."""
    with postgresql_persister.connection:
        postgresql_persister.save("txn-nested", "app", 1, "pos", state.State({"a": 1}), "completed")
        assert postgresql_persister.load("txn-nested", "app", 1)["state"].get_all() == {"a": 1}


def test_save_after_read_is_stamped_after_another_connections_save(postgresql_persister):
    """created_at comes from the transaction start, so a read must not keep one open
    across another connection's save."""
    other = PostgreSQLPersister.from_values(
        db_name="postgres",
        user="postgres",
        password="postgres",
        host="localhost",
        port=5432,
        table_name="testtable",
    )
    try:
        postgresql_persister.load("txn-order", "missing")
        other.save("txn-order", "app-b", 1, "pos", state.State({}), "completed")
        postgresql_persister.save("txn-order", "app-a", 1, "pos", state.State({}), "completed")
        created_a = postgresql_persister.load("txn-order", "app-a", 1)["created_at"]
        created_b = postgresql_persister.load("txn-order", "app-b", 1)["created_at"]
        assert created_a >= created_b
    finally:
        other.cleanup()


def test_load_nonexistent_key(postgresql_persister):
    state_data = postgresql_persister.load("pk", "nonexistent_key")
    assert state_data is None


def test_is_initialized(postgresql_persister):
    """Tests that a new connection also returns True for is_initialized."""
    assert postgresql_persister.is_initialized()
    persister2 = PostgreSQLPersister.from_values(
        db_name="postgres",
        user="postgres",
        password="postgres",
        host="localhost",
        port=5432,
        table_name="testtable",
    )
    assert persister2.is_initialized()


def test_is_initialized_false():
    persister = PostgreSQLPersister.from_values(
        db_name="postgres",
        user="postgres",
        password="postgres",
        host="localhost",
        port=5432,
        table_name="testtable2",
    )
    assert not persister.is_initialized()


def test_serialization_with_pickle(postgresql_persister):
    # Save some state
    postgresql_persister.save(
        "pk", "app_id_serde", 1, "pos", state.State({"a": 1, "b": 2}), "completed"
    )

    # Serialize the persister
    serialized_persister = pickle.dumps(postgresql_persister)

    # Deserialize the persister
    deserialized_persister = pickle.loads(serialized_persister)

    # Load the state from the deserialized persister
    data = deserialized_persister.load("pk", "app_id_serde", 1)

    assert data["state"].get_all() == {"a": 1, "b": 2}


@pytest.fixture
async def asyncpostgresql_persister():
    persister = await AsyncPostgreSQLPersister.from_values(
        db_name="postgres",
        user="postgres",
        password="postgres",
        host="localhost",
        port=5432,
        table_name="testtable_async",
    )
    await persister.initialize()
    yield persister
    await persister.cleanup()


async def test_async_pg_fixture(asyncpostgresql_persister):
    assert await asyncpostgresql_persister.is_initialized()


async def test_async_is_initialized_false():
    persister = await AsyncPostgreSQLPersister.from_values(
        db_name="postgres",
        user="postgres",
        password="postgres",
        host="localhost",
        port=5432,
        table_name="testtable_async2",
    )
    assert not await persister.is_initialized()


async def test_async_save_and_load_state(asyncpostgresql_persister):
    await asyncpostgresql_persister.save(
        "pk", "app_id", 1, "pos", state.State({"a": 1, "b": 2}), "completed"
    )
    data = await asyncpostgresql_persister.load("pk", "app_id", 1)
    print(data)
    assert data["state"].get_all() == {"a": 1, "b": 2}


async def test_async_list_app_ids(asyncpostgresql_persister):
    await asyncpostgresql_persister.save(
        "pk", "app_id1", 1, "pos1", state.State({"a": 1}), "completed"
    )
    await asyncpostgresql_persister.save(
        "pk", "app_id2", 2, "pos2", state.State({"b": 2}), "completed"
    )
    app_ids = await asyncpostgresql_persister.list_app_ids("pk")
    assert "app_id1" in app_ids
    assert "app_id2" in app_ids


async def test_async_load_nonexistent_key(asyncpostgresql_persister):
    state_data = await asyncpostgresql_persister.load("pk", "nonexistent_key")
    assert state_data is None
