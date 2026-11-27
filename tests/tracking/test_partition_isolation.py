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

"""Partition isolation for local tracking (issue #319)."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from burr.core import ApplicationBuilder, Result, State, action, default
from burr.tracking.client import LocalTrackingClient
from burr.tracking.common.partition_paths import (
    PARTITIONS_DIRNAME,
    application_directory,
    partition_segment,
)
from burr.tracking.server.backend import LocalBackend

PROJECT = "partition-isolation-tests"
APP_ID = "shared-app"


@action(reads=["marker"], writes=["marker"])
def stamp(state: State) -> State:
    return state.update(marker=f"{state['marker']}:stamped")


def write_app(storage, app_id, partition, marker, sequence_id=None):
    tracker = LocalTrackingClient(project=PROJECT, storage_dir=str(storage))
    builder = (
        ApplicationBuilder()
        .with_state(marker=marker)
        .with_actions(stamp, Result("marker").with_name("result"))
        .with_transitions(("stamp", "result", default))
        .with_entrypoint("stamp")
        .with_tracker(tracker)
        .with_identifiers(app_id=app_id, partition_key=partition)
    )
    if sequence_id is not None:
        builder = builder.with_identifiers(sequence_id=sequence_id)
    app = builder.build()
    app.run(halt_after=["result"])
    tracker.f.close()
    tracker.f = None
    return app


def loaded_marker(storage, partition, app_id=APP_ID, sequence_id=None):
    tracker = LocalTrackingClient(project=PROJECT, storage_dir=str(storage))
    data = tracker.load(partition_key=partition, app_id=app_id, sequence_id=sequence_id)
    return None if data is None else dict(data["state"].get_all())["marker"]


def app_root(storage, app_id=APP_ID):
    return Path(storage) / PROJECT / app_id


def write_legacy(storage, app_id, marker, metadata=None):
    directory = app_root(storage, app_id)
    directory.mkdir(parents=True, exist_ok=True)
    graph = {
        "type": "application",
        "entrypoint": "stamp",
        "actions": [{"name": "stamp", "reads": ["marker"], "writes": ["marker"], "code": "pass"}],
        "transitions": [],
    }
    (directory / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    end_entry = {
        "type": "end_entry",
        "action": "result",
        "sequence_id": 0,
        "state": {"marker": marker},
        "exception": None,
        "end_time": "2024-01-01T00:00:00",
    }
    (directory / "log.jsonl").write_text(json.dumps(end_entry) + "\n", encoding="utf-8")
    if metadata is not None:
        (directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return directory


def test_two_partitions_have_independent_files_and_metadata(tmp_path):
    write_app(tmp_path, APP_ID, "tenant-A", "MARK_A")
    write_app(tmp_path, APP_ID, "tenant-B", "MARK_B")

    root = app_root(tmp_path)
    assert not (root / "log.jsonl").exists()
    assert not (root / "metadata.json").exists()
    dir_a = Path(application_directory(str(root), "tenant-A"))
    dir_b = Path(application_directory(str(root), "tenant-B"))
    assert dir_a != dir_b
    for directory, partition, marker in (
        (dir_a, "tenant-A", "MARK_A"),
        (dir_b, "tenant-B", "MARK_B"),
    ):
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["partition_key"] == partition
        lines = [json.loads(line) for line in (directory / "log.jsonl").read_text().splitlines()]
        assert all(
            line["state"]["marker"].startswith(marker)
            for line in lines
            if line["type"] == "end_entry"
        )
        assert len([line for line in lines if line["type"] == "end_entry"]) == 2


def test_load_resume_and_sequence_id_use_the_requested_partition(tmp_path):
    write_app(tmp_path, APP_ID, "tenant-A", "MARK_A")
    write_app(tmp_path, APP_ID, "tenant-B", "MARK_B", sequence_id=9)

    assert loaded_marker(tmp_path, "tenant-A") == "MARK_A:stamped"
    assert loaded_marker(tmp_path, "tenant-B") == "MARK_B:stamped"
    assert loaded_marker(tmp_path, "tenant-A", sequence_id=0) == "MARK_A:stamped"
    with pytest.raises(ValueError, match="Sequence number 10 not found"):
        loaded_marker(tmp_path, "tenant-A", sequence_id=10)

    for partition, marker in (("tenant-A", "MARK_A:stamped"), ("tenant-B", "MARK_B:stamped")):
        tracker = LocalTrackingClient(project=PROJECT, storage_dir=str(tmp_path))
        app = (
            ApplicationBuilder()
            .with_actions(stamp, Result("marker").with_name("result"))
            .with_transitions(("stamp", "result", default))
            .with_tracker(tracker)
            .initialize_from(
                tracker,
                resume_at_next_action=True,
                default_state={"marker": "DEFAULT"},
                default_entrypoint="stamp",
            )
            .with_identifiers(app_id=APP_ID, partition_key=partition)
            .build()
        )
        assert dict(app.state.get_all())["marker"] == marker
        tracker.f.close()
        tracker.f = None


def test_legacy_data_is_read_only_when_metadata_confirms_the_partition(tmp_path):
    legacy_a = write_legacy(tmp_path, "legacy-a", "LEGACY_A", {"partition_key": "tenant-A"})
    legacy_none = write_legacy(tmp_path, "legacy-none", "LEGACY_NONE", {"partition_key": None})
    legacy_missing = write_legacy(tmp_path, "legacy-missing", "LEGACY_MISSING")
    before = {p: (p / "log.jsonl").read_bytes() for p in (legacy_a, legacy_none, legacy_missing)}

    assert loaded_marker(tmp_path, "tenant-A", "legacy-a") == "LEGACY_A"
    assert loaded_marker(tmp_path, None, "legacy-none") == "LEGACY_NONE"
    assert loaded_marker(tmp_path, None, "legacy-missing") == "LEGACY_MISSING"

    with pytest.raises(ValueError, match="Refusing to load"):
        loaded_marker(tmp_path, "tenant-B", "legacy-a")
    with pytest.raises(ValueError, match="Refusing to load it without a partition_key"):
        loaded_marker(tmp_path, None, "legacy-a")
    with pytest.raises(ValueError, match="Refusing to load"):
        loaded_marker(tmp_path, "tenant-A", "legacy-none")
    with pytest.raises(ValueError, match="Refusing to load"):
        loaded_marker(tmp_path, "tenant-A", "legacy-missing")

    for path, content in before.items():
        assert (path / "log.jsonl").read_bytes() == content
        assert not (path / PARTITIONS_DIRNAME).exists()

    backend = LocalBackend(path=str(tmp_path))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(backend.get_application_logs(None, PROJECT, "legacy-a", "tenant-B"))
    assert exc.value.status_code == 400  # data exists but belongs to another partition
    with pytest.raises(HTTPException) as exc:
        asyncio.run(backend.get_application_logs(None, PROJECT, "missing-app", "tenant-A"))
    assert exc.value.status_code == 404  # no data for these identifiers


def test_legacy_and_new_runs_for_same_partition_coexist(tmp_path):
    write_legacy(tmp_path, APP_ID, "LEGACY_A", {"partition_key": "tenant-A"})
    write_app(tmp_path, APP_ID, "tenant-A", "NEW_A")

    assert loaded_marker(tmp_path, "tenant-A") == "NEW_A:stamped"
    with pytest.raises(ValueError, match="partition_key is required|without a partition_key"):
        loaded_marker(tmp_path, None)

    backend = LocalBackend(path=str(tmp_path))
    listed, total = asyncio.run(backend.list_apps(None, PROJECT, "tenant-A"))
    assert total == 1
    assert [(a.app_id, a.partition_key) for a in listed] == [(APP_ID, "tenant-A")]
    logs = asyncio.run(backend.get_application_logs(None, PROJECT, APP_ID, "tenant-A"))
    assert all(step.step_end_log.state["marker"].startswith("NEW_A") for step in logs.steps)


def test_resume_from_legacy_then_continue_in_new_partition_directory(tmp_path):
    """An upgrade resume must read legacy state before its own empty log shadows it."""
    legacy = write_legacy(tmp_path, APP_ID, "LEGACY_A", {"partition_key": "tenant-A"})
    before = (legacy / "log.jsonl").read_bytes()

    def resume_and_run():
        tracker = LocalTrackingClient(project=PROJECT, storage_dir=str(tmp_path))
        app = (
            ApplicationBuilder()
            .with_actions(stamp, Result("marker").with_name("result"))
            .with_transitions(("stamp", "result", default))
            .with_tracker(tracker)
            .initialize_from(
                tracker,
                resume_at_next_action=False,
                default_state={"marker": "DEFAULT_MUST_NOT_BE_USED"},
                default_entrypoint="stamp",
            )
            .with_identifiers(app_id=APP_ID, partition_key="tenant-A")
            .build()
        )
        initial = dict(app.state.get_all())["marker"]
        app.run(halt_after=["result"])
        tracker.f.close()
        tracker.f = None
        return initial, dict(app.state.get_all())["marker"], app.sequence_id

    initial_1, final_1, seq_1 = resume_and_run()
    assert initial_1 == "LEGACY_A"
    assert final_1 == "LEGACY_A:stamped"
    assert loaded_marker(tmp_path, "tenant-A") == final_1

    initial_2, final_2, seq_2 = resume_and_run()
    assert initial_2 == final_1
    assert final_2 == "LEGACY_A:stamped:stamped"
    assert loaded_marker(tmp_path, "tenant-A") == final_2
    assert seq_2 == seq_1 + 2

    nested = Path(application_directory(str(app_root(tmp_path)), "tenant-A"))
    nested_lines = [json.loads(line) for line in (nested / "log.jsonl").read_text().splitlines()]
    assert all(
        line["state"]["marker"].startswith("LEGACY_A")
        for line in nested_lines
        if line["type"] == "end_entry"
    )
    assert (legacy / "log.jsonl").read_bytes() == before

    backend = LocalBackend(path=str(tmp_path))
    logs = asyncio.run(backend.get_application_logs(None, PROJECT, APP_ID, "tenant-A"))
    assert all(step.step_end_log.state["marker"].startswith("LEGACY_A") for step in logs.steps)
    listed, total = asyncio.run(backend.list_apps(None, PROJECT, "tenant-A"))
    assert total == 1 and listed[0].app_id == APP_ID


def test_empty_string_partition_is_distinct_from_none(tmp_path):
    write_app(tmp_path, APP_ID, None, "NO_PARTITION")
    write_app(tmp_path, APP_ID, "", "EMPTY_PARTITION")

    assert loaded_marker(tmp_path, None) == "NO_PARTITION:stamped"
    assert loaded_marker(tmp_path, "") == "EMPTY_PARTITION:stamped"
    with pytest.raises(ValueError, match="Refusing to load"):
        loaded_marker(tmp_path, "tenant-A")


def test_same_partition_different_app_ids_are_independent(tmp_path):
    write_app(tmp_path, "app-1", "tenant-A", "APP_1")
    write_app(tmp_path, "app-2", "tenant-A", "APP_2")
    assert loaded_marker(tmp_path, "tenant-A", "app-1") == "APP_1:stamped"
    assert loaded_marker(tmp_path, "tenant-A", "app-2") == "APP_2:stamped"


def test_ui_backend_reads_only_the_requested_partition(tmp_path):
    write_app(tmp_path, APP_ID, "tenant-A", "MARK_A")
    write_app(tmp_path, APP_ID, "tenant-B", "MARK_B", sequence_id=9)
    backend = LocalBackend(path=str(tmp_path))

    logs_a = asyncio.run(backend.get_application_logs(None, PROJECT, APP_ID, "tenant-A"))
    logs_b = asyncio.run(backend.get_application_logs(None, PROJECT, APP_ID, "tenant-B"))
    assert [s.step_start_log.sequence_id for s in logs_a.steps] == [0, 1]
    assert [s.step_start_log.sequence_id for s in logs_b.steps] == [10, 11]
    assert all(s.step_end_log.state["marker"].startswith("MARK_A") for s in logs_a.steps)
    assert all(s.step_end_log.state["marker"].startswith("MARK_B") for s in logs_b.steps)

    for partition in ("tenant-A", "tenant-B"):
        listed, total = asyncio.run(backend.list_apps(None, PROJECT, partition))
        assert total == 1
        assert listed[0].partition_key == partition
    listed, total = asyncio.run(backend.list_apps(None, PROJECT, None))
    assert total == 2
    with pytest.raises(HTTPException) as exc:
        asyncio.run(backend.get_application_logs(None, PROJECT, APP_ID, None))
    assert exc.value.status_code == 400


def test_fork_child_relationship_goes_to_parent_partition_directory(tmp_path):
    write_app(tmp_path, "parent", "tenant-A", "PARENT")
    tracker = LocalTrackingClient(project=PROJECT, storage_dir=str(tmp_path))
    child = (
        ApplicationBuilder()
        .with_actions(stamp, Result("marker").with_name("result"))
        .with_transitions(("stamp", "result", default))
        .with_tracker(tracker)
        .initialize_from(
            tracker,
            resume_at_next_action=True,
            default_state={"marker": "CHILD"},
            default_entrypoint="stamp",
            fork_from_app_id="parent",
            fork_from_partition_key="tenant-A",
            fork_from_sequence_id=0,
        )
        .with_identifiers(app_id="child", partition_key="tenant-B")
        .build()
    )
    child.run(halt_after=["result"])
    tracker.f.close()
    tracker.f = None

    parent_root = app_root(tmp_path, "parent")
    assert not (parent_root / "children.jsonl").exists()
    parent_partition = Path(application_directory(str(parent_root), "tenant-A"))
    children = [
        json.loads(line)
        for line in (parent_partition / "children.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [c["child"]["partition_key"] for c in children] == ["tenant-B"]
    logs = asyncio.run(
        LocalBackend(path=str(tmp_path)).get_application_logs(None, PROJECT, "parent", "tenant-A")
    )
    assert [c.child.partition_key for c in logs.children] == ["tenant-B"]


@pytest.mark.parametrize(
    "partition",
    ["../escape", "nested/segment", "back\\slash", "a" * 300, "line\nbreak", "分区-🔑", ""],
)
def test_partition_keys_are_path_safe_and_round_trip_through_metadata(tmp_path, partition):
    write_app(tmp_path, APP_ID, partition, "MARK")
    root = app_root(tmp_path)
    partition_dir = Path(application_directory(str(root), partition))
    assert partition_dir.parent == root / PARTITIONS_DIRNAME
    assert partition_dir.parent.parent == root
    metadata = json.loads((partition_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["partition_key"] == partition
    assert loaded_marker(tmp_path, partition) == "MARK:stamped"
    assert list((tmp_path / PROJECT).iterdir()) == [root]


def test_async_application_uses_partition_aware_paths(tmp_path):
    async def run(partition, marker):
        tracker = LocalTrackingClient(project=PROJECT, storage_dir=str(tmp_path))
        app = await (
            ApplicationBuilder()
            .with_state(marker=marker)
            .with_actions(stamp, Result("marker").with_name("result"))
            .with_transitions(("stamp", "result", default))
            .with_entrypoint("stamp")
            .with_tracker(tracker)
            .with_identifiers(app_id=APP_ID, partition_key=partition)
            .abuild()
        )
        await app.arun(halt_after=["result"])
        tracker.f.close()
        tracker.f = None

    asyncio.run(run("tenant-A", "ASYNC_A"))
    asyncio.run(run("tenant-B", "ASYNC_B"))
    assert loaded_marker(tmp_path, "tenant-A") == "ASYNC_A:stamped"
    assert loaded_marker(tmp_path, "tenant-B") == "ASYNC_B:stamped"


def test_partition_segment_is_stable_and_non_empty_partitions_do_not_collide():
    assert partition_segment("tenant-A") == partition_segment("tenant-A")
    assert partition_segment("tenant-A") != partition_segment("tenant-B")
    assert partition_segment("") != partition_segment("a")
    assert "/" not in partition_segment("../escape")
