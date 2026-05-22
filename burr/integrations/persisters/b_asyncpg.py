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

import json
import logging
from datetime import datetime
from typing import Any, ClassVar, Literal, Optional

from burr.common.types import BaseCopyable
from burr.core import persistence, serde, state
from burr.core.durable import JournalEntry, SuspensionRecord
from burr.integrations import base

try:
    import asyncpg
except ImportError as e:
    base.require_plugin(e, "asyncpg")

try:
    from typing import Self
except ImportError:
    Self = Any


logger = logging.getLogger(__name__)


class AsyncPostgreSQLPersister(persistence.AsyncBaseStatePersister, BaseCopyable):
    """Class for async PostgreSQL persistence of state.

    .. warning::
        The synchronous persister closes the connection on deletion of the class using the ``__del__`` method.
        In an async context that is not reliable (the event loop may already be closed by the time ``__del__``
        gets invoked). Therefore, you are responsible for closing the connection yourself (i.e. manual cleanup).
        We suggest to use the persister either as a context manager through the ``async with`` clause or
        using the method ``.cleanup()``.

    .. warning::
        If you intend to use parallelism features or need to share this persister across multiple tasks,
        you should initialize it with a connection pool (set ``use_pool=True`` in ``from_values``).
        Direct connections cannot be shared across different tasks and may cause errors in concurrent scenarios.

    .. note::
        The implementation relies on the popular asyncpg library: https://github.com/MagicStack/asyncpg

        MagicStack wrote a blog post: http://magic.io/blog/asyncpg-1m-rows-from-postgres-to-python/
        explaining why a new implementation, performance review and comparison to aiopg (async interface of psycopg2).


    To try it out locally with docker -- here's a command -- change the values as appropriate.

    .. code:: bash

        docker run --name local-psql \\\\  # container name
                   -v local_psql_data:/SOME/FILE_PATH/ \\\\  # mounting a volume for data persistence
                   -p 54320:5432 \\\\  # port mapping
                   -e POSTGRES_PASSWORD=my_password \\\\  # superuser password
                   -d postgres  # database name

    Then you should be able to create the class like this:

    .. code:: python

        p = await AsyncPostgreSQLPersister.from_values("postgres", "postgres", "my_password",
                                           "localhost", 54320, table_name="burr_state")

    """

    PARTITION_KEY_DEFAULT = ""

    # Class variable to hold the connection pool
    _pool: ClassVar[Optional[asyncpg.Pool]] = None

    @classmethod
    async def create_pool(
        cls,
        user: str,
        password: str,
        database: str,
        host: str,
        port: int,
        **pool_kwargs,
    ) -> asyncpg.Pool:
        """Creates a connection pool that can be shared across persisters."""
        if cls._pool is None:
            cls._pool = await asyncpg.create_pool(
                user=user,
                password=password,
                database=database,
                host=host,
                port=port,
                **pool_kwargs,
            )
        return cls._pool

    @classmethod
    async def from_config(cls, config: dict) -> "AsyncPostgreSQLPersister":
        """Creates a new instance of the PostgreSQLPersister from a configuration dictionary."""
        return await cls.from_values(**config)

    @classmethod
    async def from_values(
        cls,
        db_name: str,
        user: str,
        password: str,
        host: str,
        port: int,
        table_name: str = "burr_state",
        use_pool: bool = False,
        **pool_kwargs,
    ) -> "AsyncPostgreSQLPersister":
        """Builds a new instance of the PostgreSQLPersister from the provided values.

        :param db_name: the name of the PostgreSQL database.
        :param user: the username to connect to the PostgreSQL database.
        :param password: the password to connect to the PostgreSQL database.
        :param host: the host of the PostgreSQL database.
        :param port: the port of the PostgreSQL database.
        :param table_name:  the table name to store things under.
        :param use_pool: whether to use a connection pool (True) or a direct connection (False)
        :param pool_kwargs: additional kwargs to pass to the pool creation
        """
        if use_pool:
            pool = await cls.create_pool(
                user=user,
                password=password,
                database=db_name,
                host=host,
                port=port,
                **pool_kwargs,
            )
            return cls(connection=None, pool=pool, table_name=table_name)
        else:
            # Original behavior - direct connection
            connection = await asyncpg.connect(
                user=user, password=password, database=db_name, host=host, port=port
            )
            return cls(connection=connection, table_name=table_name)

    def __init__(
        self,
        connection=None,
        pool=None,
        table_name: str = "burr_state",
        serde_kwargs: dict = None,
    ):
        """Constructor

        :param connection: the connection to the PostgreSQL database (optional if pool is provided)
        :param pool: a connection pool to use instead of a direct connection (optional if connection is provided)
        :param table_name:  the table name to store things under.
        :param serde_kwargs: kwargs for state serialization/deserialization
        """
        if connection is None and pool is None:
            raise ValueError("Either connection or pool must be provided")

        self.table_name = table_name
        self.connection = connection
        self.pool = pool
        self.serde_kwargs = serde_kwargs or {}
        self._initialized = False

    def copy(self) -> "Self":
        """Creates a copy of this persister.

        If using a pool, returns a new persister that will acquire its own connection from the pool.
        If using a direct connection, just returns a new persister with the same connection (won't work for async parallelism)
        """
        if self.pool is not None:
            return AsyncPostgreSQLPersister(
                connection=None,
                pool=self.pool,
                table_name=self.table_name,
                serde_kwargs=self.serde_kwargs,
            )
        else:
            return AsyncPostgreSQLPersister(
                connection=self.connection,
                table_name=self.table_name,
                serde_kwargs=self.serde_kwargs,
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.cleanup()
        return False

    async def _get_connection(self):
        """Gets a connection - either the dedicated one or one from the pool."""
        if self.pool is not None:
            return await self.pool.acquire(), True
        elif self.connection is not None:
            return self.connection, False
        else:
            raise ValueError("No connection or pool available")

    async def _release_connection(self, connection, acquired):
        """Releases a connection back to the pool if it was acquired."""
        if acquired and self.pool is not None:
            await self.pool.release(connection)

    def set_serde_kwargs(self, serde_kwargs: dict):
        """Sets the serde_kwargs for the persister."""
        self.serde_kwargs = serde_kwargs

    async def create_table(self, table_name: str):
        """Helper function to create the table where things are stored."""
        conn, acquired = await self._get_connection()
        try:
            async with conn.transaction():
                await conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        partition_key TEXT DEFAULT '{self.PARTITION_KEY_DEFAULT}',
                        app_id TEXT NOT NULL,
                        sequence_id INTEGER NOT NULL,
                        position TEXT NOT NULL,
                        status TEXT NOT NULL,
                        state JSONB NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (partition_key, app_id, sequence_id, position)
                    )"""
                )
                await conn.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {table_name}_created_at_index ON {table_name} (created_at);
                """
                )
        finally:
            await self._release_connection(conn, acquired)

    async def create_durable_tables_if_not_exist(self):
        """Creates the durable-execution tables (suspensions + journal) if they don't exist."""
        conn, acquired = await self._get_connection()
        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS burr_suspensions (
                        suspension_id TEXT PRIMARY KEY,
                        partition_key TEXT,
                        app_id TEXT NOT NULL,
                        sequence_id INTEGER NOT NULL,
                        position TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        schema_json JSONB,
                        metadata_json JSONB,
                        inputs_json JSONB,
                        state_json JSONB NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        resolved BOOLEAN NOT NULL DEFAULT false
                    )"""
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS burr_journal (
                        partition_key TEXT,
                        app_id TEXT NOT NULL,
                        sequence_id INTEGER NOT NULL,
                        step_key TEXT NOT NULL,
                        call_index INTEGER NOT NULL,
                        result_json JSONB NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (partition_key, app_id, sequence_id, step_key)
                    )"""
                )
        finally:
            await self._release_connection(conn, acquired)

    async def initialize(self):
        """Creates the table"""
        await self.create_table(self.table_name)
        await self.create_durable_tables_if_not_exist()
        self._initialized = True

    async def is_initialized(self) -> bool:
        """This checks to see if the table has been created in the database or not.
        It defaults to using the initialized field, else queries the database to see if the table exists.
        It then sets the initialized field to True if the table exists.
        """
        if self._initialized:
            return True

        conn, acquired = await self._get_connection()
        try:
            query = "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = $1)"
            self._initialized = await conn.fetchval(query, self.table_name, column=0)
            return self._initialized
        finally:
            await self._release_connection(conn, acquired)

    async def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        """Lists the app_ids for a given partition_key."""
        conn, acquired = await self._get_connection()
        try:
            query = (
                f"SELECT DISTINCT app_id, created_at FROM {self.table_name} "
                "WHERE partition_key = $1 "
                "ORDER BY created_at DESC"
            )
            fetched_data = await conn.fetch(query, partition_key)
            app_ids = [row[0] for row in fetched_data]
            return app_ids
        finally:
            await self._release_connection(conn, acquired)

    async def load(
        self,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int = None,
        **kwargs,
    ) -> Optional[persistence.PersistedStateData]:
        """Loads state for a given partition id.

        Depending on the parameters, this will return the last thing written, the last thing written for a given app_id,
        or a specific sequence_id for a given app_id.

        :param partition_key:
        :param app_id:
        :param sequence_id:
        :return:
        """
        if partition_key is None:
            partition_key = self.PARTITION_KEY_DEFAULT
        logger.debug("Loading %s, %s, %s", partition_key, app_id, sequence_id)

        conn, acquired = await self._get_connection()
        try:
            row = None
            if app_id is None:
                # get latest for all app_ids
                query = (
                    f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                    "WHERE partition_key = $1 "
                    f"ORDER BY CREATED_AT DESC LIMIT 1"
                )
                row = await conn.fetchrow(query, partition_key)
            elif sequence_id is None:
                query = (
                    f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                    "WHERE partition_key = $1 AND app_id = $2 "
                    f"ORDER BY sequence_id DESC LIMIT 1"
                )
                row = await conn.fetchrow(query, partition_key, app_id)
            else:
                query = (
                    f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                    "WHERE partition_key = $1 AND app_id = $2 AND sequence_id = $3 "
                )
                row = await conn.fetchrow(
                    query,
                    partition_key,
                    app_id,
                    sequence_id,
                )

            if row is None:
                return None

            # converts from asyncpg str to dict
            json_row = json.loads(row[1])
            _state = state.State.deserialize(json_row, **self.serde_kwargs)
            return {
                "partition_key": partition_key,
                "app_id": row[3],
                "sequence_id": row[2],
                "position": row[0],
                "state": _state,
                "created_at": row[4],
                "status": row[5],
            }
        finally:
            await self._release_connection(conn, acquired)

    async def save(
        self,
        partition_key: str,
        app_id: str,
        sequence_id: int,
        position: str,
        state: state.State,
        status: Literal["completed", "failed"],
        **kwargs,
    ):
        """
        Saves the state for a given app_id, sequence_id, and position.

        This method connects to the SQLite database, converts the state to a JSON string, and inserts a new record
        into the table with the provided partition_key, app_id, sequence_id, position, and state. After the operation,
        it commits the changes and closes the connection to the database.

        :param partition_key: The partition key. This could be None, but it's up to the persistor to whether
            that is a valid value it can handle.
        :param app_id: The identifier for the app instance being recorded.
        :param sequence_id: The state corresponding to a specific point in time.
        :param position: The position in the sequence of states.
        :param state: The state to be saved, an instance of the State class.
        :param status: The status of this state, either "completed" or "failed". If "failed" the state is what it was
            before the action was applied.
        :return: None
        """
        logger.debug(
            "saving %s, %s, %s, %s, %s, %s",
            partition_key,
            app_id,
            sequence_id,
            position,
            state,
            status,
        )

        conn, acquired = await self._get_connection()
        try:
            json_state = json.dumps(state.serialize(**self.serde_kwargs))
            query = (
                f"INSERT INTO {self.table_name} (partition_key, app_id, sequence_id, position, state, status) "
                "VALUES ($1, $2, $3, $4, $5, $6)"
            )
            await conn.execute(
                query, partition_key, app_id, sequence_id, position, json_state, status
            )
        finally:
            await self._release_connection(conn, acquired)

    async def save_suspension(self, record: SuspensionRecord) -> None:
        """Persist a suspension record into the burr_suspensions table."""
        conn, acquired = await self._get_connection()
        try:
            # asyncpg requires datetime objects for TIMESTAMP columns;
            # SuspensionRecord.created_at is typed as str so we parse it when needed.
            created_at = record.created_at
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            await conn.execute(
                """INSERT INTO burr_suspensions
                   (suspension_id, partition_key, app_id, sequence_id, position,
                    channel, schema_json, metadata_json, inputs_json, state_json,
                    created_at, resolved)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                   ON CONFLICT (suspension_id) DO UPDATE SET
                       partition_key = EXCLUDED.partition_key,
                       app_id = EXCLUDED.app_id,
                       sequence_id = EXCLUDED.sequence_id,
                       position = EXCLUDED.position,
                       channel = EXCLUDED.channel,
                       schema_json = EXCLUDED.schema_json,
                       metadata_json = EXCLUDED.metadata_json,
                       inputs_json = EXCLUDED.inputs_json,
                       state_json = EXCLUDED.state_json,
                       created_at = EXCLUDED.created_at,
                       resolved = EXCLUDED.resolved""",
                record.suspension_id,
                record.partition_key,
                record.app_id,
                record.sequence_id,
                record.position,
                record.channel,
                json.dumps(record.schema_json),
                json.dumps(serde.serialize(record.metadata, **self.serde_kwargs)),
                json.dumps(serde.serialize(record.inputs, **self.serde_kwargs)),
                json.dumps(serde.serialize(record.state, **self.serde_kwargs)),
                created_at,
                record.resolved,
            )
        finally:
            await self._release_connection(conn, acquired)

    async def load_suspension(
        self, partition_key: Optional[str], app_id: str, channel: str
    ) -> Optional[SuspensionRecord]:
        """Load the most recent suspension record for (partition_key, app_id, channel).

        Returns the record whether or not it is resolved; callers check
        ``record.resolved`` for resume-once idempotency. Returns ``None``
        when no record exists for this combination.
        """
        conn, acquired = await self._get_connection()
        try:
            row = await conn.fetchrow(
                """SELECT suspension_id, partition_key, app_id, sequence_id, position,
                          channel, schema_json, metadata_json, inputs_json, state_json,
                          created_at, resolved
                   FROM burr_suspensions
                   WHERE partition_key IS NOT DISTINCT FROM $1 AND app_id = $2 AND channel = $3
                   ORDER BY created_at DESC LIMIT 1""",
                partition_key,
                app_id,
                channel,
            )
            if row is None:
                return None
            # asyncpg returns JSONB columns as strings — must json.loads() explicitly
            # (unlike psycopg2 which auto-parses JSONB to Python objects).
            schema = json.loads(row[6]) if row[6] is not None else None
            metadata_raw = json.loads(row[7]) if row[7] is not None else None
            inputs_raw = json.loads(row[8])  # asyncpg: JSONB is a string, must deserialize
            state_raw = json.loads(row[9])  # asyncpg: JSONB is a string, must deserialize
            return SuspensionRecord(
                suspension_id=row[0],
                partition_key=row[1],
                app_id=row[2],
                sequence_id=row[3],
                position=row[4],
                channel=row[5],
                schema_json=schema,
                metadata=serde.deserialize(metadata_raw, **self.serde_kwargs)
                if metadata_raw is not None
                else None,
                inputs=serde.deserialize(inputs_raw, **self.serde_kwargs),
                state=serde.deserialize(state_raw, **self.serde_kwargs),
                # asyncpg returns TIMESTAMP as datetime; SuspensionRecord.created_at is str.
                created_at=row[10].isoformat() if isinstance(row[10], datetime) else row[10],
                resolved=bool(row[11]),
            )
        finally:
            await self._release_connection(conn, acquired)

    async def mark_suspension_resolved(self, suspension_id: str) -> bool:
        """Mark a suspension consumed. Conditional UPDATE for resume-once idempotency.

        :return: True if a row was updated (first call), False if already resolved (no-op).
        """
        conn, acquired = await self._get_connection()
        try:
            status = await conn.execute(
                "UPDATE burr_suspensions SET resolved = true "
                "WHERE suspension_id = $1 AND resolved = false",
                suspension_id,
            )
            # asyncpg returns status string like 'UPDATE 1' or 'UPDATE 0'
            return int(status.split()[-1]) > 0
        finally:
            await self._release_connection(conn, acquired)

    async def save_journal_entry(self, entry: JournalEntry) -> None:
        """Persist one memoized sub-step into the burr_journal table."""
        conn, acquired = await self._get_connection()
        try:
            await conn.execute(
                """INSERT INTO burr_journal
                   (partition_key, app_id, sequence_id, step_key, call_index, result_json)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (partition_key, app_id, sequence_id, step_key) DO UPDATE SET
                       call_index = EXCLUDED.call_index,
                       result_json = EXCLUDED.result_json""",
                entry.partition_key,
                entry.app_id,
                entry.sequence_id,
                entry.step_key,
                entry.call_index,
                json.dumps(serde.serialize(entry.result, **self.serde_kwargs)),
            )
        finally:
            await self._release_connection(conn, acquired)

    async def load_journal(
        self, partition_key: Optional[str], app_id: str, sequence_id: int
    ) -> list[JournalEntry]:
        """Load journal entries for a suspended action, ordered by call_index."""
        conn, acquired = await self._get_connection()
        try:
            rows = await conn.fetch(
                """SELECT partition_key, app_id, sequence_id, step_key, call_index,
                          result_json
                   FROM burr_journal
                   WHERE partition_key IS NOT DISTINCT FROM $1 AND app_id = $2 AND sequence_id = $3
                   ORDER BY call_index ASC""",
                partition_key,
                app_id,
                sequence_id,
            )
            # asyncpg returns JSONB columns as strings — must json.loads() explicitly
            # (unlike psycopg2 which auto-parses JSONB to Python objects).
            return [
                JournalEntry(
                    partition_key=row[0],
                    app_id=row[1],
                    sequence_id=row[2],
                    step_key=row[3],
                    call_index=row[4],
                    result=serde.deserialize(json.loads(row[5]), **self.serde_kwargs),
                )
                for row in rows
            ]
        finally:
            await self._release_connection(conn, acquired)

    async def cleanup(self):
        """Closes the connection to the database."""
        if self.connection is not None:
            await self.connection.close()
            self.connection = None
