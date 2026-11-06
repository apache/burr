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

from burr.integrations import base

try:
    import psycopg2
except ImportError as e:
    base.require_plugin(e, "postgresql")

import contextlib
import json
import logging
from typing import Literal, Optional

from burr.core import persistence, state

logger = logging.getLogger(__name__)


class PostgreSQLPersister(persistence.BaseStatePersister):
    """Class for PostgreSQL persistence of state. This is a simple implementation.

    To try it out locally with docker -- here's a command -- change the values as appropriate.

    .. code:: bash

        docker run --name local-psql \  # container name
                   -v local_psql_data:/SOME/FILE_PATH/ \  # mounting a volume for data persistence
                   -p 54320:5432 \  # port mapping
                   -e POSTGRES_PASSWORD=my_password \  # superuser password
                   -d postgres  # database name

    Then you should be able to create the class like this:

    .. code:: python

        p = PostgreSQLPersister.from_values("postgres", "postgres", "my_password",
                                           "localhost", 54320, table_name="burr_state")

    A persister built with ``from_values`` or ``from_config`` owns its connection, so
    ``list_app_ids``, ``load``, ``save`` and an uncached ``is_initialized`` each end their
    transaction: they commit after the database work succeeds and attempt a rollback if it
    raises. A connection passed to the constructor keeps its existing behavior by default: of these
    four, only ``save`` commits, and a failed call leaves the rollback to the caller. Pass
    ``manage_transactions=True`` to get per-call transactions on a connection you give it, which is
    the recommended setup for a connection used only by the persister.
    """

    PARTITION_KEY_DEFAULT = ""

    @classmethod
    def from_config(cls, config: dict) -> "PostgreSQLPersister":
        """Creates a new instance of the PostgreSQLPersister from a configuration dictionary."""
        return cls.from_values(**config)

    @classmethod
    def from_values(
        cls,
        db_name: str,
        user: str,
        password: str,
        host: str,
        port: int,
        table_name: str = "burr_state",
    ):
        """Builds a new instance of the PostgreSQLPersister from the provided values.

        :param db_name: the name of the PostgreSQL database.
        :param user: the username to connect to the PostgreSQL database.
        :param password: the password to connect to the PostgreSQL database.
        :param host: the host of the PostgreSQL database.
        :param port: the port of the PostgreSQL database.
        :param table_name:  the table name to store things under.
        """
        connection = psycopg2.connect(
            dbname=db_name, user=user, password=password, host=host, port=port
        )
        return cls(connection, table_name, manage_transactions=True)

    def __init__(
        self,
        connection,
        table_name: str = "burr_state",
        serde_kwargs: dict = None,
        manage_transactions: bool = False,
    ):
        """Constructor

        :param connection: the connection to the PostgreSQL database.
        :param table_name:  the table name to store things under.
        :param manage_transactions: if True, ``load``, ``list_app_ids``, ``save`` and an uncached
            ``is_initialized`` commit after their database work succeeds and attempt a rollback if
            it raises. Leave it False when the connection also carries your own transaction; then
            reads neither commit nor roll back, ``save`` commits on success, and a failed call
            leaves the rollback to you.
        """
        self.table_name = table_name
        self.connection = connection
        self.serde_kwargs = serde_kwargs or {}
        self.manage_transactions = manage_transactions
        self._initialized = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.connection.close()
        return False

    def set_serde_kwargs(self, serde_kwargs: dict):
        """Sets the serde_kwargs for the persister."""
        self.serde_kwargs = serde_kwargs

    @contextlib.contextmanager
    def _transaction(self, commit: bool = False):
        """Yields a cursor and closes it when the block exits.

        With ``manage_transactions``, it also ends the transaction: commit when the block
        succeeds, and a rollback attempt when it raises, ``KeyboardInterrupt`` included. psycopg2 opens a transaction on the first statement and keeps it open, so
        without this a failed insert leaves the connection in an aborted transaction and a read
        leaves it idle in transaction. This doesn't use ``with self.connection`` because psycopg2
        refuses to re-enter it from a caller's own ``with connection`` block. Without
        ``manage_transactions``, the transaction belongs to the caller and only ``commit=True``
        (used by ``save``) commits it on success.
        """
        if not self.manage_transactions:
            with self.connection.cursor() as cursor:
                yield cursor
            if commit:
                self.connection.commit()
            return
        try:
            with self.connection.cursor() as cursor:
                yield cursor
        except BaseException:
            try:
                self.connection.rollback()
            except Exception:
                # Usually the connection is already gone; the original error is the useful one.
                logger.debug("Rollback after a failed call also failed", exc_info=True)
            raise
        self.connection.commit()

    def create_table(self, table_name: str):
        """Helper function to create the table where things are stored."""
        with self.connection.cursor() as cursor:
            cursor.execute(
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
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {table_name}_created_at_index ON {table_name} (created_at);
            """
            )
        self.connection.commit()

    def initialize(self):
        """Creates the table"""
        self.create_table(self.table_name)
        self._initialized = True

    def is_initialized(self) -> bool:
        """This checks to see if the table has been created in the database or not.
        It defaults to using the initialized field, else queries the database to see if the table exists.
        It then sets the initialized field to True if the table exists.
        """
        if self._initialized:
            return True
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
                (self.table_name,),
            )
            self._initialized = cursor.fetchone()[0]
        return self._initialized

    def list_app_ids(self, partition_key: Optional[str], **kwargs) -> list[str]:
        """Lists the app_ids for a given partition_key, each once, most recently saved first."""
        if partition_key is None:
            partition_key = self.PARTITION_KEY_DEFAULT
        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT app_id FROM {self.table_name} "
                "WHERE partition_key = %s "
                "GROUP BY app_id "
                "ORDER BY MAX(created_at) DESC",
                (partition_key,),
            )
            app_ids = [row[0] for row in cursor.fetchall()]
        return app_ids

    def load(
        self, partition_key: Optional[str], app_id: str, sequence_id: int = None, **kwargs
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
        with self._transaction() as cursor:
            if app_id is None:
                # get latest for all app_ids
                cursor.execute(
                    f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                    f"WHERE partition_key = %s "
                    f"ORDER BY CREATED_AT DESC LIMIT 1",
                    (partition_key,),
                )
            elif sequence_id is None:
                cursor.execute(
                    f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                    f"WHERE partition_key = %s AND app_id = %s "
                    f"ORDER BY sequence_id DESC LIMIT 1",
                    (partition_key, app_id),
                )
            else:
                cursor.execute(
                    f"SELECT position, state, sequence_id, app_id, created_at, status FROM {self.table_name} "
                    f"WHERE partition_key = %s AND app_id = %s AND sequence_id = %s ",
                    (partition_key, app_id, sequence_id),
                )
            row = cursor.fetchone()
        if row is None:
            return None
        _state = state.State.deserialize(row[1], **self.serde_kwargs)
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
        if partition_key is None:
            partition_key = self.PARTITION_KEY_DEFAULT
        logger.debug(
            "saving %s, %s, %s, %s, %s, %s",
            partition_key,
            app_id,
            sequence_id,
            position,
            state,
            status,
        )
        json_state = json.dumps(state.serialize(**self.serde_kwargs))
        with self._transaction(commit=True) as cursor:
            cursor.execute(
                f"INSERT INTO {self.table_name} (partition_key, app_id, sequence_id, position, state, status) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (partition_key, app_id, sequence_id, position, json_state, status),
            )

    def cleanup(self):
        """Closes the connection to the database."""
        self.connection.close()

    def __del__(self):
        # This should be deprecated -- using __del__ is unreliable for closing connections to db's;
        # the preferred way should be for the user to use a context manager or use the `.cleanup()`
        # method within a REST API framework.

        # closes connection at end when things are being shutdown.
        self.connection.close()

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        if not hasattr(self.connection, "info"):
            logger.warning(
                "Postgresql information for connection object not available. Cannot serialize persister."
            )
            return state
        state["connection_params"] = {
            "dbname": self.connection.info.dbname,
            "user": self.connection.info.user,
            "password": self.connection.info.password,
            "host": self.connection.info.host,
            "port": self.connection.info.port,
        }
        del state["connection"]
        return state

    def __setstate__(self, state: dict):
        connection_params = state.pop("connection_params")
        # Persisters pickled before manage_transactions existed never managed transactions.
        state.setdefault("manage_transactions", False)
        # we assume normal psycopg2 client.
        self.connection = psycopg2.connect(**connection_params)
        self.__dict__.update(state)


if __name__ == "__main__":
    # test the PostgreSQLPersister class
    persister = PostgreSQLPersister.from_values(
        "postgres", "postgres", "my_password", "localhost", 54320, table_name="burr_state"
    )

    persister.initialize()
    persister.save("pk", "app_id", 1, "pos", state.State({"a": 1, "b": 2}), "completed")
    print(persister.list_app_ids("pk"))
    print(persister.load("pk", "app_id"))
