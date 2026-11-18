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

"""Unambiguous partition identity on the query-parameter HTTP routes."""

import asyncio
import importlib
import json
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from burr.core import ApplicationBuilder, Result, State, action, default
from burr.tracking.client import LocalTrackingClient
from burr.tracking.server.backend import LocalBackend
from burr.tracking.server.schema import AnnotationCreate, AnnotationObservation

PROJECT = "partition-query-tests"


@action(reads=["marker"], writes=["marker"])
def stamp(state: State) -> State:
    return state.update(marker=f"{state['marker']}:stamped")


def write_app(storage, app_id, partition, marker):
    tracker = LocalTrackingClient(project=PROJECT, storage_dir=str(storage))
    app = (
        ApplicationBuilder()
        .with_state(marker=marker)
        .with_actions(stamp, Result("marker").with_name("result"))
        .with_transitions(("stamp", "result", default))
        .with_entrypoint("stamp")
        .with_tracker(tracker)
        .with_identifiers(app_id=app_id, partition_key=partition)
        .build()
    )
    app.run(halt_after=["result"])
    tracker.f.close()
    tracker.f = None


def write_manual_app(storage, app_id, partition):
    """Write a minimal but valid legacy application directory without running a graph."""
    directory = Path(storage) / PROJECT / app_id
    directory.mkdir(parents=True, exist_ok=True)
    graph = {
        "type": "application",
        "entrypoint": "stamp",
        "actions": [],
        "transitions": [],
    }
    (directory / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    metadata = {
        "type": "application_metadata",
        "partition_key": partition,
        "parent_pointer": None,
        "spawning_parent_pointer": None,
    }
    (directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    end_entry = {
        "type": "end_entry",
        "action": "result",
        "sequence_id": 0,
        "state": {},
        "exception": None,
        "end_time": "2024-01-01T00:00:00",
    }
    (directory / "log.jsonl").write_text(json.dumps(end_entry) + "\n", encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BURR_SERVE_STATIC", "false")
    monkeypatch.setenv("BURR_SERVER_DEMOS", "false")
    monkeypatch.setenv("BURR_BACKEND_IMPL", "burr.tracking.server.backend.LocalBackend")
    monkeypatch.setenv("burr_path", str(tmp_path))
    for app_id, partition, marker in [
        ("none-app", None, "MARK_NONE"),
        ("empty-app", "", "MARK_EMPTY"),
        ("sentinel-app", "__none__", "MARK_SENTINEL"),
        ("slash-app", "tenant/A", "MARK_SLASH"),
        ("unicode-app", "分区-🔑", "MARK_UNICODE"),
    ]:
        write_app(str(tmp_path), app_id, partition, marker)
    run = importlib.import_module("burr.tracking.server.run")
    monkeypatch.setattr(run, "backend", LocalBackend(path=str(tmp_path)))
    return TestClient(run.create_burr_ui_app(serve_static=False))


def detail(client, app_id, partition=None, none_partition=False):
    params = (
        "none_partition=true"
        if none_partition
        else f"partition_key={quote(partition or '', safe='')}"
    )
    return client.get(f"/api/v0/apps/{PROJECT}/{app_id}/detail?{params}")


def markers(response):
    return sorted(
        s["step_end_log"]["state"]["marker"]
        for s in response.json()["steps"]
        if s.get("step_end_log")
    )


def test_none_empty_and_sentinel_are_distinct(client):
    assert markers(detail(client, "none-app", none_partition=True)) == ["MARK_NONE:stamped"] * 2
    assert markers(detail(client, "empty-app", partition="")) == ["MARK_EMPTY:stamped"] * 2
    assert (
        markers(detail(client, "sentinel-app", partition="__none__"))
        == ["MARK_SENTINEL:stamped"] * 2
    )


def test_slash_and_unicode_partitions_are_addressable(client):
    assert markers(detail(client, "slash-app", partition="tenant/A")) == ["MARK_SLASH:stamped"] * 2
    assert markers(detail(client, "unicode-app", partition="分区-🔑")) == ["MARK_UNICODE:stamped"] * 2


def test_list_filter_distinguishes_exact_identities(client):
    none_list = client.get(f"/api/v0/apps/{PROJECT}/list?none_partition=true")
    assert [(a["app_id"], a["partition_key"]) for a in none_list.json()["applications"]] == [
        ("none-app", None)
    ]
    empty_list = client.get(f"/api/v0/apps/{PROJECT}/list?partition_key=")
    assert [(a["app_id"], a["partition_key"]) for a in empty_list.json()["applications"]] == [
        ("empty-app", "")
    ]
    sentinel_list = client.get(f"/api/v0/apps/{PROJECT}/list?partition_key=__none__")
    assert [(a["app_id"], a["partition_key"]) for a in sentinel_list.json()["applications"]] == [
        ("sentinel-app", "__none__")
    ]
    all_list = client.get(f"/api/v0/apps/{PROJECT}/list")
    assert len(all_list.json()["applications"]) == 5


def test_query_identity_validation(client):
    conflict = client.get(
        f"/api/v0/apps/{PROJECT}/none-app/detail?partition_key=x&none_partition=true"
    )
    assert conflict.status_code == 400
    missing = client.get(f"/api/v0/apps/{PROJECT}/none-app/detail")
    assert missing.status_code == 400


def test_none_partition_pagination_over_100_records(tmp_path, monkeypatch):
    for index in range(150):
        write_manual_app(tmp_path, f"none-{index:03d}", None)
    for index in range(50):
        write_manual_app(tmp_path, f"other-{index:03d}", "other")

    monkeypatch.setenv("BURR_SERVE_STATIC", "false")
    monkeypatch.setenv("BURR_SERVER_DEMOS", "false")
    monkeypatch.setenv("BURR_BACKEND_IMPL", "burr.tracking.server.backend.LocalBackend")
    monkeypatch.setenv("burr_path", str(tmp_path))
    run = importlib.import_module("burr.tracking.server.run")
    monkeypatch.setattr(run, "backend", LocalBackend(path=str(tmp_path)))
    client = TestClient(run.create_burr_ui_app(serve_static=False))

    base = f"/api/v0/apps/{PROJECT}/list?none_partition=true"
    first = client.get(f"{base}&limit=100&offset=0").json()
    second = client.get(f"{base}&limit=100&offset=100").json()
    tail = client.get(f"{base}&limit=25&offset=140").json()

    assert first["total"] == 150
    assert len(first["applications"]) == 100
    assert first["has_another_page"] is True
    assert second["total"] == 150
    assert len(second["applications"]) == 50
    assert second["has_another_page"] is False
    assert tail["total"] == 150
    assert len(tail["applications"]) == 10
    assert tail["has_another_page"] is False

    first_ids = {app["app_id"] for app in first["applications"]}
    second_ids = {app["app_id"] for app in second["applications"]}
    assert first_ids.isdisjoint(second_ids)
    assert all(
        app["partition_key"] is None for app in first["applications"] + second["applications"]
    )


ANNOTATION_PARTITIONS = [None, "", "__none__", "tenant/A", "tenant-A"]


def annotation_markers(response):
    return sorted(
        {annotation["tags"][0] for annotation in response.json() if annotation.get("tags")}
    )


@pytest.fixture
def annotation_client(tmp_path, monkeypatch):
    monkeypatch.setenv("BURR_SERVE_STATIC", "false")
    monkeypatch.setenv("BURR_SERVER_DEMOS", "false")
    monkeypatch.setenv("BURR_BACKEND_IMPL", "burr.tracking.server.backend.LocalBackend")
    monkeypatch.setenv("burr_path", str(tmp_path))
    (Path(tmp_path) / PROJECT).mkdir(parents=True, exist_ok=True)
    backend = LocalBackend(path=str(tmp_path))
    for partition in ANNOTATION_PARTITIONS:
        marker = "ANNOT_NONE" if partition is None else f"ANNOT_{partition}"
        annotation = AnnotationCreate(
            span_id=None,
            step_name="step",
            tags=[marker],
            observations=[
                AnnotationObservation(
                    data_fields={"marker": marker}, thumbs_up_thumbs_down=None, data_pointers=[]
                )
            ],
        )
        asyncio.run(backend.create_annotation(annotation, PROJECT, partition, "shared", 7))
    run = importlib.import_module("burr.tracking.server.run")
    monkeypatch.setattr(run, "backend", backend)
    return TestClient(run.create_burr_ui_app(serve_static=False))


def test_legacy_annotation_get_sentinel_is_ambiguous(annotation_client):
    """Negative control: the legacy route must not be treated as identity-safe."""
    response = annotation_client.get(
        f"/api/v0/{PROJECT}/annotations?app_id=shared&step_sequence_id=7&partition_key=__none__"
    )
    assert response.status_code == 200
    assert set(annotation_markers(response)) == {
        "ANNOT_",
        "ANNOT___none__",
        "ANNOT_NONE",
        "ANNOT_tenant-A",
        "ANNOT_tenant/A",
    }


def annotation_query(client, query):
    return client.get(
        f"/api/v0/apps/{PROJECT}/annotations?app_id=shared&step_sequence_id=7&{query}"
    )


def test_annotation_query_preserves_exact_partition_identity(annotation_client):
    assert annotation_markers(annotation_query(annotation_client, "partition_key=__none__")) == [
        "ANNOT___none__"
    ]
    assert annotation_markers(annotation_query(annotation_client, "partition_key=")) == ["ANNOT_"]
    assert annotation_markers(annotation_query(annotation_client, "partition_key=tenant%2FA")) == [
        "ANNOT_tenant/A"
    ]
    assert annotation_markers(annotation_query(annotation_client, "partition_key=tenant-A")) == [
        "ANNOT_tenant-A"
    ]


def test_annotation_query_none_partition_is_not_no_filter(annotation_client):
    response = annotation_query(annotation_client, "none_partition=true")
    assert response.status_code == 200
    assert annotation_markers(response) == ["ANNOT_NONE"]


def test_annotation_query_rejects_ambiguous_parameters(annotation_client):
    conflict = annotation_query(annotation_client, "partition_key=__none__&none_partition=true")
    assert conflict.status_code == 400
    missing = annotation_query(annotation_client, "none_partition=false")
    assert missing.status_code == 400


def test_legacy_annotation_get_without_partition_keeps_historical_no_filter(annotation_client):
    response = annotation_client.get(
        f"/api/v0/{PROJECT}/annotations?app_id=shared&step_sequence_id=7"
    )
    assert response.status_code == 200
    assert set(annotation_markers(response)) == {
        "ANNOT_",
        "ANNOT___none__",
        "ANNOT_NONE",
        "ANNOT_tenant-A",
        "ANNOT_tenant/A",
    }
