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

import dataclasses

import pytest

from burr.core.durable import (
    DeterminismError,
    JournalEntry,
    SuspensionRecord,
    _Suspended,
)


def test_suspended_is_base_exception_not_exception():
    assert issubclass(_Suspended, BaseException)
    assert not issubclass(_Suspended, Exception)


def test_suspended_carries_channel_schema_metadata():
    sig = _Suspended(channel="approval", schema_json={"type": "object"}, metadata={"k": "v"})
    assert sig.channel == "approval"
    assert sig.schema_json == {"type": "object"}
    assert sig.metadata == {"k": "v"}


def test_determinism_error_is_exception():
    assert issubclass(DeterminismError, Exception)


def test_suspension_record_fields():
    record = SuspensionRecord(
        suspension_id="s1",
        partition_key="p",
        app_id="a",
        sequence_id=3,
        position="review",
        channel="approval",
        schema_json=None,
        metadata={"summary": "hi"},
        inputs={"x": 1},
        state={"draft": "text"},
        created_at="2026-05-22T00:00:00",
        resolved=False,
    )
    assert dataclasses.is_dataclass(record)
    assert record.resolved is False
    assert record.state == {"draft": "text"}


def test_journal_entry_fields():
    entry = JournalEntry(
        partition_key="p",
        app_id="a",
        sequence_id=3,
        step_key="summarize",
        call_index=0,
        result="cached value",
    )
    assert dataclasses.is_dataclass(entry)
    assert entry.call_index == 0
    assert entry.result == "cached value"


def test_save_status_literal_includes_suspended():
    import typing

    from burr.core.persistence import BaseStateSaver

    hints = typing.get_type_hints(BaseStateSaver.save)
    status_arg = hints["status"]
    assert "suspended" in typing.get_args(status_arg)


def test_durable_symbols_exported_from_burr_core():
    import burr.core as core

    assert hasattr(core, "DeterminismError")
    assert hasattr(core, "SuspensionRecord")


def test_base_persister_durable_methods_raise_not_implemented():
    from burr.core.durable import JournalEntry, SuspensionRecord
    from burr.core.persistence import BaseStatePersister

    # Use DevNullPersister which satisfies the abstract methods but does not
    # override the durable methods, so all five should raise NotImplementedError.
    from burr.core.persistence import DevNullPersister

    p = DevNullPersister()

    dummy_record = SuspensionRecord(
        suspension_id="s1",
        partition_key="p",
        app_id="a",
        sequence_id=1,
        position="action",
        channel="ch",
        schema_json=None,
        metadata=None,
        inputs={},
        state={},
        created_at="2026-05-22T00:00:00",
        resolved=False,
    )
    dummy_entry = JournalEntry(
        partition_key="p",
        app_id="a",
        sequence_id=1,
        step_key="k",
        call_index=0,
        result=None,
    )

    with pytest.raises(NotImplementedError):
        p.save_suspension(dummy_record)

    with pytest.raises(NotImplementedError):
        p.load_suspension("p", "a", "ch")

    with pytest.raises(NotImplementedError):
        p.save_journal_entry(dummy_entry)

    with pytest.raises(NotImplementedError):
        p.load_journal("p", "a", 1)

    with pytest.raises(NotImplementedError):
        p.mark_suspension_resolved("s1")


def test_supports_durable_storage_false_for_base_sqlite():
    from burr.core.durable import supports_durable_storage
    from burr.core.persistence import SQLitePersister

    persister = SQLitePersister.from_values(":memory:")
    # No SQLite override ships in this task; that lands in M4.
    assert supports_durable_storage(persister) is False


def test_supports_durable_storage_true_for_in_memory():
    from burr.core.durable import supports_durable_storage
    from burr.core.persistence import InMemoryPersister

    assert supports_durable_storage(InMemoryPersister()) is True


def test_in_memory_persister_suspension_round_trip():
    from burr.core.durable import SuspensionRecord
    from burr.core.persistence import InMemoryPersister

    persister = InMemoryPersister()
    record = SuspensionRecord(
        suspension_id="s1", partition_key="p", app_id="a", sequence_id=2,
        position="review", channel="approval", schema_json=None,
        metadata=None, inputs={}, state={"draft": "d"},
        created_at="2026-05-22T00:00:00", resolved=False,
    )
    persister.save_suspension(record)
    loaded = persister.load_suspension("p", "a", "approval")
    assert loaded.suspension_id == "s1"
    assert loaded.state == {"draft": "d"}
    assert loaded.resolved is False


def test_in_memory_persister_journal_round_trip():
    from burr.core.durable import JournalEntry
    from burr.core.persistence import InMemoryPersister

    persister = InMemoryPersister()
    entry = JournalEntry(
        partition_key="p", app_id="a", sequence_id=2,
        step_key="summarize", call_index=0, result="cached",
    )
    persister.save_journal_entry(entry)
    journal = persister.load_journal("p", "a", 2)
    assert len(journal) == 1
    assert journal[0].result == "cached"
