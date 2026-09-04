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
import tomllib
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

if os.environ.get("BURR_CI_INTEGRATION_TESTS") != "true":
    pytest.skip("Skipping integration tests", allow_module_level=True)

from burr.core import state
from burr.core.persistence import BaseStatePersister
from burr.integrations.persisters.b_aerospike import (
    AerospikePersistenceConflictError,
    AerospikePersister,
)


@pytest.fixture
def aerospike_persister():
    persister = AerospikePersister.from_values(key_prefix=f"test-{uuid.uuid4().hex}")
    persister.initialize()
    yield persister
    persister.cleanup()


def test_persister_exposes_the_synchronous_burr_interface(aerospike_persister):
    assert isinstance(aerospike_persister, BaseStatePersister)
    assert aerospike_persister.is_async() is False
    assert aerospike_persister.is_initialized() is True


def test_exact_checkpoint_round_trip_returns_all_persisted_fields(aerospike_persister):
    aerospike_persister.save(
        "tenant-a",
        "application-a",
        7,
        "answer",
        state.State({"answer": 42}),
        "completed",
    )

    loaded = aerospike_persister.load("tenant-a", "application-a", 7)

    assert loaded["partition_key"] == "tenant-a"
    assert loaded["app_id"] == "application-a"
    assert loaded["sequence_id"] == 7
    assert loaded["position"] == "answer"
    assert loaded["state"].get_all() == {"answer": 42}
    assert loaded["status"] == "completed"
    assert loaded["created_at"].endswith("+00:00")


def test_owned_persister_pickle_round_trip_reconnects_and_loads_existing_state(
    aerospike_persister,
):
    aerospike_persister.save(
        "tenant-a",
        "pickle-app",
        3,
        "checkpoint",
        state.State({"restored": True}),
        "completed",
    )

    reconstructed = pickle.loads(pickle.dumps(aerospike_persister))
    try:
        assert reconstructed.is_initialized() is False
        loaded = reconstructed.load("tenant-a", "pickle-app", 3)
        assert loaded["state"].get_all() == {"restored": True}
    finally:
        reconstructed.cleanup()


def test_latest_load_returns_the_checkpoint_with_the_greatest_sequence(
    aerospike_persister,
):
    aerospike_persister.save(
        "pk", "app", 2, "second", state.State({"value": 2}), "completed"
    )
    aerospike_persister.save(
        "pk", "app", 1, "first", state.State({"value": 1}), "completed"
    )

    loaded = aerospike_persister.load("pk", "app")

    assert loaded["sequence_id"] == 2
    assert loaded["state"].get_all() == {"value": 2}


def test_absent_exact_checkpoint_and_absent_head_return_none(aerospike_persister):
    assert aerospike_persister.load("pk", "missing", 1) is None
    assert aerospike_persister.load("pk", "missing") is None


def test_load_requires_an_application_id(aerospike_persister):
    with pytest.raises(ValueError, match="app_id"):
        aerospike_persister.load("pk", None)


def test_none_empty_and_literal_none_partitions_remain_distinct(aerospike_persister):
    for partition_key, value in [(None, "null"), ("", "empty"), ("None", "literal")]:
        aerospike_persister.save(
            partition_key,
            "app",
            1,
            "position",
            state.State({"value": value}),
            "completed",
        )

    assert aerospike_persister.load(None, "app", 1)["state"].get_all() == {
        "value": "null"
    }
    assert aerospike_persister.load("", "app", 1)["state"].get_all() == {
        "value": "empty"
    }
    assert aerospike_persister.load("None", "app", 1)["state"].get_all() == {
        "value": "literal"
    }
    assert set(aerospike_persister.list_app_ids(None)) == {"app"}
    assert set(aerospike_persister.list_app_ids("")) == {"app"}
    assert set(aerospike_persister.list_app_ids("None")) == {"app"}


def test_list_app_ids_returns_each_application_once_without_an_order_contract(
    aerospike_persister,
):
    aerospike_persister.save(
        "pk", "app-a", 1, "one", state.State({"v": 1}), "completed"
    )
    aerospike_persister.save(
        "pk", "app-a", 2, "two", state.State({"v": 2}), "completed"
    )
    aerospike_persister.save(
        "pk", "app-b", 1, "one", state.State({"v": 3}), "completed"
    )

    assert set(aerospike_persister.list_app_ids("pk")) == {"app-a", "app-b"}
    assert aerospike_persister.list_app_ids("another-partition") == []


def test_identical_save_is_idempotent_and_preserves_the_first_creation_time(
    aerospike_persister,
):
    checkpoint = state.State({"message": "héllo", "nested": {"b": 2, "a": 1}})
    aerospike_persister.save("pk", "app", 1, "position", checkpoint, "completed")
    first = aerospike_persister.load("pk", "app", 1)

    aerospike_persister.save(
        "pk",
        "app",
        1,
        "position",
        state.State({"nested": {"a": 1, "b": 2}, "message": "héllo"}),
        "completed",
    )

    assert aerospike_persister.load("pk", "app", 1)["created_at"] == first["created_at"]


@pytest.mark.parametrize(
    ("position", "saved_state", "status"),
    [
        ("different", state.State({"value": 1}), "completed"),
        ("position", state.State({"value": 2}), "completed"),
        ("position", state.State({"value": 1}), "failed"),
    ],
)
def test_conflicting_duplicate_checkpoint_is_rejected(
    aerospike_persister, position, saved_state, status
):
    aerospike_persister.save(
        "pk", "app", 1, "position", state.State({"value": 1}), "completed"
    )

    with pytest.raises(AerospikePersistenceConflictError):
        aerospike_persister.save("pk", "app", 1, position, saved_state, status)

    loaded = aerospike_persister.load("pk", "app", 1)
    assert loaded["position"] == "position"
    assert loaded["state"].get_all() == {"value": 1}
    assert loaded["status"] == "completed"


@pytest.mark.parametrize("sequence_id", [True, -(2**63) - 1, 2**63])
def test_invalid_sequence_is_rejected_before_persistence(
    aerospike_persister, sequence_id
):
    with pytest.raises(ValueError, match="sequence"):
        aerospike_persister.save(
            "pk",
            "invalid-sequence",
            sequence_id,
            "position",
            state.State({}),
            "completed",
        )

    assert aerospike_persister.list_app_ids("pk") == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), b"bytes"])
def test_non_json_state_is_rejected_without_creating_a_head(aerospike_persister, value):
    with pytest.raises((TypeError, ValueError), match="serializ|JSON|finite"):
        aerospike_persister.save(
            "pk",
            "invalid-state",
            1,
            "position",
            state.State({"value": value}),
            "completed",
        )

    assert aerospike_persister.load("pk", "invalid-state") is None


def test_repeated_initialization_is_idempotent(aerospike_persister):
    aerospike_persister.initialize()
    assert aerospike_persister.is_initialized() is True


def test_validation_only_accepts_the_existing_compatible_index(aerospike_persister):
    validator = AerospikePersister.from_values(create_index=False)
    try:
        validator.initialize()
        assert validator.is_initialized() is True
    finally:
        validator.cleanup()


def test_head_never_regresses_when_an_older_checkpoint_is_retried(aerospike_persister):
    old = state.State({"value": "old"})
    aerospike_persister.save("pk", "app", 1, "old", old, "completed")
    aerospike_persister.save(
        "pk", "app", 2, "new", state.State({"value": "new"}), "completed"
    )
    aerospike_persister.save("pk", "app", 1, "old", old, "completed")

    assert aerospike_persister.load("pk", "app")["sequence_id"] == 2


class CallerOwnedClient:
    def __init__(self):
        self.close_calls = 0
        self.database_calls = 0

    def close(self):
        self.close_calls += 1

    def get(self, *args, **kwargs):
        self.database_calls += 1
        raise AssertionError("the database must not be accessed")

    def put(self, *args, **kwargs):
        self.database_calls += 1
        raise AssertionError("the database must not be accessed")

    def operate(self, *args, **kwargs):
        self.database_calls += 1
        raise AssertionError("the database must not be accessed")


def test_injected_client_constructs_a_synchronous_base_persister():
    persister = AerospikePersister(client=CallerOwnedClient())

    assert isinstance(persister, BaseStatePersister)
    assert persister.is_async() is False


def test_cleanup_and_context_exit_never_close_an_injected_client():
    client = CallerOwnedClient()
    persister = AerospikePersister(client=client)

    persister.cleanup()
    persister.cleanup()
    with persister:
        pass

    assert client.close_calls == 0


def test_cleanup_closes_an_internally_constructed_client_once():
    client = Mock()
    with patch(
        "burr.integrations.persisters.b_aerospike.aerospike.client", return_value=client
    ) as factory:
        persister = AerospikePersister.from_values()

    persister.cleanup()
    persister.cleanup()

    factory.assert_called_once()
    client.close.assert_called_once_with()


def test_from_config_accepts_official_client_configuration():
    client = Mock()
    config = {
        "hosts": [("aerospike.internal", 3000)],
        "client_config": {"user": "service-user", "password": "secret"},
        "namespace": "test",
        "history_set": "history",
        "head_set": "heads",
        "key_prefix": "service-a",
        "index_name": "service_a_partition_idx",
    }
    with patch(
        "burr.integrations.persisters.b_aerospike.aerospike.client", return_value=client
    ) as factory:
        persister = AerospikePersister.from_config(config)

    try:
        supplied_config = factory.call_args.args[0]
        assert supplied_config["hosts"] == [("aerospike.internal", 3000)]
        assert supplied_config["user"] == "service-user"
        assert supplied_config["password"] == "secret"
    finally:
        persister.cleanup()


@pytest.mark.parametrize("sequence_id", [True, -(2**63) - 1, 2**63, 1.0, "1"])
def test_invalid_sequence_is_rejected_before_client_access(sequence_id):
    client = CallerOwnedClient()
    persister = AerospikePersister(client=client)

    with pytest.raises(ValueError, match="sequence"):
        persister.save(
            "pk", "app", sequence_id, "position", state.State({}), "completed"
        )

    assert client.database_calls == 0


def test_load_without_an_app_id_is_rejected_before_client_access():
    client = CallerOwnedClient()
    persister = AerospikePersister(client=client)

    with pytest.raises(ValueError, match="app_id"):
        persister.load("pk", None)

    assert client.database_calls == 0


def test_aerospike_extra_preserves_core_python_baseline_and_selects_only_on_python_3_10_plus():
    metadata = tomllib.loads((Path(__file__).parents[3] / "pyproject.toml").read_text())

    assert metadata["project"]["requires-python"] == ">=3.9"
    (dependency,) = metadata["project"]["optional-dependencies"]["aerospike"]
    assert dependency.startswith("aerospike")
    assert "python_version" in dependency
    assert '>= "3.10"' in dependency or ">= '3.10'" in dependency
