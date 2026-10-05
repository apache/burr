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

import pytest

from burr.core import state
from burr.integrations.persisters.b_redis import (
    AsyncRedisBasePersister,
    RedisBasePersister,
    RedisPersister,
)

if not os.environ.get("BURR_CI_INTEGRATION_TESTS") == "true":
    pytest.skip("Skipping integration tests", allow_module_level=True)


@pytest.fixture
def redis_persister():
    persister = RedisBasePersister.from_values(host="localhost", port=6379, db=0)
    yield persister
    persister.cleanup()


@pytest.fixture
def redis_persister_with_ns():
    persister = RedisBasePersister.from_values(host="localhost", port=6379, db=0, namespace="test")
    yield persister
    persister.cleanup()


def test_save_and_load_state(redis_persister):
    redis_persister.save("pk", "app_id", 1, "pos", state.State({"a": 1, "b": 2}), "completed")
    data = redis_persister.load("pk", "app_id", 1)
    assert data["state"].get_all() == {"a": 1, "b": 2}


def test_save_and_load_with_default_partition_key(redis_persister):
    """An application without a partition key saves and loads with partition_key=None."""
    redis_persister.save(None, "no_pk_app", 1, "pos", state.State({"a": 1}), "completed")
    data = redis_persister.load(None, "no_pk_app")
    assert data["state"].get_all() == {"a": 1}
    # None is stored under the default partition key, so it reads back as "" as well
    assert data["partition_key"] == ""
    assert redis_persister.load("", "no_pk_app")["sequence_id"] == 1
    assert "no_pk_app" in redis_persister.list_app_ids(None)


def test_save_and_load_with_default_partition_key_with_ns(redis_persister_with_ns):
    """An application without a partition key saves and loads with partition_key=None."""
    redis_persister_with_ns.save(None, "no_pk_app", 1, "pos", state.State({"a": 1}), "completed")
    data = redis_persister_with_ns.load(None, "no_pk_app")
    assert data["state"].get_all() == {"a": 1}
    assert "no_pk_app" in redis_persister_with_ns.list_app_ids(None)


def test_list_app_ids(redis_persister):
    redis_persister.save("pk", "app_id1", 1, "pos1", state.State({"a": 1}), "completed")
    redis_persister.save("pk", "app_id2", 2, "pos2", state.State({"b": 2}), "completed")
    app_ids = redis_persister.list_app_ids("pk")
    assert "app_id1" in app_ids
    assert "app_id2" in app_ids


def test_load_nonexistent_key(redis_persister):
    state_data = redis_persister.load("pk", "nonexistent_key")
    assert state_data is None


def test_save_and_load_state_ns(redis_persister_with_ns):
    redis_persister_with_ns.save(
        "pk", "app_id", 1, "pos", state.State({"a": 1, "b": 2}), "completed"
    )
    data = redis_persister_with_ns.load("pk", "app_id", 1)
    assert data["state"].get_all() == {"a": 1, "b": 2}


def test_list_app_ids_with_ns(redis_persister_with_ns):
    redis_persister_with_ns.save("pk", "app_id1", 1, "pos1", state.State({"a": 1}), "completed")
    redis_persister_with_ns.save("pk", "app_id2", 2, "pos2", state.State({"b": 2}), "completed")
    app_ids = redis_persister_with_ns.list_app_ids("pk")
    assert "app_id1" in app_ids
    assert "app_id2" in app_ids


def test_load_nonexistent_key_with_ns(redis_persister_with_ns):
    state_data = redis_persister_with_ns.load("pk", "nonexistent_key")
    assert state_data is None


def test_redis_persister_class_backwards_compatible():
    """Tests that the RedisPersister class is still backwards compatible."""
    persister = RedisPersister(host="localhost", port=6379, db=0, namespace="backwardscompatible")
    persister.save("pk", "app_id", 2, "pos", state.State({"a": 4, "b": 5}), "completed")
    data = persister.load("pk", "app_id", 2)
    assert data["state"].get_all() == {"a": 4, "b": 5}
    persister.connection.close()


def test_serialization_with_pickle(redis_persister_with_ns):
    # Save some state
    redis_persister_with_ns.save(
        "pk", "app_id_serde", 1, "pos", state.State({"a": 1, "b": 2}), "completed"
    )

    # Serialize the persister
    serialized_persister = pickle.dumps(redis_persister_with_ns)

    # Deserialize the persister
    deserialized_persister = pickle.loads(serialized_persister)

    # Load the state from the deserialized persister
    data = deserialized_persister.load("pk", "app_id_serde", 1)

    assert data["state"].get_all() == {"a": 1, "b": 2}


@pytest.fixture
async def async_redis_persister():
    persister = AsyncRedisBasePersister.from_values(host="localhost", port=6379, db=1)
    yield persister
    await persister.cleanup()


@pytest.fixture
async def async_redis_persister_with_ns():
    persister = AsyncRedisBasePersister.from_values(
        host="localhost", port=6379, db=1, namespace="test_async"
    )
    yield persister
    await persister.cleanup()


async def test_async_save_and_load_state(async_redis_persister):
    await async_redis_persister.save(
        "pk", "app_id", 1, "pos", state.State({"a": 1, "b": 2}), "completed"
    )
    data = await async_redis_persister.load("pk", "app_id", 1)
    assert data["state"].get_all() == {"a": 1, "b": 2}


async def test_async_save_and_load_with_default_partition_key(async_redis_persister):
    """An application without a partition key saves and loads with partition_key=None."""
    await async_redis_persister.save(
        None, "no_pk_app", 1, "pos", state.State({"a": 1}), "completed"
    )
    data = await async_redis_persister.load(None, "no_pk_app")
    assert data["state"].get_all() == {"a": 1}
    assert "no_pk_app" in await async_redis_persister.list_app_ids(None)


async def test_async_list_app_ids(async_redis_persister):
    await async_redis_persister.save("pk", "app_id1", 1, "pos1", state.State({"a": 1}), "completed")
    await async_redis_persister.save("pk", "app_id2", 2, "pos2", state.State({"b": 2}), "completed")
    app_ids = await async_redis_persister.list_app_ids("pk")
    assert "app_id1" in app_ids
    assert "app_id2" in app_ids


async def test_async_load_nonexistent_key(async_redis_persister):
    state_data = await async_redis_persister.load("pk", "nonexistent_key")
    assert state_data is None


async def test_async_save_and_load_state_ns(async_redis_persister_with_ns):
    await async_redis_persister_with_ns.save(
        "pk", "app_id", 1, "pos", state.State({"a": 1, "b": 2}), "completed"
    )
    data = await async_redis_persister_with_ns.load("pk", "app_id", 1)
    assert data["state"].get_all() == {"a": 1, "b": 2}


async def test_async_list_app_ids_with_ns(async_redis_persister_with_ns):
    await async_redis_persister_with_ns.save(
        "pk", "app_id1", 1, "pos1", state.State({"a": 1}), "completed"
    )
    await async_redis_persister_with_ns.save(
        "pk", "app_id2", 2, "pos2", state.State({"b": 2}), "completed"
    )
    app_ids = await async_redis_persister_with_ns.list_app_ids("pk")
    assert "app_id1" in app_ids
    assert "app_id2" in app_ids


async def test_async_load_nonexistent_key_with_ns(async_redis_persister_with_ns):
    state_data = await async_redis_persister_with_ns.load("pk", "nonexistent_key")
    assert state_data is None
