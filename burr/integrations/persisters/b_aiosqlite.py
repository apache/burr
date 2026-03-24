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
from typing import Literal, Optional

import aiosqlite

from burr.common.async_utils import _AsyncPersisterContextManager
from burr.common.types import BaseCopyable
from burr.core import State
from burr.core.persistence import AsyncBaseStatePersister, PersistedStateData

logger = logging.getLogger()

try:
    from typing import Self
except ImportError:
    Self = None


class AsyncSQLitePersister(AsyncBaseStatePersister, BaseCopyable):
    """Class for asynchronous SQLite persistence of state. This is a simple implementation.

    .. warning::
        The synchronous persister closes the connection on deletion of the class using the ``__del__`` method.
        In an async context that is not reliable (the event loop may already be closed by the time ``__del__``
        gets invoked). Therefore, you are responsible for closing the connection yourself (i.e. manual cleanup).
        We suggest to use the persister either as a context manager through the ``async with`` clause or
        using the method ``.cleanup()``.

    .. note::
        SQLite is specifically single-threaded and `aiosqlite <https://aiosqlite.omnilib.dev/en/latest/index.html>`_
        creates async support through multi-threading. This persister is mainly here for quick prototyping and testing;
        we suggest to consider a different database with native async support for production.

        Note the third-party library `aiosqlite <https://aiosqlite.omnilib.dev/en/latest/index.html>`_,
        is maintained and considered stable considered stable: https://github.com/omnilib/aiosqlite/issues/309.
    """

    def copy(self) -> "Self":
        return AsyncSQLitePersister(
            connection=self.connection, table_name=self.table_name, serde_kwargs=self.serde_kwargs
        )

    PARTITION_KEY_DEFAULT = ""

    @classmethod
    def from_config(cls, config: dict) -> "_AsyncPersisterContextManager":
        """Creates a new instance of the AsyncSQLitePersister from a configuration dictionary.

        Can be used with ``await`` or as an async context manager::

            persister = await AsyncSQLitePersister.from_config(config)
            # or
            async with AsyncSQLitePersister.from_config(config) as persister:
                ...

        The config key:value pair needed are:
        db_path: str,
        table_name: str,
        serde_kwargs: dict,
        connect_kwargs: dict,
        """
        return cls.from_values(**config)

    @classmethod
    def from_values(
        cls,
        db_path: str,
        table_name: str = "burr_state",
        serde_kwargs: dict = None,
        connect_kwargs: dict = None,
    ) -> "_AsyncPersisterContextManager":
        """Creates a new instance of the AsyncSQLitePersister from passed in values.

        Can be used with ``await`` or as an async context manager::

            persister = await AsyncSQLitePersister.from_values(db_path="test.db")
            # or
            async with AsyncSQLitePersister.from_values(db_path="test.db") as persister:
                ...

        :param db_path: the path the DB will be stored.
        :param table_name: the table name to store things under.
        :param serde_kwargs: kwargs for state serialization/deserialization.
        :param connect_kwargs: kwargs to pass to the aiosqlite.connect method.
        :return: async sqlite persister instance with an open connection. You are responsible
            for closing the connection yourself.
        """

        async def _create():
            connection = await aiosqlite.connect(
                db_path, **connect_kwargs if connect_kwargs is not None else {}
            )
            return cls(connection, table_name, serde_kwargs)

        return _AsyncPersisterContextManager(_create())

    def __init__(
        self,
        connection,
        table_name: str = "burr_state",
        serde_kwargs: dict = None,
    ):
        """Constructor.

        NOTE: you are responsible to handle closing of the connection / teardown manually. To help,
        we provide a close() method.

        :param connection: the path the DB will be stored.
        :param table_name: the table name to store things under.
        :param serde_kwargs: kwargs for state serialization/deserialization.
        """
        self.connection = connection
        self.table_name = table_name
        self.serde_kwargs = serde_kwargs or {}
        self._initialized = False

    def set_serde_kwargs(self, serde_kwargs: dict):
        """Sets the serde_kwargs for the persister."""
        self.serde_kwargs = serde_kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.connection.close()
        return False

    async def create_table_if_not_exists(self, table_name: str):
        """Helper function to create the table where things are stored if it doesn't exist."""
        cursor = await self.connection.cursor()
        await cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                partition_key TEXT DEFAULT '{AsyncSQLitePersister.PARTITION_KEY_DEFAULT}',
                app_id TEXT NOT NULL,
                sequence_id INTEGER NOT NULL,
                position TEXT NOT NULL,
                status TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (partition_key, app_id, sequence_id, position)
            )"""
        )
        await cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {table_name}_created_at_index ON {table_name} (created_at);
        """
        )
        await self.connection.commit()

    async def initialize(self):
        """Asynchronously creates the table if it doesn't exist"""
        # Usage
        await self.create_table_if_not_exists(self.table_name)
        self._initialized = True

    async def is_initialized(self) -> bool:
        """This checks to see if the table has been created in the database or not.
        It defaults to using the initialized field, else queries the database to see if the table exists.
        It then sets the initialized field to True if the table exists.
        """
        if self._initialized:
            return True

        cursor = await self.connection.cursor()
        await cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (self.table_name,)
        )
        self._initialized = await cursor.fetchone() is not None
        return self._initialized

    async def list_app_ids(self, partition_key: Optional[str] = None, **kwargs) -> list[str]:
        partition_key = (
            partition_key
            if partition_key is not None
            else AsyncSQLitePersister.PARTITION_KEY_DEFAULT
        )

        cursor = await self.connection.cursor()
        await cursor.execute(
            f"SELECT DISTINCT app_id FROM {self.table_name} "
            f"WHERE partition_key = ? "
            f"ORDER BY created_at DESC",
            (partition_key,),
        )
        app_ids = [row[0] for row in await cursor.fetchall()]
        return app_ids

    async def load(
        self,
        partition_key: Optional[str],
        app_id: Optional[str],
        sequence_id: Optional[int] = None,
        **kwargs,
    ) -> Optional[PersistedStateData]:
        """Asynchronously loads state for a given partition id.

        Depending on the parameters, this will return the last thing written, the last thing written for a given app_id,
        or a specific sequence_id for a given app_id.

        :param partition_key:
        :param app_id:
        :param sequence_id:
        :return:
        """
        partition_key = (
            partition_key
            if partition_key is not None
            else AsyncSQLitePersister.PARTITION_KEY_DEFAULT
        )
        logger.debug("Loading %s, %s, %s", partition_key, app_id, sequence_id)
        cursor = await self.connection.cursor()
        if app_id is None:
            # get latest for all app_ids
            await cursor.execute(
                f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                f"WHERE partition_key = ? "
                f"ORDER BY CREATED_AT DESC LIMIT 1",
                (partition_key,),
            )
        elif sequence_id is None:
            await cursor.execute(
                f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                f"WHERE partition_key = ? AND app_id = ? "
                f"ORDER BY sequence_id DESC LIMIT 1",
                (partition_key, app_id),
            )
        else:
            await cursor.execute(
                f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                f"WHERE partition_key = ? AND app_id = ? AND sequence_id = ?",
                (partition_key, app_id, sequence_id),
            )
        row = await cursor.fetchone()
        if row is None:
            return None
        _state = State.deserialize(json.loads(row[1]), **self.serde_kwargs)
        return {
            "partition_key": partition_key,
            "app_id": row[3],
            "sequence_id": row[2],
            "position": row[0],
            "state": _state,
            "created_at": row[4],
            "status": row[5],
        }

    async def save(
        self,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int,
        position: str,
        state: State,
        status: Literal["completed", "failed"],
        **kwargs,
    ):
        """
        Asynchronously saves the state for a given app_id, sequence_id, and position.

        This method connects to the SQLite database, converts the state to a JSON string, and inserts a new record
        into the table with the provided partition_key, app_id, sequence_id, position, and state. After the operation,
        it commits the changes and closes the connection to the database.

        :param partition_key: The partition key. This could be None, but it's up to the persister to whether
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
        partition_key = (
            partition_key
            if partition_key is not None
            else AsyncSQLitePersister.PARTITION_KEY_DEFAULT
        )
        cursor = await self.connection.cursor()
        json_state = json.dumps(state.serialize(**self.serde_kwargs))
        await cursor.execute(
            f"INSERT INTO {self.table_name} (partition_key, app_id, sequence_id, position, state, status) "
            f"VALUES (?, ?, ?, ?, ?, ?)",
            (partition_key, app_id, sequence_id, position, json_state, status),
        )
        await self.connection.commit()

    async def cleanup(self):
        """Closes the connection to the database."""
        await self.connection.close()

    async def close(self):
        """This is deprecated, please use .cleanup()"""
        logger.warning("The .close() method will be deprecated, please use .cleanup() instead.")
        await self.connection.close()
