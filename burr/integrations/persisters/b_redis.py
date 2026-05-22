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
    import redis  # can't name module redis because this import wouldn't work.
    import redis.asyncio as aredis

except ImportError as e:
    base.require_plugin(e, "redis")

import json
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from burr.core import persistence, serde, state
from burr.core.durable import JournalEntry, SuspensionRecord

logger = logging.getLogger(__name__)


def add_namespace_to_partition_key(partition_key: str, namespace: Optional[str] = None) -> str:
    """Helper function to add namespace to partition key."""

    if namespace:
        return f"{namespace}:{partition_key}"
    return partition_key


class RedisBasePersister(persistence.BaseStatePersister):
    """Main class for Redis persister.

    Use this class if you want to directly control injecting the Redis client.

    This class is responsible for persisting state data to a Redis database.
    It inherits from the BaseStatePersister class.

    Note: We didn't create the right constructor for the initial implementation of the RedisPersister class,
    so this is an attempt to fix that in a backwards compatible way.
    """

    @classmethod
    def from_config(cls, config: dict) -> "RedisBasePersister":
        """Creates a new instance of the RedisBasePersister from a configuration dictionary."""
        return cls.from_values(**config)

    @classmethod
    def from_values(
        cls,
        host: str,
        port: int,
        db: int,
        password: str = None,
        serde_kwargs: dict = None,
        redis_client_kwargs: dict = None,
        namespace: str = None,
    ) -> "RedisBasePersister":
        """Creates a new instance of the RedisBasePersister from passed in values."""
        if redis_client_kwargs is None:
            redis_client_kwargs = {}
        connection = redis.Redis(
            host=host, port=port, db=db, password=password, **redis_client_kwargs
        )
        return cls(connection, serde_kwargs, namespace)

    def __init__(
        self,
        connection,
        serde_kwargs: dict = None,
        namespace: str = None,
    ):
        """Initializes the RedisPersister class.

        :param connection: the redis connection object.
        :param serde_kwargs: serialization and deserialization keyword arguments to pass to state SERDE.
        :param namespace: The name of the project to optionally use in the key prefix.
        """
        self.connection = connection
        self.serde_kwargs = serde_kwargs or {}
        self.namespace = namespace if namespace else ""

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
        namespaced_partition_key = add_namespace_to_partition_key(partition_key, self.namespace)
        app_ids = self.connection.zrevrange(namespaced_partition_key, 0, -1)
        return [app_id.decode() for app_id in app_ids]

    def load(
        self, partition_key: str, app_id: str, sequence_id: int = None, **kwargs
    ) -> Optional[persistence.PersistedStateData]:
        """Load the state data for a given partition key, app id, and sequence id.

        If the sequence id is not given, it will be looked up in the Redis database. If it is not found, None will be returned.

        :param partition_key:
        :param app_id:
        :param sequence_id:
        :param kwargs:
        :return: Value or None.
        """
        namespaced_partition_key = add_namespace_to_partition_key(partition_key, self.namespace)
        if sequence_id is None:
            sequence_id = self.connection.zscore(namespaced_partition_key, app_id)
            if sequence_id is None:
                return None
            sequence_id = int(sequence_id)
        key = self.create_key(app_id, partition_key, sequence_id)
        data = self.connection.hgetall(key)
        if not data:
            return None
        _state = state.State.deserialize(json.loads(data[b"state"].decode()), **self.serde_kwargs)
        return {
            "partition_key": partition_key,
            "app_id": app_id,
            "sequence_id": sequence_id,
            "position": data[b"position"].decode(),
            "state": _state,
            "created_at": data[b"created_at"].decode(),
            "status": data[b"status"].decode(),
        }

    def create_key(self, app_id, partition_key, sequence_id):
        """Create a key for the Redis database."""
        return add_namespace_to_partition_key(
            f"{partition_key}:{app_id}:{sequence_id}", self.namespace
        )

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
        """Save the state data to the Redis database.

        :param partition_key:
        :param app_id:
        :param sequence_id:
        :param position:
        :param state:
        :param status:
        :param kwargs:
        :return:
        """
        key = self.create_key(app_id, partition_key, sequence_id)
        if self.connection.exists(key):
            raise ValueError(f"partition_key:app_id:sequence_id[{key}] already exists.")
        json_state = json.dumps(state.serialize(**self.serde_kwargs))
        self.connection.hset(
            key,
            mapping={
                "partition_key": partition_key,
                "app_id": app_id,
                "sequence_id": sequence_id,
                "position": position,
                "state": json_state,
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        namespaced_partition_key = add_namespace_to_partition_key(partition_key, self.namespace)
        self.connection.zadd(namespaced_partition_key, {app_id: sequence_id})

    # ------------------------------------------------------------------
    # Durable-execution helpers
    # ------------------------------------------------------------------

    def _partition_key_safe(self, partition_key: Optional[str]) -> str:
        """Return a Redis-key-safe representation of partition_key."""
        return "__none__" if partition_key is None else partition_key

    def _suspension_hash_key(self, partition_key: Optional[str], app_id: str, channel: str) -> str:
        pk = self._partition_key_safe(partition_key)
        return f"burr:suspension:{pk}:{app_id}:{channel}"

    def _journal_list_key(
        self, partition_key: Optional[str], app_id: str, sequence_id: int
    ) -> str:
        pk = self._partition_key_safe(partition_key)
        return f"burr:journal:{pk}:{app_id}:{sequence_id}"

    # ------------------------------------------------------------------
    # Durable-execution methods
    # ------------------------------------------------------------------

    def save_suspension(self, record: SuspensionRecord) -> None:
        """Persist a SuspensionRecord to a Redis HASH.

        Also writes a secondary index key so ``mark_suspension_resolved``
        can locate the hash by ``suspension_id`` alone.

        The hash ``resolved`` field stores a literal string and is updated
        by ``mark_suspension_resolved``; callers must use ``load_suspension``
        to get the authoritative ``resolved`` state (backed by the SETNX key).
        """
        hash_key = self._suspension_hash_key(
            record.partition_key, record.app_id, record.channel
        )
        self.connection.hset(
            hash_key,
            mapping={
                "suspension_id": record.suspension_id,
                "partition_key": json.dumps(record.partition_key),
                "app_id": record.app_id,
                "sequence_id": str(record.sequence_id),
                "position": record.position,
                "channel": record.channel,
                "schema_json": json.dumps(record.schema_json),
                "metadata_json": json.dumps(
                    serde.serialize(record.metadata, **self.serde_kwargs)
                ),
                "inputs_json": json.dumps(
                    serde.serialize(record.inputs, **self.serde_kwargs)
                ),
                "state_json": json.dumps(
                    serde.serialize(record.state, **self.serde_kwargs)
                ),
                "created_at": record.created_at,
                "resolved": "true" if record.resolved else "false",
            },
        )
        # Secondary index: suspension_id -> hash key, for mark_suspension_resolved
        self.connection.set(f"burr:suspension_id_idx:{record.suspension_id}", hash_key)

    def load_suspension(
        self, partition_key: Optional[str], app_id: str, channel: str
    ) -> Optional[SuspensionRecord]:
        """Load the suspension record for (partition_key, app_id, channel).

        Returns the record whether or not it is resolved; callers check
        ``record.resolved`` for resume-once idempotency. Returns ``None``
        when no record exists.

        The ``resolved`` flag is determined by the existence of the SETNX
        key ``burr:resolved:{suspension_id}`` rather than the hash field.
        """
        hash_key = self._suspension_hash_key(partition_key, app_id, channel)
        data = self.connection.hgetall(hash_key)
        if not data:
            return None
        suspension_id = data[b"suspension_id"].decode()
        resolved = bool(self.connection.exists(f"burr:resolved:{suspension_id}"))
        return SuspensionRecord(
            suspension_id=suspension_id,
            partition_key=json.loads(data[b"partition_key"].decode()),
            app_id=data[b"app_id"].decode(),
            sequence_id=int(data[b"sequence_id"].decode()),
            position=data[b"position"].decode(),
            channel=data[b"channel"].decode(),
            schema_json=json.loads(data[b"schema_json"].decode()),
            metadata=serde.deserialize(
                json.loads(data[b"metadata_json"].decode()), **self.serde_kwargs
            ),
            inputs=serde.deserialize(
                json.loads(data[b"inputs_json"].decode()), **self.serde_kwargs
            ),
            state=serde.deserialize(
                json.loads(data[b"state_json"].decode()), **self.serde_kwargs
            ),
            created_at=data[b"created_at"].decode(),
            resolved=resolved,
        )

    def mark_suspension_resolved(self, suspension_id: str) -> bool:
        """Mark a suspension consumed. Atomic SETNX for resume-once idempotency.

        :return: True if this call performed the first flip, False if already
            resolved or the suspension_id is unknown.
        """
        if self.connection.setnx(f"burr:resolved:{suspension_id}", 1):
            # Update the hash field so load_suspension reflects the resolved state
            # without requiring an EXISTS check for callers who read the hash directly.
            hash_key_bytes = self.connection.get(f"burr:suspension_id_idx:{suspension_id}")
            if hash_key_bytes is not None:
                self.connection.hset(hash_key_bytes.decode(), "resolved", "true")
            return True
        return False

    def save_journal_entry(self, entry: JournalEntry) -> None:
        """Persist one memoized sub-step to a Redis LIST.

        Upserts by step_key: scans for an existing entry with the same
        step_key and replaces it via LSET if found; otherwise appends with
        RPUSH.  Journals are short so the linear scan is acceptable.
        """
        list_key = self._journal_list_key(entry.partition_key, entry.app_id, entry.sequence_id)
        serialized = json.dumps(
            {
                "partition_key": json.dumps(entry.partition_key),
                "app_id": entry.app_id,
                "sequence_id": entry.sequence_id,
                "step_key": entry.step_key,
                "call_index": entry.call_index,
                "result_json": json.dumps(serde.serialize(entry.result, **self.serde_kwargs)),
            }
        )
        existing = self.connection.lrange(list_key, 0, -1)
        for idx, raw in enumerate(existing):
            item = json.loads(raw.decode())
            if item.get("step_key") == entry.step_key:
                self.connection.lset(list_key, idx, serialized)
                return
        self.connection.rpush(list_key, serialized)

    def load_journal(
        self, partition_key: Optional[str], app_id: str, sequence_id: int
    ) -> list[JournalEntry]:
        """Load journal entries for a suspended action, sorted by call_index."""
        list_key = self._journal_list_key(partition_key, app_id, sequence_id)
        raw_entries = self.connection.lrange(list_key, 0, -1)
        entries = []
        for raw in raw_entries:
            item = json.loads(raw.decode())
            entries.append(
                JournalEntry(
                    partition_key=json.loads(item["partition_key"]),
                    app_id=item["app_id"],
                    sequence_id=item["sequence_id"],
                    step_key=item["step_key"],
                    call_index=item["call_index"],
                    result=serde.deserialize(
                        json.loads(item["result_json"]), **self.serde_kwargs
                    ),
                )
            )
        entries.sort(key=lambda e: e.call_index)
        return entries

    def cleanup(self):
        """Closes the connection to the database."""
        self.connection.close()

    def __del__(self):
        # This should be deprecated -- using __del__ is unreliable for closing connections to db's;
        # the preferred way should be for the user to use a context manager or use the `.cleanup()`
        # method within a REST API framework.

        self.connection.close()

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["connection_params"] = {
            "host": self.connection.connection_pool.connection_kwargs["host"],
            "port": self.connection.connection_pool.connection_kwargs["port"],
            "db": self.connection.connection_pool.connection_kwargs["db"],
            "password": self.connection.connection_pool.connection_kwargs["password"],
        }
        del state["connection"]
        return state

    def __setstate__(self, state: dict):
        connection_params = state.pop("connection_params")
        # we assume normal redis client.
        self.connection = redis.Redis(**connection_params)
        self.__dict__.update(state)


class AsyncRedisBasePersister(persistence.AsyncBaseStatePersister):
    """Main class for async Redis persister.

    .. warning::
        The synchronous persister closes the connection on deletion of the class using the ``__del__`` method.
        In an async context that is not reliable (the event loop may already be closed by the time ``__del__``
        gets invoked). Therefore, you are responsible for closing the connection yourself (i.e. manual cleanup).
        We suggest to use the persister either as a context manager through the ``async with`` clause or
        using the method ``.cleanup()``.


    This class is responsible for async persisting state data to a Redis database.
    It inherits from the AsyncBaseStatePersister class.
    """

    @classmethod
    def from_config(cls, config: dict) -> "AsyncRedisBasePersister":
        """Creates a new instance of the RedisBasePersister from a configuration dictionary."""
        return cls.from_values(**config)

    @classmethod
    def from_values(
        cls,
        host: str,
        port: int,
        db: int,
        password: str = None,
        serde_kwargs: dict = None,
        redis_client_kwargs: dict = None,
        namespace: str = None,
    ) -> "AsyncRedisBasePersister":
        """Creates a new instance of the AsyncRedisBasePersister from passed in values."""
        if redis_client_kwargs is None:
            redis_client_kwargs = {}
        connection = aredis.Redis(
            host=host, port=port, db=db, password=password, **redis_client_kwargs
        )
        return cls(connection, serde_kwargs, namespace)

    def __init__(
        self,
        connection,
        serde_kwargs: dict = None,
        namespace: str = None,
    ):
        """Initializes the AsyncRedisPersister class.

        :param connection: the redis connection object.
        :param serde_kwargs: serialization and deserialization keyword arguments to pass to state SERDE.
        :param namespace: The name of the project to optionally use in the key prefix.
        """
        self.connection = connection
        self.serde_kwargs = serde_kwargs or {}
        self.namespace = namespace if namespace else ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.connection.aclose()
        return False

    def set_serde_kwargs(self, serde_kwargs: dict):
        """Sets the serde_kwargs for the persister."""
        self.serde_kwargs = serde_kwargs

    async def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        """List the app ids for a given partition key."""
        namespaced_partition_key = add_namespace_to_partition_key(partition_key, self.namespace)
        app_ids = await self.connection.zrevrange(namespaced_partition_key, 0, -1)
        return [app_id.decode() for app_id in app_ids]

    async def load(
        self, partition_key: str, app_id: str, sequence_id: int = None, **kwargs
    ) -> Optional[persistence.PersistedStateData]:
        """Load the state data for a given partition key, app id, and sequence id.

        If the sequence id is not given, it will be looked up in the Redis database. If it is not found, None will be returned.

        :param partition_key:
        :param app_id:
        :param sequence_id:
        :param kwargs:
        :return: Value or None.
        """
        namespaced_partition_key = add_namespace_to_partition_key(partition_key, self.namespace)
        if sequence_id is None:
            sequence_id = await self.connection.zscore(namespaced_partition_key, app_id)
            if sequence_id is None:
                return None
            sequence_id = int(sequence_id)
        key = self.create_key(app_id, partition_key, sequence_id)
        data = await self.connection.hgetall(key)
        if not data:
            return None
        _state = state.State.deserialize(json.loads(data[b"state"].decode()), **self.serde_kwargs)
        return {
            "partition_key": partition_key,
            "app_id": app_id,
            "sequence_id": sequence_id,
            "position": data[b"position"].decode(),
            "state": _state,
            "created_at": data[b"created_at"].decode(),
            "status": data[b"status"].decode(),
        }

    def create_key(self, app_id, partition_key, sequence_id):
        """Create a key for the Redis database."""
        return add_namespace_to_partition_key(
            f"{partition_key}:{app_id}:{sequence_id}", self.namespace
        )

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
        """Save the state data to the Redis database.

        :param partition_key:
        :param app_id:
        :param sequence_id:
        :param position:
        :param state:
        :param status:
        :param kwargs:
        :return:
        """
        key = self.create_key(app_id, partition_key, sequence_id)
        if await self.connection.exists(key):
            raise ValueError(f"partition_key:app_id:sequence_id[{key}] already exists.")
        json_state = json.dumps(state.serialize(**self.serde_kwargs))
        await self.connection.hset(
            key,
            mapping={
                "partition_key": partition_key,
                "app_id": app_id,
                "sequence_id": sequence_id,
                "position": position,
                "state": json_state,
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        namespaced_partition_key = add_namespace_to_partition_key(partition_key, self.namespace)
        await self.connection.zadd(namespaced_partition_key, {app_id: sequence_id})

    # ------------------------------------------------------------------
    # Durable-execution helpers (async)
    # ------------------------------------------------------------------

    def _partition_key_safe(self, partition_key: Optional[str]) -> str:
        """Return a Redis-key-safe representation of partition_key."""
        return "__none__" if partition_key is None else partition_key

    def _suspension_hash_key(self, partition_key: Optional[str], app_id: str, channel: str) -> str:
        pk = self._partition_key_safe(partition_key)
        return f"burr:suspension:{pk}:{app_id}:{channel}"

    def _journal_list_key(
        self, partition_key: Optional[str], app_id: str, sequence_id: int
    ) -> str:
        pk = self._partition_key_safe(partition_key)
        return f"burr:journal:{pk}:{app_id}:{sequence_id}"

    # ------------------------------------------------------------------
    # Durable-execution methods (async)
    # ------------------------------------------------------------------

    async def save_suspension(self, record: SuspensionRecord) -> None:
        """Persist a SuspensionRecord to a Redis HASH (async).

        Also writes a secondary index key so ``mark_suspension_resolved``
        can locate the hash by ``suspension_id`` alone.
        """
        hash_key = self._suspension_hash_key(
            record.partition_key, record.app_id, record.channel
        )
        await self.connection.hset(
            hash_key,
            mapping={
                "suspension_id": record.suspension_id,
                "partition_key": json.dumps(record.partition_key),
                "app_id": record.app_id,
                "sequence_id": str(record.sequence_id),
                "position": record.position,
                "channel": record.channel,
                "schema_json": json.dumps(record.schema_json),
                "metadata_json": json.dumps(
                    serde.serialize(record.metadata, **self.serde_kwargs)
                ),
                "inputs_json": json.dumps(
                    serde.serialize(record.inputs, **self.serde_kwargs)
                ),
                "state_json": json.dumps(
                    serde.serialize(record.state, **self.serde_kwargs)
                ),
                "created_at": record.created_at,
                "resolved": "true" if record.resolved else "false",
            },
        )
        await self.connection.set(
            f"burr:suspension_id_idx:{record.suspension_id}", hash_key
        )

    async def load_suspension(
        self, partition_key: Optional[str], app_id: str, channel: str
    ) -> Optional[SuspensionRecord]:
        """Load the suspension record for (partition_key, app_id, channel) (async).

        Returns the record whether or not it is resolved; callers check
        ``record.resolved`` for resume-once idempotency. Returns ``None``
        when no record exists.
        """
        hash_key = self._suspension_hash_key(partition_key, app_id, channel)
        data = await self.connection.hgetall(hash_key)
        if not data:
            return None
        suspension_id = data[b"suspension_id"].decode()
        resolved = bool(await self.connection.exists(f"burr:resolved:{suspension_id}"))
        return SuspensionRecord(
            suspension_id=suspension_id,
            partition_key=json.loads(data[b"partition_key"].decode()),
            app_id=data[b"app_id"].decode(),
            sequence_id=int(data[b"sequence_id"].decode()),
            position=data[b"position"].decode(),
            channel=data[b"channel"].decode(),
            schema_json=json.loads(data[b"schema_json"].decode()),
            metadata=serde.deserialize(
                json.loads(data[b"metadata_json"].decode()), **self.serde_kwargs
            ),
            inputs=serde.deserialize(
                json.loads(data[b"inputs_json"].decode()), **self.serde_kwargs
            ),
            state=serde.deserialize(
                json.loads(data[b"state_json"].decode()), **self.serde_kwargs
            ),
            created_at=data[b"created_at"].decode(),
            resolved=resolved,
        )

    async def mark_suspension_resolved(self, suspension_id: str) -> bool:
        """Mark a suspension consumed. Atomic SETNX for resume-once idempotency (async).

        :return: True if this call performed the first flip, False if already resolved.
        """
        if await self.connection.setnx(f"burr:resolved:{suspension_id}", 1):
            hash_key_bytes = await self.connection.get(
                f"burr:suspension_id_idx:{suspension_id}"
            )
            if hash_key_bytes is not None:
                await self.connection.hset(hash_key_bytes.decode(), "resolved", "true")
            return True
        return False

    async def save_journal_entry(self, entry: JournalEntry) -> None:
        """Persist one memoized sub-step to a Redis LIST (async).

        Upserts by step_key: scans for an existing entry with the same
        step_key and replaces it via LSET if found; otherwise appends.
        """
        list_key = self._journal_list_key(entry.partition_key, entry.app_id, entry.sequence_id)
        serialized = json.dumps(
            {
                "partition_key": json.dumps(entry.partition_key),
                "app_id": entry.app_id,
                "sequence_id": entry.sequence_id,
                "step_key": entry.step_key,
                "call_index": entry.call_index,
                "result_json": json.dumps(serde.serialize(entry.result, **self.serde_kwargs)),
            }
        )
        existing = await self.connection.lrange(list_key, 0, -1)
        for idx, raw in enumerate(existing):
            item = json.loads(raw.decode())
            if item.get("step_key") == entry.step_key:
                await self.connection.lset(list_key, idx, serialized)
                return
        await self.connection.rpush(list_key, serialized)

    async def load_journal(
        self, partition_key: Optional[str], app_id: str, sequence_id: int
    ) -> list[JournalEntry]:
        """Load journal entries for a suspended action, sorted by call_index (async)."""
        list_key = self._journal_list_key(partition_key, app_id, sequence_id)
        raw_entries = await self.connection.lrange(list_key, 0, -1)
        entries = []
        for raw in raw_entries:
            item = json.loads(raw.decode())
            entries.append(
                JournalEntry(
                    partition_key=json.loads(item["partition_key"]),
                    app_id=item["app_id"],
                    sequence_id=item["sequence_id"],
                    step_key=item["step_key"],
                    call_index=item["call_index"],
                    result=serde.deserialize(
                        json.loads(item["result_json"]), **self.serde_kwargs
                    ),
                )
            )
        entries.sort(key=lambda e: e.call_index)
        return entries

    async def cleanup(self):
        """Closes the connection to the database."""
        await self.connection.aclose()


class RedisPersister(RedisBasePersister):
    """A class used to represent a Redis Persister.

    This class is deprecated. Use RedisBasePersister.from_values() instead.
    """

    def __init__(
        self,
        host: str,
        port: int,
        db: int,
        password: str = None,
        serde_kwargs: dict = None,
        redis_client_kwargs: dict = None,
        namespace: str = None,
    ):
        """Initializes the RedisPersister class.

        This is deprecated. Use RedisBasePersister.from_values() instead.

        :param host:
        :param port:
        :param db:
        :param password:
        :param serde_kwargs:
        :param redis_client_kwargs: Additional keyword arguments to pass to the redis.Redis client.
        :param namespace: The name of the project to optionally use in the key prefix.
        """
        if redis_client_kwargs is None:
            redis_client_kwargs = {}
        connection = redis.Redis(
            host=host, port=port, db=db, password=password, **redis_client_kwargs
        )
        super(RedisPersister, self).__init__(connection, serde_kwargs, namespace)


if __name__ == "__main__":
    # test the RedisBasePersister class
    persister = RedisBasePersister.from_values("localhost", 6379, 0)

    persister.initialize()
    persister.save("pk", "app_id", 2, "pos", state.State({"a": 1, "b": 2}), "completed")
    print(persister.list_app_ids("pk"))
    print(persister.load("pk", "app_id"))
