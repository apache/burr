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

from burr.core.durable import JournalEntry, SuspensionRecord, supports_durable_storage
from burr.core.persistence import SQLitePersister


@pytest.fixture
def sqlite_persister():
    persister = SQLitePersister.from_values(":memory:")
    persister.initialize()
    yield persister


def _record(resolved=False):
    return SuspensionRecord(
        suspension_id="sus-1", partition_key="pk", app_id="app",
        sequence_id=4, position="review", channel="approval",
        schema_json={"type": "object"}, metadata={"summary": "s"},
        inputs={"x": 1}, state={"draft": "d"},
        created_at="2026-05-22T00:00:00", resolved=resolved,
    )


def test_sqlite_supports_durable_storage(sqlite_persister):
    assert supports_durable_storage(sqlite_persister) is True


def test_sqlite_suspension_round_trip(sqlite_persister):
    sqlite_persister.save_suspension(_record())
    loaded = sqlite_persister.load_suspension("pk", "app", "approval")
    assert loaded.suspension_id == "sus-1"
    assert loaded.state == {"draft": "d"}
    assert loaded.inputs == {"x": 1}
    assert loaded.schema_json == {"type": "object"}
    assert loaded.resolved is False


def test_sqlite_load_suspension_returns_resolved_record(sqlite_persister):
    # Contract: load_suspension returns the record whether or not it is
    # resolved; the caller checks record.resolved for resume-once idempotency.
    sqlite_persister.save_suspension(_record())
    sqlite_persister.mark_suspension_resolved("sus-1")
    loaded = sqlite_persister.load_suspension("pk", "app", "approval")
    assert loaded is not None
    assert loaded.resolved is True


def test_sqlite_mark_resolved_is_conditional(sqlite_persister):
    sqlite_persister.save_suspension(_record())
    first = sqlite_persister.mark_suspension_resolved("sus-1")
    second = sqlite_persister.mark_suspension_resolved("sus-1")
    # First call resolves a row; second call resolves nothing (resume-once).
    assert first is True
    assert second is False


def test_sqlite_journal_round_trip(sqlite_persister):
    sqlite_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "summarize", 0, "result-a")
    )
    sqlite_persister.save_journal_entry(
        JournalEntry("pk", "app", 4, "translate", 1, "result-b")
    )
    journal = sqlite_persister.load_journal("pk", "app", 4)
    assert [e.call_index for e in journal] == [0, 1]
    assert [e.result for e in journal] == ["result-a", "result-b"]
