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
