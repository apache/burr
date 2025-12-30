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

import abc
import datetime
import json
import sqlite3
from abc import ABCMeta
from collections import defaultdict
from typing import Any, Dict, Literal, Optional, TypedDict

from burr.common.types import BaseCopyable
from burr.core import Action
from burr.core.state import State, logger
from burr.lifecycle import PostRunStepHook, PostRunStepHookAsync

try:
    from typing import Self
except ImportError:
    Self = None

# Error message template for uninitialized SQLitePersister
_UNINITIALIZED_PERSISTER_ERROR = (
    "Uninitialized persister: table '{table_name}' does not exist. "
    "Make sure to call .initialize() on the persister before passing it "
    "to the ApplicationBuilder."
)


class PersistedStateData(TypedDict):
    partition_key: str
    app_id: str
    sequence_id: int
    position: str
    state: State
    created_at: str
    status: str


class BaseStateLoader(abc.ABC):
    """Base class for state initialization. This goes together with a BaseStateSaver to form the
    database for your application."""

    @abc.abstractmethod
    def load(
        self, partition_key: str, app_id: Optional[str], sequence_id: Optional[int] = None, **kwargs
    ) -> Optional[PersistedStateData]:
        """Loads the state for a given app_id

        :param partition_key: the partition key. Note this could be None, but it's up to the persistor to whether
            that is a valid value it can handle.
        :param app_id: the identifier for the app instance being recorded.
        :param sequence_id: optional, the state corresponding to a specific point in time. Specifically state at the
            end of the action with this sequence_id. If sequence_id is not provided, persistor should return the state
            from the latest fully completed action.
        :return: PersistedStateData or None
        """
        pass

    @abc.abstractmethod
    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        """Returns list of app IDs for a given primary key"""
        pass

    def is_async(self) -> bool:
        return False


class AsyncBaseStateLoader(abc.ABC):
    """Asynchronous base class for state initialization. This goes together with a AsyncBaseStateSaver
    to form the database for your application."""

    @abc.abstractmethod
    async def load(
        self, partition_key: str, app_id: Optional[str], sequence_id: Optional[int] = None, **kwargs
    ) -> Optional[PersistedStateData]:
        """Loads the state for a given app_id

        :param partition_key: the partition key. Note this could be None, but it's up to the persistor to whether
            that is a valid value it can handle.
        :param app_id: the identifier for the app instance being recorded.
        :param sequence_id: optional, the state corresponding to a specific point in time. Specifically state at the
            end of the action with this sequence_id. If sequence_id is not provided, persistor should return the state
            from the latest fully completed action.
        :return: PersistedStateData or None
        """
        pass

    @abc.abstractmethod
    async def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        """Returns list of app IDs for a given primary key"""
        pass

    def is_async(self) -> bool:
        return True


class BaseStateSaver(abc.ABC):
    """Base class for state writing. This goes together with a BaseStateLoader to form the
    database for your application.
    """

    def initialize(self):
        """Initializes the app for saving, set up any databases, etc.. you want to here."""
        pass

    def is_initialized(self) -> bool:
        """Check if the persister has been initialized appropriately."""
        raise NotImplementedError("Implement this method in your subclass if you need to.")

    @abc.abstractmethod
    def save(
        self,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int,
        position: str,
        state: State,
        status: Literal["completed", "failed"],
        **kwargs,
    ):
        """Saves the state for a given app_id, sequence_id, position

        (PK, App_id, sequence_id, position) are a unique identifier for the state. Why not just
        (PK, App_id, sequence_id)? Because we're over-engineering this here. We're always going to have
        a position so might as well make it a quadruple.

        :param partition_key: the partition key. Note this could be None, but it's up to the persistor to whether
            that is a valid value it can handle.
        :param app_id: Appliaction UID to write with
        :param sequence_id: Sequence ID of the last executed step
        :param position: The action name that was implemented
        :param state: The current state of the application
        :param status: The status of this state, either "completed" or "failed". If "failed" the state is what it was
            before the action was applied.
        """
        pass

    def is_async(self) -> bool:
        return False


class AsyncBaseStateSaver(abc.ABC):
    """Asynchronous base class for state writing. This goes together with a AsyncBaseStateLoader
    to form the database for your application.
    """

    async def initialize(self):
        """Initializes the app for saving, set up any databases, etc.. you want to here."""
        pass

    async def is_initialized(self) -> bool:
        """Check if the persister has been initialized appropriately."""
        raise NotImplementedError("Implement this method in your subclass if you need to.")

    @abc.abstractmethod
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
        """Saves the state for a given app_id, sequence_id, position

        (PK, App_id, sequence_id, position) are a unique identifier for the state. Why not just
        (PK, App_id, sequence_id)? Because we're over-engineering this here. We're always going to have
        a position so might as well make it a quadruple.

        :param partition_key: the partition key. Note this could be None, but it's up to the persistor to whether
            that is a valid value it can handle.
        :param app_id: Appliaction UID to write with
        :param sequence_id: Sequence ID of the last executed step
        :param position: The action name that was implemented
        :param state: The current state of the application
        :param status: The status of this state, either "completed" or "failed". If "failed" the state is what it was
            before the action was applied.
        """
        pass

    def is_async(self) -> bool:
        return True


class BaseStatePersister(BaseStateLoader, BaseStateSaver, metaclass=ABCMeta):
    """Utility interface for a state reader/writer. This both persists and initializes state.
    Extend this class if you want an easy way to implement custom state storage.
    """


class AsyncBaseStatePersister(AsyncBaseStateLoader, AsyncBaseStateSaver, metaclass=ABCMeta):
    """Utility interface for an asynchronous state reader/writer. This both persists and initializes state.
    Extend this class if you want an easy way to implement custom state storage.
    """


class PersisterHook(PostRunStepHook):
    """Wrapper class for bridging the persistence interface with lifecycle hooks. This is used internally."""

    def __init__(self, persister: BaseStateSaver):
        self.persister = persister

    def post_run_step(
        self,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        state: "State",
        action: "Action",
        result: Optional[Dict[str, Any]],
        exception: Exception,
        **future_kwargs: Any,
    ):
        if exception is None:
            self.persister.save(partition_key, app_id, sequence_id, action.name, state, "completed")
        else:
            self.persister.save(partition_key, app_id, sequence_id, action.name, state, "failed")


class PersisterHookAsync(PostRunStepHookAsync):
    """Wrapper class for bridging the persistence interface with asynchronous lifecycle hooks. This is used internally."""

    def __init__(self, persister: AsyncBaseStateSaver):
        self.persister = persister

    async def post_run_step(
        self,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        state: "State",
        action: "Action",
        result: Optional[Dict[str, Any]],
        exception: Exception,
        **future_kwargs: Any,
    ):
        if exception is None:
            await self.persister.save(
                partition_key, app_id, sequence_id, action.name, state, "completed"
            )
        else:
            await self.persister.save(
                partition_key, app_id, sequence_id, action.name, state, "failed"
            )


class DevNullPersister(BaseStatePersister):
    """Does nothing, do not use this. This is for testing only."""

    def load(
        self, partition_key: str, app_id: Optional[str], sequence_id: Optional[int] = None, **kwargs
    ) -> Optional[PersistedStateData]:
        return None

    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        return []

    def save(
        self,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int,
        position: str,
        state: State,
        status: Literal["completed", "failed"],
        **kwargs,
    ):
        return


class AsyncDevNullPersister(AsyncBaseStatePersister):
    """Does nothing asynchronously, do not use this. This is for testing only."""

    async def load(
        self, partition_key: str, app_id: Optional[str], sequence_id: Optional[int] = None, **kwargs
    ) -> Optional[PersistedStateData]:
        return None

    async def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        return []

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
        return


class SQLitePersister(BaseStatePersister, BaseCopyable):
    """Class for SQLite persistence of state. This is a simple implementation."""

    @classmethod
    def from_config(cls, config: dict) -> "SQLitePersister":
        """Creates a new instance of the SQLitePersister from a configuration dictionary.

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
    ) -> "SQLitePersister":
        """Creates a new instance of the SQLitePersister from passed in values.

        :param db_path: the path the DB will be stored.
        :param table_name: the table name to store things under.
        :param serde_kwargs: kwargs for state serialization/deserialization.
        :param connect_kwargs: kwargs to pass to the aiosqlite.connect method.
        :return: async sqlite persister instance with an open connection. You are responsible
            for closing the connection yourself.
        """
        connection = sqlite3.connect(
            db_path, **connect_kwargs if connect_kwargs is not None else {}
        )
        return cls(db_path, table_name, serde_kwargs, connection=connection)

    def copy(self) -> "Self":
        return SQLitePersister(
            db_path=self.db_path,
            table_name=self.table_name,
            serde_kwargs=self.serde_kwargs,
            connect_kwargs=self._connect_kwargs,
        )

    PARTITION_KEY_DEFAULT = ""

    def __init__(
        self,
        db_path: str,
        table_name: str = "burr_state",
        serde_kwargs: dict = None,
        connect_kwargs: dict = None,
        connection: sqlite3.Connection = None,
    ):
        """Constructor

        :param db_path: the path the DB will be stored.
        :param table_name: the table name to store things under.
        :param serde_kwargs: kwargs for state serialization/deserialization.
        :param connect_kwargs: kwargs to pass to the sqlite3.connect method.
            Use check_same_thread=False to enable use ina  multithreaded context
        :param connection: ability to instantiate a db outside of the persister and pass
            in the connection to be used.
        """
        self.db_path = db_path
        self.table_name = table_name

        # Here for backwards compatibility, the original idea was to create the connection
        # but later we realized it also makes sense to pass the connection to the class and
        # handle cleanup manually.
        if connection is None:
            self.connection = sqlite3.connect(
                db_path, **connect_kwargs if connect_kwargs is not None else {}
            )
        else:
            self.connection = connection

        self.serde_kwargs = serde_kwargs or {}
        self._initialized = False
        self._connect_kwargs = connect_kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.connection.close()
        return False

    def set_serde_kwargs(self, serde_kwargs: dict):
        """Sets the serde_kwargs for the persister."""
        self.serde_kwargs = serde_kwargs

    def create_table_if_not_exists(self, table_name: str):
        """Helper function to create the table where things are stored if it doesn't exist."""
        cursor = self.connection.cursor()
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                partition_key TEXT DEFAULT '{SQLitePersister.PARTITION_KEY_DEFAULT}',
                app_id TEXT NOT NULL,
                sequence_id INTEGER NOT NULL,
                position TEXT NOT NULL,
                status TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (partition_key, app_id, sequence_id, position)
            )"""
        )
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {table_name}_created_at_index ON {table_name} (created_at);
        """
        )
        self.connection.commit()

    def initialize(self):
        """Creates the table if it doesn't exist"""
        # Usage
        self.create_table_if_not_exists(self.table_name)
        self._initialized = True

    def is_initialized(self) -> bool:
        """This checks to see if the table has been created in the database or not.
        It defaults to using the initialized field, else queries the database to see if the table exists.
        It then sets the initialized field to True if the table exists.
        """
        if self._initialized:
            return True
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (self.table_name,)
        )
        self._initialized = cursor.fetchone() is not None
        return self._initialized

    def list_app_ids(self, partition_key: Optional[str], **kwargs) -> list[str]:
        partition_key = (
            partition_key if partition_key is not None else SQLitePersister.PARTITION_KEY_DEFAULT
        )

        cursor = self.connection.cursor()
        try:
            cursor.execute(
                f"SELECT DISTINCT app_id FROM {self.table_name} "
                f"WHERE partition_key = ? "
                f"ORDER BY created_at DESC",
                (partition_key,),
            )
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                raise RuntimeError(
                    _UNINITIALIZED_PERSISTER_ERROR.format(table_name=self.table_name)
                ) from e
            raise
        app_ids = [row[0] for row in cursor.fetchall()]
        return app_ids

    def load(
        self,
        partition_key: Optional[str],
        app_id: Optional[str],
        sequence_id: Optional[int] = None,
        **kwargs,
    ) -> Optional[PersistedStateData]:
        """Loads state for a given partition id.

        Depending on the parameters, this will return the last thing written, the last thing written for a given app_id,
        or a specific sequence_id for a given app_id.

        :param partition_key:
        :param app_id:
        :param sequence_id:
        :return:
        """
        partition_key = (
            partition_key if partition_key is not None else SQLitePersister.PARTITION_KEY_DEFAULT
        )
        logger.debug("Loading %s, %s, %s", partition_key, app_id, sequence_id)
        cursor = self.connection.cursor()
        try:
            if app_id is None:
                # get latest for all app_ids
                cursor.execute(
                    f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                    f"WHERE partition_key = ? "
                    f"ORDER BY CREATED_AT DESC LIMIT 1",
                    (partition_key,),
                )
            elif sequence_id is None:
                cursor.execute(
                    f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                    f"WHERE partition_key = ? AND app_id = ? "
                    f"ORDER BY sequence_id DESC LIMIT 1",
                    (partition_key, app_id),
                )
            else:
                cursor.execute(
                    f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                    f"WHERE partition_key = ? AND app_id = ? AND sequence_id = ?",
                    (partition_key, app_id, sequence_id),
                )
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                raise RuntimeError(
                    _UNINITIALIZED_PERSISTER_ERROR.format(table_name=self.table_name)
                ) from e
            raise
        row = cursor.fetchone()
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

    def save(
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
        partition_key = (
            partition_key if partition_key is not None else SQLitePersister.PARTITION_KEY_DEFAULT
        )
        cursor = self.connection.cursor()
        json_state = json.dumps(state.serialize(**self.serde_kwargs))
        try:
            cursor.execute(
                f"INSERT INTO {self.table_name} (partition_key, app_id, sequence_id, position, state, status) "
                f"VALUES (?, ?, ?, ?, ?, ?)",
                (partition_key, app_id, sequence_id, position, json_state, status),
            )
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                raise RuntimeError(
                    _UNINITIALIZED_PERSISTER_ERROR.format(table_name=self.table_name)
                ) from e
            raise
        self.connection.commit()

    def cleanup(self):
        """Closes the connection to the database."""
        self.connection.close()

    def __del__(self):
        # This should be deprecated -- using __del__ is unreliable for closing connections to db's;
        # the preferred way should be for the user to use a context manager or use the `.cleanup()`
        # method within a REST API framework.

        # closes connection at end when things are being shutdown.
        self.connection.close()

    def __getstate__(self):
        return {key: value for key, value in self.__dict__.items() if key != "connection"}

    def __setstate__(self, state):
        for key, value in state.items():
            setattr(self, key, value)
        self.connection = sqlite3.connect(
            self.db_path, **self._connect_kwargs if self._connect_kwargs is not None else {}
        )


class InMemoryPersister(BaseStatePersister):
    """In-memory persister for testing purposes. This is not recommended for production use."""

    def __init__(self):
        self._storage = defaultdict(lambda: defaultdict(list))

    def load(
        self, partition_key: str, app_id: Optional[str], sequence_id: Optional[int] = None, **kwargs
    ) -> Optional[PersistedStateData]:
        # If no app_id provided, return None
        if app_id is None:
            return None

        if not (states := self._storage[partition_key][app_id]):
            return None

        if sequence_id is None:
            return states[-1]

        # Find states matching the specific sequence_id
        matching_states = [state for state in states if state["sequence_id"] == sequence_id]

        # Return the latest state for this sequence_id, if exists
        return matching_states[-1] if matching_states else None

    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        return list(self._storage[partition_key].keys())

    def save(
        self,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int,
        position: str,
        state: State,
        status: Literal["completed", "failed"],
        **kwargs,
    ):
        # Create a PersistedStateData entry
        persisted_state: PersistedStateData = {
            "partition_key": partition_key or "",
            "app_id": app_id,
            "sequence_id": sequence_id,
            "position": position,
            "state": state,
            "created_at": datetime.datetime.now().isoformat(),
            "status": status,
        }

        # Store the state
        self._storage[partition_key][app_id].append(persisted_state)


class AsyncInMemoryPersister(AsyncBaseStatePersister):
    """Sync in-memory persister for testing purposes. This is not recommended for production use."""

    def __init__(self):
        self._storage = defaultdict(lambda: defaultdict(list))

    async def load(
        self, partition_key: str, app_id: Optional[str], sequence_id: Optional[int] = None, **kwargs
    ) -> Optional[PersistedStateData]:
        # If no app_id provided, return None
        if app_id is None:
            return None

        if not (states := self._storage[partition_key][app_id]):
            return None

        if sequence_id is None:
            return states[-1]

        # Find states matching the specific sequence_id
        matching_states = [state for state in states if state["sequence_id"] == sequence_id]

        # Return the latest state for this sequence_id, if exists
        return matching_states[-1] if matching_states else None

    async def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        return list(self._storage[partition_key].keys())

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
        # Create a PersistedStateData entry
        persisted_state: PersistedStateData = {
            "partition_key": partition_key or "",
            "app_id": app_id,
            "sequence_id": sequence_id,
            "position": position,
            "state": state,
            "created_at": datetime.datetime.now().isoformat(),
            "status": status,
        }

        # Store the state
        self._storage[partition_key][app_id].append(persisted_state)


SQLLitePersister = SQLitePersister

if __name__ == "__main__":
    s = SQLitePersister(db_path=".SQLite.db", table_name="test1")
    s.initialize()
    s.save("pk", "app_id", 1, "pos", State({"a": 1, "b": 2}), "completed")
    print(s.list_app_ids("pk"))
    print(s.load("pk", "app_id"))
