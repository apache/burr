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

import pytest

from burr.core import state
from burr.integrations.persisters.b_google_sheets import COLUMNS, GoogleSheetsBasePersister


class FakeWorksheet:
    """In-memory stand-in for a ``gspread`` worksheet.

    Only the two methods the persister uses are implemented. Keeping the persister's
    dependency surface this small is what makes it testable without credentials or network.
    Google Sheets returns every cell as a string, so this does too.
    """

    def __init__(self, rows: list[list[str]] = None):
        self.rows = [list(row) for row in (rows or [])]

    def get_all_values(self) -> list[list[str]]:
        return [list(row) for row in self.rows]

    def append_row(self, values: list) -> None:
        self.rows.append([str(value) for value in values])


@pytest.fixture
def persister():
    p = GoogleSheetsBasePersister(FakeWorksheet())
    p.initialize()
    return p


def test_initialize_writes_header(persister):
    assert persister.worksheet.rows[0] == COLUMNS
    assert persister.is_initialized()


def test_initialize_is_idempotent(persister):
    persister.initialize()
    persister.initialize()
    assert persister.worksheet.rows.count(COLUMNS) == 1


def test_is_initialized_false_on_empty_worksheet():
    assert not GoogleSheetsBasePersister(FakeWorksheet()).is_initialized()


def test_save_and_load_state(persister):
    persister.save("pk", "app_id", 1, "pos", state.State({"a": 1, "b": 2}), "completed")
    data = persister.load("pk", "app_id", 1)
    assert data["state"].get_all() == {"a": 1, "b": 2}
    assert data["sequence_id"] == 1
    assert data["position"] == "pos"
    assert data["status"] == "completed"


def test_load_without_sequence_id_returns_latest(persister):
    """Rows are append-only, so the last matching row is the current state."""
    persister.save("pk", "app_id", 1, "first", state.State({"count": 1}), "completed")
    persister.save("pk", "app_id", 2, "second", state.State({"count": 2}), "completed")
    persister.save("pk", "app_id", 3, "third", state.State({"count": 3}), "completed")
    data = persister.load("pk", "app_id")
    assert data["sequence_id"] == 3
    assert data["position"] == "third"
    assert data["state"].get_all() == {"count": 3}


def test_load_specific_sequence_id(persister):
    persister.save("pk", "app_id", 1, "first", state.State({"count": 1}), "completed")
    persister.save("pk", "app_id", 2, "second", state.State({"count": 2}), "completed")
    data = persister.load("pk", "app_id", 1)
    assert data["sequence_id"] == 1
    assert data["state"].get_all() == {"count": 1}


def test_load_returns_none_when_missing(persister):
    assert persister.load("pk", "does-not-exist") is None


def test_load_is_scoped_to_partition_key(persister):
    persister.save("pk1", "app_id", 1, "pos", state.State({"a": 1}), "completed")
    persister.save("pk2", "app_id", 1, "pos", state.State({"a": 2}), "completed")
    assert persister.load("pk1", "app_id")["state"].get_all() == {"a": 1}
    assert persister.load("pk2", "app_id")["state"].get_all() == {"a": 2}


def test_list_app_ids_skips_header_and_dedupes(persister):
    persister.save("pk", "app_id1", 1, "pos", state.State({"a": 1}), "completed")
    persister.save("pk", "app_id2", 1, "pos", state.State({"b": 2}), "completed")
    persister.save("pk", "app_id1", 2, "pos", state.State({"a": 3}), "completed")
    app_ids = persister.list_app_ids("pk")
    assert COLUMNS[1] not in app_ids, "header row must never be treated as data"
    # app_id1 was written most recently, so it comes first
    assert app_ids == ["app_id1", "app_id2"]


def test_list_app_ids_is_scoped_to_partition_key(persister):
    persister.save("pk1", "app_id1", 1, "pos", state.State({"a": 1}), "completed")
    persister.save("pk2", "app_id2", 1, "pos", state.State({"b": 2}), "completed")
    assert persister.list_app_ids("pk1") == ["app_id1"]
    assert persister.list_app_ids("pk2") == ["app_id2"]


def test_list_app_ids_empty_for_unknown_partition_key(persister):
    assert persister.list_app_ids("nope") == []


def test_save_duplicate_key_raises(persister):
    persister.save("pk", "app_id", 1, "pos", state.State({"a": 1}), "completed")
    with pytest.raises(ValueError, match="already exists"):
        persister.save("pk", "app_id", 1, "pos", state.State({"a": 2}), "completed")


def test_same_sequence_id_different_position_is_allowed(persister):
    persister.save("pk", "app_id", 1, "pos_a", state.State({"a": 1}), "completed")
    persister.save("pk", "app_id", 1, "pos_b", state.State({"a": 2}), "completed")
    assert persister.load("pk", "app_id", 1)["position"] == "pos_b"


def test_none_partition_key_roundtrip(persister):
    persister.save(None, "app_id", 1, "pos", state.State({"a": 1}), "completed")
    data = persister.load(None, "app_id")
    assert data is not None
    assert data["state"].get_all() == {"a": 1}
    assert persister.list_app_ids(None) == ["app_id"]


def test_failed_status_is_persisted(persister):
    persister.save("pk", "app_id", 1, "pos", state.State({"a": 1}), "failed")
    assert persister.load("pk", "app_id")["status"] == "failed"


def test_reads_worksheet_without_header(persister):
    """A worksheet written by an older version has no header row; reads must not drop a row."""
    raw = FakeWorksheet()
    p = GoogleSheetsBasePersister(raw)
    p.save("pk", "app_id", 1, "pos", state.State({"a": 1}), "completed")
    assert not p.is_initialized()
    assert p.load("pk", "app_id")["state"].get_all() == {"a": 1}
    assert p.list_app_ids("pk") == ["app_id"]
