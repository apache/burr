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
        return cls(connection, table_name)

    def __init__(self, connection, table_name: str = "burr_state", serde_kwargs: dict = None):
        """Constructor

        :param connection: the connection to the PostgreSQL database.
        :param table_name:  the table name to store things under.
        """
        self.table_name = table_name
        self.connection = connection
        self.serde_kwargs = serde_kwargs or {}
        self._initialized = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.connection.close()
        return False

    def set_serde_kwargs(self, serde_kwargs: dict):
        """Sets the serde_kwargs for the persister."""
        self.serde_kwargs = serde_kwargs

    def create_table(self, table_name: str):
        """Helper function to create the table where things are stored."""
        cursor = self.connection.cursor()
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                partition_key TEXT DEFAULT '{self.PARTITION_KEY_DEFAULT}',
                app_id TEXT NOT NULL,
                sequence_id INTEGER NOT NULL,
                position TEXT NOT NULL,
                status TEXT NOT NULL,
                state JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (partition_key, app_id, sequence_id, position)
            )""")
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS {table_name}_created_at_index ON {table_name} (created_at);
        """)
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
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
            (self.table_name,),
        )
        self._initialized = cursor.fetchone()[0]
        return self._initialized

    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        """Lists the app_ids for a given partition_key."""
        cursor = self.connection.cursor()
        cursor.execute(
            f"SELECT DISTINCT app_id, created_at FROM {self.table_name} "
            "WHERE partition_key = %s "
            "ORDER BY created_at DESC",
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
        cursor = self.connection.cursor()
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
        cursor = self.connection.cursor()
        json_state = json.dumps(state.serialize(**self.serde_kwargs))
        cursor.execute(
            f"INSERT INTO {self.table_name} (partition_key, app_id, sequence_id, position, state, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (partition_key, app_id, sequence_id, position, json_state, status),
        )
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
