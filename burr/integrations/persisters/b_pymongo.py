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
from datetime import datetime, timezone
from importlib.metadata import version as get_version
from typing import Literal, Optional

from pymongo import MongoClient
from pymongo.driver_info import DriverInfo

from burr.core import persistence, state

try:
    _VERSION = get_version("apache-burr")
except Exception:
    _VERSION = None

_DRIVER_INFO = DriverInfo(name="Burr", version=_VERSION)

logger = logging.getLogger(__name__)


class MongoDBBasePersister(persistence.BaseStatePersister):
    """A class used to represent a MongoDB Persister.

    Example usage:

    .. code-block:: python

       persister = MongoDBBasePersister.from_values(uri='mongodb://user:pass@localhost:27017',
                                                    db_name='mydatabase',
                                                    collection_name='mystates')
       persister.save(
           partition_key='example_partition',
           app_id='example_app',
           sequence_id=1,
           position='example_position',
           state=state.State({'key': 'value'}),
           status='completed'
       )
       loaded_state = persister.load(partition_key='example_partition', app_id='example_app', sequence_id=1)
       print(loaded_state)

    Note: this is called MongoDBBasePersister because we had to change the constructor and wanted to make
     this change backwards compatible.
    """

    @classmethod
    def from_config(cls, config: dict) -> "MongoDBBasePersister":
        """Creates a new instance of the MongoDBBasePersister from a configuration dictionary."""
        return cls.from_values(**config)

    @classmethod
    def from_values(
        cls,
        uri="mongodb://localhost:27017",
        db_name="mydatabase",
        collection_name="mystates",
        serde_kwargs: dict = None,
        mongo_client_kwargs: dict = None,
    ) -> "MongoDBBasePersister":
        """Initializes the MongoDBBasePersister class."""
        if mongo_client_kwargs is None:
            mongo_client_kwargs = {}
        mongo_client_kwargs.setdefault("driver", _DRIVER_INFO)
        client = MongoClient(uri, **mongo_client_kwargs)
        return cls(
            client=client,
            db_name=db_name,
            collection_name=collection_name,
            serde_kwargs=serde_kwargs,
        )

    def __init__(
        self,
        client,
        db_name="mydatabase",
        collection_name="mystates",
        serde_kwargs: dict = None,
    ):
        """Initializes the MongoDBBasePersister class.

        :param client: the mongodb client to use
        :param db_name: the name of the database to use
        :param collection_name: the name of the collection to use
        :param serde_kwargs: serializer/deserializer keyword arguments to pass to the state object
        """
        self.client = client
        if hasattr(client, "append_metadata"):
            client.append_metadata(_DRIVER_INFO)
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]
        self.serde_kwargs = serde_kwargs or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.connection.close()
        return False

    def set_serde_kwargs(self, serde_kwargs: dict):
        """Sets the serde_kwargs for the persister."""
        self.serde_kwargs = serde_kwargs

    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        """List the app ids for a given partition key."""
        app_ids = self.collection.distinct("app_id", {"partition_key": partition_key})
        return app_ids

    def load(
        self, partition_key: Optional[str], app_id: str, sequence_id: int = None, **kwargs
    ) -> Optional[persistence.PersistedStateData]:
        """Loads the state data for a given partition key, app_id, and sequence_id.

        This method retrieves the most recent state data for the specified (partition_key, app_id) combination.
        If a sequence ID is provided, it will attempt to fetch the specific state at that sequence.

        :param partition_key: The partition key. Defaults to `None`.
            **Note:** The partition key defaults to `None`. If a partition key was used during saving,
            it must be provided consistently during retrieval, or no results will be returned.
        :param app_id: Application UID to read from.
        :param sequence_id: (Optional) The sequence ID to retrieve a specific state. If not provided,
            the latest state is returned.


        :returns: The state data if found, otherwise None.
        """
        query = {"partition_key": partition_key, "app_id": app_id}
        if sequence_id is not None:
            query["sequence_id"] = sequence_id
        document = self.collection.find_one(query, sort=[("sequence_id", -1)])
        if not document:
            return None
        _state = state.State.deserialize(json.loads(document["state"]), **self.serde_kwargs)
        return {
            "partition_key": partition_key,
            "app_id": app_id,
            "sequence_id": document["sequence_id"],
            "position": document["position"],
            "state": _state,
            "created_at": document["created_at"],
            "status": document["status"],
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
        """Save the state data to the MongoDB database.

        :param partition_key: the partition key. Note this could be None, but it's up to the persistor
                              to whether that is a valid value it can handle. If a partition key was used
                              during saving, it must be provided consistently during retrieval, or no
                              results will be returned.
        :param app_id: Application UID to write with.
        :param sequence_id: Sequence ID of the last executed step.
        :param position: The action name that was implemented.
        :param state: The current state of the application.
        :param status: The status of this state, either "completed" or "failed". If "failed", the state
                       is what it was before the action was applied.

        :return:
        """
        key = {"partition_key": partition_key, "app_id": app_id, "sequence_id": sequence_id}
        if self.collection.find_one(key):
            raise ValueError(f"partition_key:app_id:sequence_id[{key}] already exists.")
        json_state = json.dumps(state.serialize(**self.serde_kwargs))
        self.collection.insert_one(
            {
                "partition_key": partition_key,
                "app_id": app_id,
                "sequence_id": sequence_id,
                "position": position,
                "state": json_state,
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def cleanup(self):
        """Closes the connection to the database."""
        self.connection.close()

    def __del__(self):
        # This should be deprecated -- using __del__ is unreliable for closing connections to db's;
        # the preferred way should be for the user to use a context manager or use the `.cleanup()`
        # method within a REST API framework.

        self.client.close()

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["connection_params"] = {
            "uri": self.client.address[0],
            "port": self.client.address[1],
            "db_name": self.db.name,
            "collection_name": self.collection.name,
        }
        del state["client"]
        del state["db"]
        del state["collection"]
        return state

    def __setstate__(self, state: dict):
        connection_params = state.pop("connection_params")
        # we assume MongoClient.
        self.client = MongoClient(
            connection_params["uri"], connection_params["port"], driver=_DRIVER_INFO
        )
        self.db = self.client[connection_params["db_name"]]
        self.collection = self.db[connection_params["collection_name"]]
        self.__dict__.update(state)
