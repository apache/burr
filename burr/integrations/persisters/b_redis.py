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

from burr.core import persistence, state

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

    PARTITION_KEY_DEFAULT = ""

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

    def list_app_ids(self, partition_key: Optional[str], **kwargs) -> list[str]:
        """List the app ids for a given partition key."""
        if partition_key is None:
            partition_key = self.PARTITION_KEY_DEFAULT
        namespaced_partition_key = add_namespace_to_partition_key(partition_key, self.namespace)
        app_ids = self.connection.zrevrange(namespaced_partition_key, 0, -1)
        return [app_id.decode() for app_id in app_ids]

    def load(
        self, partition_key: Optional[str], app_id: str, sequence_id: int = None, **kwargs
    ) -> Optional[persistence.PersistedStateData]:
        """Load the state data for a given partition key, app id, and sequence id.

        If the sequence id is not given, it will be looked up in the Redis database. If it is not found, None will be returned.

        :param partition_key:
        :param app_id:
        :param sequence_id:
        :param kwargs:
        :return: Value or None.
        """
        if partition_key is None:
            partition_key = self.PARTITION_KEY_DEFAULT
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
        partition_key: Optional[str],
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
        if partition_key is None:
            partition_key = self.PARTITION_KEY_DEFAULT
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

    PARTITION_KEY_DEFAULT = ""

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

    async def list_app_ids(self, partition_key: Optional[str], **kwargs) -> list[str]:
        """List the app ids for a given partition key."""
        if partition_key is None:
            partition_key = self.PARTITION_KEY_DEFAULT
        namespaced_partition_key = add_namespace_to_partition_key(partition_key, self.namespace)
        app_ids = await self.connection.zrevrange(namespaced_partition_key, 0, -1)
        return [app_id.decode() for app_id in app_ids]

    async def load(
        self, partition_key: Optional[str], app_id: str, sequence_id: int = None, **kwargs
    ) -> Optional[persistence.PersistedStateData]:
        """Load the state data for a given partition key, app id, and sequence id.

        If the sequence id is not given, it will be looked up in the Redis database. If it is not found, None will be returned.

        :param partition_key:
        :param app_id:
        :param sequence_id:
        :param kwargs:
        :return: Value or None.
        """
        if partition_key is None:
            partition_key = self.PARTITION_KEY_DEFAULT
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
        partition_key: Optional[str],
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
        if partition_key is None:
            partition_key = self.PARTITION_KEY_DEFAULT
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
