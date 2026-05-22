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
from typing import Literal, Optional

from pymongo import ASCENDING, DESCENDING, MongoClient

from burr.core import persistence, serde, state
from burr.core.durable import JournalEntry, SuspensionRecord

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
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]
        self.serde_kwargs = serde_kwargs or {}

    def initialize(self):
        """Creates indexes for the state collection and the two durable-execution
        collections (``burr_suspensions`` and ``burr_journal``).

        Index creation in MongoDB is idempotent — calling this multiple times
        is safe.
        """
        self.db["burr_suspensions"].create_index(
            [
                ("partition_key", ASCENDING),
                ("app_id", ASCENDING),
                ("channel", ASCENDING),
                ("created_at", DESCENDING),
            ]
        )
        self.db["burr_journal"].create_index(
            [
                ("partition_key", ASCENDING),
                ("app_id", ASCENDING),
                ("sequence_id", ASCENDING),
                ("step_key", ASCENDING),
            ],
            unique=True,
        )

    def save_suspension(self, record: SuspensionRecord) -> None:
        """Persist a suspension record into the ``burr_suspensions`` collection."""
        doc = {
            "_id": record.suspension_id,
            "suspension_id": record.suspension_id,
            "partition_key": record.partition_key,
            "app_id": record.app_id,
            "sequence_id": record.sequence_id,
            "position": record.position,
            "channel": record.channel,
            "schema_json": record.schema_json,
            "metadata": serde.serialize(record.metadata, **self.serde_kwargs)
            if record.metadata is not None
            else None,
            "inputs": serde.serialize(record.inputs, **self.serde_kwargs),
            "state": serde.serialize(record.state, **self.serde_kwargs),
            "created_at": record.created_at,
            "resolved": record.resolved,
        }
        self.db["burr_suspensions"].update_one(
            {"_id": record.suspension_id},
            {"$set": doc},
            upsert=True,
        )

    def load_suspension(
        self, partition_key: Optional[str], app_id: str, channel: str
    ) -> Optional[SuspensionRecord]:
        """Load the most recent suspension record for (partition_key, app_id, channel).

        Returns the record whether or not it is resolved; callers check
        ``record.resolved`` for resume-once idempotency. Returns ``None``
        when no record exists for this combination.
        """
        doc = self.db["burr_suspensions"].find_one(
            {"partition_key": partition_key, "app_id": app_id, "channel": channel},
            sort=[("created_at", DESCENDING)],
        )
        if doc is None:
            return None
        return SuspensionRecord(
            suspension_id=doc["suspension_id"],
            partition_key=doc["partition_key"],
            app_id=doc["app_id"],
            sequence_id=doc["sequence_id"],
            position=doc["position"],
            channel=doc["channel"],
            schema_json=doc.get("schema_json"),
            metadata=serde.deserialize(doc["metadata"], **self.serde_kwargs)
            if doc.get("metadata") is not None
            else None,
            inputs=serde.deserialize(doc["inputs"], **self.serde_kwargs),
            state=serde.deserialize(doc["state"], **self.serde_kwargs),
            created_at=doc["created_at"],
            resolved=bool(doc["resolved"]),
        )

    def mark_suspension_resolved(self, suspension_id: str) -> bool:
        """Mark a suspension consumed. Conditional update for resume-once idempotency.

        :return: ``True`` if a document was updated (first call), ``False`` if
                 already resolved or not found (no-op).
        """
        result = self.db["burr_suspensions"].update_one(
            {"_id": suspension_id, "resolved": False},
            {"$set": {"resolved": True}},
        )
        return result.modified_count == 1

    def save_journal_entry(self, entry: JournalEntry) -> None:
        """Persist one memoized sub-step into the ``burr_journal`` collection."""
        filter_doc = {
            "partition_key": entry.partition_key,
            "app_id": entry.app_id,
            "sequence_id": entry.sequence_id,
            "step_key": entry.step_key,
        }
        update_doc = {
            "$set": {
                "partition_key": entry.partition_key,
                "app_id": entry.app_id,
                "sequence_id": entry.sequence_id,
                "step_key": entry.step_key,
                "call_index": entry.call_index,
                "result": serde.serialize(entry.result, **self.serde_kwargs),
            }
        }
        self.db["burr_journal"].update_one(filter_doc, update_doc, upsert=True)

    def load_journal(
        self, partition_key: Optional[str], app_id: str, sequence_id: int
    ) -> list[JournalEntry]:
        """Load journal entries for a suspended action, ordered by call_index."""
        cursor = self.db["burr_journal"].find(
            {"partition_key": partition_key, "app_id": app_id, "sequence_id": sequence_id}
        ).sort("call_index", ASCENDING)
        return [
            JournalEntry(
                partition_key=doc["partition_key"],
                app_id=doc["app_id"],
                sequence_id=doc["sequence_id"],
                step_key=doc["step_key"],
                call_index=doc["call_index"],
                result=serde.deserialize(doc["result"], **self.serde_kwargs),
            )
            for doc in cursor
        ]

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
        self.client = MongoClient(connection_params["uri"], connection_params["port"])
        self.db = self.client[connection_params["db_name"]]
        self.collection = self.db[connection_params["collection_name"]]
        self.__dict__.update(state)
