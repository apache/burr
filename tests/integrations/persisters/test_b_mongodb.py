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

import logging
import os
import pickle

import pytest
from pymongo.errors import InvalidOperation

from burr.core import state
from burr.core.persistence import PersistenceConflictError
from burr.integrations.persisters.b_mongodb import MongoDBPersister
from burr.integrations.persisters.b_pymongo import MongoDBBasePersister

if not os.environ.get("BURR_CI_INTEGRATION_TESTS") == "true":
    pytest.skip("Skipping integration tests", allow_module_level=True)


@pytest.fixture
def mongodb_persister():
    persister = MongoDBBasePersister.from_values(
        uri="mongodb://localhost:27017", db_name="testdb", collection_name="testcollection"
    )
    yield persister
    persister.collection.drop()


def test_save_and_load_state(mongodb_persister):
    mongodb_persister.save("pk", "app_id", 1, "pos", state.State({"a": 1, "b": 2}), "completed")
    data = mongodb_persister.load("pk", "app_id", 1)
    assert data["state"].get_all() == {"a": 1, "b": 2}


def test_list_app_ids(mongodb_persister):
    mongodb_persister.save("pk", "app_id1", 1, "pos1", state.State({"a": 1}), "completed")
    mongodb_persister.save("pk", "app_id2", 2, "pos2", state.State({"b": 2}), "completed")
    app_ids = mongodb_persister.list_app_ids("pk")
    assert "app_id1" in app_ids
    assert "app_id2" in app_ids


def test_load_nonexistent_key(mongodb_persister):
    state_data = mongodb_persister.load("pk", "nonexistent_key")
    assert state_data is None


def test_backwards_compatible_persister():
    persister = MongoDBPersister(
        uri="mongodb://localhost:27017", db_name="testdb", collection_name="backwardscompatible"
    )
    persister.save("pk", "app_id", 5, "pos", state.State({"a": 5, "b": 5}), "completed")
    data = persister.load("pk", "app_id", 5)
    assert data["state"].get_all() == {"a": 5, "b": 5}

    persister.collection.drop()


def test_serialization_with_pickle(mongodb_persister):
    # Save some state
    mongodb_persister.save(
        "pk", "app_id_serde", 1, "pos", state.State({"a": 1, "b": 2}), "completed"
    )

    # Serialize the persister
    serialized_persister = pickle.dumps(mongodb_persister)

    # Deserialize the persister
    deserialized_persister = pickle.loads(serialized_persister)

    # Load the state from the deserialized persister
    data = deserialized_persister.load("pk", "app_id_serde", 1)

    assert data["state"].get_all() == {"a": 1, "b": 2}


def test_partition_key_is_optional(mongodb_persister):
    # 1. Save and load with partition key = None
    mongodb_persister.save(
        None, "app_id_none", 1, "pos1", state.State({"foo": "bar"}), "in_progress"
    )
    loaded_data = mongodb_persister.load(None, "app_id_none", 1)
    assert loaded_data is not None
    assert loaded_data["state"].get_all() == {"foo": "bar"}

    # 2. Save and load again (different key/index) with partition key = None
    mongodb_persister.save(
        None, "app_id_none2", 2, "pos2", state.State({"hello": "world"}), "completed"
    )
    loaded_data2 = mongodb_persister.load(None, "app_id_none2", 2)
    assert loaded_data2 is not None
    assert loaded_data2["state"].get_all() == {"hello": "world"}


def test_cleanup_closes_client():
    persister = MongoDBBasePersister.from_values(
        uri="mongodb://localhost:27017", db_name="testdb", collection_name="cleanup"
    )
    persister.cleanup()
    with pytest.raises(InvalidOperation):
        persister.load("pk", "app_id")


def test_context_manager_closes_client():
    with MongoDBBasePersister.from_values(
        uri="mongodb://localhost:27017", db_name="testdb", collection_name="context_manager"
    ) as persister:
        assert persister.load("pk", "app_id") is None
    with pytest.raises(InvalidOperation):
        persister.load("pk", "app_id")


def test_save_of_a_saved_step_raises_conflict(mongodb_persister):
    mongodb_persister.save("pk", "app_id", 1, "pos", state.State({"a": 1}), "completed")
    with pytest.raises(PersistenceConflictError):
        mongodb_persister.save("pk", "app_id", 1, "pos", state.State({"a": 2}), "completed")
    assert mongodb_persister.load("pk", "app_id", 1)["state"].get_all() == {"a": 1}


def test_first_save_creates_a_unique_index_on_the_step(mongodb_persister):
    mongodb_persister.save("pk", "app_id", 1, "pos", state.State({"a": 1}), "completed")
    indexes = mongodb_persister.collection.index_information().values()
    step_key = [("partition_key", 1), ("app_id", 1), ("sequence_id", 1)]
    assert any(index["key"] == step_key and index.get("unique") for index in indexes)


def test_concurrent_saves_of_one_step_save_it_once(
    mongodb_persister, assert_one_concurrent_save_wins
):
    other = MongoDBBasePersister.from_values(
        uri="mongodb://localhost:27017", db_name="testdb", collection_name="testcollection"
    )
    try:
        assert_one_concurrent_save_wins([mongodb_persister, other])
    finally:
        other.cleanup()


def test_save_warns_once_when_duplicates_prevent_the_unique_index(mongodb_persister, caplog):
    """A collection written before the index existed can hold the same step twice."""
    duplicate = {"partition_key": "pk", "app_id": "old_app", "sequence_id": 0}
    mongodb_persister.collection.insert_many([dict(duplicate), dict(duplicate)])
    with caplog.at_level(logging.WARNING, logger="burr.integrations.persisters.b_pymongo"):
        mongodb_persister.save("pk", "app_id", 1, "pos", state.State({"a": 1}), "completed")
        mongodb_persister.save("pk", "app_id", 2, "pos", state.State({"a": 2}), "completed")
    assert len([r for r in caplog.records if "unique index" in r.getMessage()]) == 1
    assert mongodb_persister.load("pk", "app_id")["state"].get_all() == {"a": 2}
    with pytest.raises(PersistenceConflictError):
        mongodb_persister.save("pk", "app_id", 2, "pos", state.State({"a": 3}), "completed")
