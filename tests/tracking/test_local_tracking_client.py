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

import json
import os
import uuid
from typing import Literal, Optional, Tuple

import pytest

import burr
from burr import lifecycle
from burr.core import Action, Application, ApplicationBuilder, Result, State, action, default, expr
from burr.core.persistence import BaseStatePersister, PersistedStateData
from burr.tracking import LocalTrackingClient
from burr.tracking.client import _allowed_project_name
from burr.tracking.common.models import (
    ApplicationMetadataModel,
    ApplicationModel,
    AttributeModel,
    BeginEntryModel,
    BeginSpanModel,
    ChildApplicationModel,
    EndEntryModel,
    EndSpanModel,
)
from burr.visibility import TracerFactory


@action(reads=["counter", "break_at"], writes=["counter"])
def counter(state: State, __tracer: TracerFactory) -> Tuple[dict, State]:
    with __tracer("increment") as t:
        result = {"counter": state["counter"] + 1}
        t.log_attributes(counter=result["counter"])
    if state["break_at"] == result["counter"]:
        raise ValueError("Broken")
    return result, state.update(**result)


def sample_application(
    project_name: str,
    log_dir: str,
    app_id: str,
    broken: bool = False,
    spawn_from: Tuple[Optional[str], Optional[int]] = (None, None),
):
    return (
        burr.core.ApplicationBuilder()
        .with_state(counter=0, break_at=2 if broken else -1)
        .with_actions(counter=counter, result=Result("counter"))
        .with_transitions(
            ("counter", "counter", expr("counter < 2")),  # just count to two for testing
            ("counter", "result", default),
        )
        .with_entrypoint("counter")
        .with_tracker(project=project_name, tracker="local", params={"storage_dir": log_dir})
        .with_identifiers(app_id=app_id)
        .with_spawning_parent(
            app_id=spawn_from[0],
            sequence_id=spawn_from[1],  # no need to test the partition key here really
        )
        .build()
    )


def test_application_tracks_end_to_end(tmpdir: str):
    app_id = str(uuid.uuid4())
    log_dir = os.path.join(tmpdir, "tracking")
    project_name = "test_application_tracks_end_to_end"
    app = sample_application(project_name, log_dir, app_id)
    app.run(halt_after=["result"])
    results_dir = os.path.join(log_dir, project_name, app_id)
    assert os.path.exists(results_dir)
    assert os.path.exists(log_output := os.path.join(results_dir, LocalTrackingClient.LOG_FILENAME))
    assert os.path.exists(
        graph_output := os.path.join(results_dir, LocalTrackingClient.GRAPH_FILENAME)
    )
    with open(log_output) as f:
        log_contents = [json.loads(item) for item in f.readlines()]
    with open(graph_output) as f:
        graph_contents = json.load(f)
    assert graph_contents["type"] == "application"
    app_model = ApplicationModel.parse_obj(graph_contents)
    assert app_model.entrypoint == "counter"
    assert app_model.actions[0].name == "counter"
    assert app_model.actions[1].name == "result"
    pre_run = [
        BeginEntryModel.model_validate(line)
        for line in log_contents
        if line["type"] == "begin_entry"
    ]
    post_run = [
        EndEntryModel.model_validate(line) for line in log_contents if line["type"] == "end_entry"
    ]
    span_start_model = [
        BeginSpanModel.model_validate(line) for line in log_contents if line["type"] == "begin_span"
    ]
    span_end_model = [
        EndSpanModel.model_validate(line) for line in log_contents if line["type"] == "end_span"
    ]
    attributes = [
        AttributeModel.model_validate(line) for line in log_contents if line["type"] == "attribute"
    ]
    assert len(pre_run) == 3
    assert len(post_run) == 3
    assert len(span_start_model) == 2  # two custom-defined spans
    assert len(span_end_model) == 2  # ditto
    assert not any(item.exception for item in post_run)
    assert len(attributes) == 2  # two attributes logged


def test_application_tracks_end_to_end_broken(tmpdir: str):
    app_id = str(uuid.uuid4())
    log_dir = os.path.join(tmpdir, "tracking")
    project_name = "test_application_tracks_end_to_end"
    app = sample_application(project_name, log_dir, app_id, broken=True)
    with pytest.raises(ValueError):
        app.run(halt_after=["result"])
    results_dir = os.path.join(log_dir, project_name, app_id)
    assert os.path.exists(results_dir)
    assert os.path.exists(log_output := os.path.join(results_dir, LocalTrackingClient.LOG_FILENAME))
    assert os.path.exists(
        graph_output := os.path.join(results_dir, LocalTrackingClient.GRAPH_FILENAME)
    )
    with open(log_output) as f:
        log_contents = [json.loads(item) for item in f.readlines()]
    with open(graph_output) as f:
        graph_contents = json.load(f)
    assert graph_contents["type"] == "application"
    app_model = ApplicationModel.model_validate(graph_contents)
    assert app_model.entrypoint == "counter"
    assert app_model.actions[0].name == "counter"
    assert app_model.actions[1].name == "result"
    pre_run = [
        BeginEntryModel.model_validate(line)
        for line in log_contents
        if line["type"] == "begin_entry"
    ]
    post_run = [
        EndEntryModel.model_validate(line) for line in log_contents if line["type"] == "end_entry"
    ]
    assert len(pre_run) == 2
    assert len(post_run) == 2
    assert len(post_run[-1].exception) > 0 and "Broken" in post_run[-1].exception


@pytest.mark.parametrize(
    "input_string, on_windows, expected_result",
    [
        ("Hello-World_123", False, True),
        ("Hello:World_123", False, True),
        ("Hello:World_123", True, False),
        ("Invalid:Chars*", False, False),
        ("Just$ymbols", True, False),
        ("Normal_Text", True, True),
    ],
)
def test__allowed_project_name(input_string, on_windows, expected_result):
    assert _allowed_project_name(input_string, on_windows) == expected_result


class DummyPersister(BaseStatePersister):
    """Dummy persistor."""

    def load(
        self, partition_key: str, app_id: Optional[str], sequence_id: Optional[int] = None, **kwargs
    ) -> Optional[PersistedStateData]:
        return PersistedStateData(
            partition_key="user123",
            app_id="123",
            sequence_id=5,
            position="counter",
            state=State({"count": 5}),
            created_at="",
            status="completed",
        )

    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        return ["123"]

    def save(
        self,
        partition_key: Optional[str],
        app_id: str,
        sequence_id: int,
        position: str,
        state: State,
        status: Literal["completed", "failed"],
        **kwargs,
    ):
        return


def test_persister_tracks_parent(tmpdir):
    result = Result("count").with_name("result")
    old_app_id = "old"
    new_app_id = "new"
    log_dir = os.path.join(tmpdir, "tracking")
    results_dir = os.path.join(log_dir, "test_persister_tracks_parent", new_app_id)
    project_name = "test_persister_tracks_parent"
    app: Application = (
        ApplicationBuilder()
        .with_actions(counter, result)
        .with_transitions(("counter", "result", default))
        .initialize_from(
            DummyPersister(),
            resume_at_next_action=True,
            default_state={},
            default_entrypoint="counter",
            fork_from_app_id=old_app_id,
            fork_from_partition_key="user123",
            fork_from_sequence_id=5,
        )
        .with_identifiers(app_id=new_app_id, partition_key="user123")
        .with_tracker(project=project_name, tracker="local", params={"storage_dir": log_dir})
        .build()
    )
    app.run(halt_after=["result"])
    assert os.path.exists(
        graph_output := os.path.join(results_dir, LocalTrackingClient.METADATA_FILENAME)
    )
    with open(graph_output) as f:
        metadata = json.load(f)
    metadata_parsed = ApplicationMetadataModel.model_validate(metadata)
    assert metadata_parsed.partition_key == "user123"
    assert metadata_parsed.parent_pointer.app_id == old_app_id
    assert metadata_parsed.parent_pointer.sequence_id == 5
    assert metadata_parsed.parent_pointer.partition_key == "user123"


def test_fork_children_have_correct_partition_key(tmpdir):
    """Tests that children.jsonl in the parent app directory has the correct
    partition_key for the forked child app. Regression test for #518."""
    old_app_id = "parent_app"
    new_app_id = "forked_app"
    partition_key = "user123"
    log_dir = os.path.join(tmpdir, "tracking")
    project_name = "test_fork_children_partition_key"
    tracking_client = LocalTrackingClient(project=project_name, storage_dir=log_dir)

    # Create the parent app first
    parent_app: Application = (
        ApplicationBuilder()
        .with_actions(counter, Result("count").with_name("result"))
        .with_transitions(
            ("counter", "counter", expr("counter < 3")),
            ("counter", "result", default),
        )
        .with_state(counter=0, break_at=-1)
        .with_entrypoint("counter")
        .with_identifiers(app_id=old_app_id, partition_key=partition_key)
        .with_tracker(tracking_client)
        .build()
    )
    parent_app.run(halt_after=["result"])

    # Fork from the parent
    forked_app: Application = (
        ApplicationBuilder()
        .with_actions(counter, Result("count").with_name("result"))
        .with_transitions(
            ("counter", "counter", expr("counter < 5")),
            ("counter", "result", default),
        )
        .initialize_from(
            tracking_client,
            resume_at_next_action=True,
            default_state={"counter": 0, "break_at": -1},
            default_entrypoint="counter",
            fork_from_app_id=old_app_id,
            fork_from_partition_key=partition_key,
            fork_from_sequence_id=2,
        )
        .with_identifiers(app_id=new_app_id, partition_key=partition_key)
        .with_tracker(tracking_client)
        .build()
    )
    forked_app.run(halt_after=["result"])

    # Check children.jsonl in the parent app directory
    children_path = os.path.join(
        log_dir, project_name, old_app_id, LocalTrackingClient.CHILDREN_FILENAME
    )
    assert os.path.exists(children_path), "children.jsonl should exist for the parent app"

    with open(children_path) as f:
        children = [ChildApplicationModel.model_validate(json.loads(line)) for line in f]

    assert len(children) == 1
    child = children[0]
    assert child.child.app_id == new_app_id
    assert (
        child.child.partition_key == partition_key
    ), f"Child partition_key should be '{partition_key}', got '{child.child.partition_key}'"
    assert child.event_type == "fork"


def test_multi_fork_tracking_client(tmpdir):
    """This is more of an end-to-end test. We shoudl probably break it out
    into smaller tests but the local tracking client being used as a persister is
    a bit of a complex case, and we don't want to get lost in the details.
    """
    common_app_id = uuid.uuid4()
    initial_app_id = f"new_{common_app_id}"
    # newer_app_id = "newer"
    log_dir = os.path.join(tmpdir, "tracking")
    # results_dir = os.path.join(log_dir, "test_persister_tracks_parent", new_app_id)
    project_name = "test_persister_tracks_parent"

    tracking_client = LocalTrackingClient(project=project_name, storage_dir=log_dir)

    class CallTracker(lifecycle.PostRunStepHook):
        def __init__(self):
            self.count = 0

        def post_run_step(self, action: Action, **kwargs):
            if action.name == "counter":
                self.count += 1

    def create_application(
        old_app_id: Optional[str], new_app_id: str, old_sequence_id: Optional[int], max_count: int
    ) -> Tuple[Application, CallTracker]:
        tracker = CallTracker()
        app: Application = (
            ApplicationBuilder()
            .with_actions(counter, Result("count").with_name("result"))
            .with_transitions(
                ("counter", "counter", expr(f"counter < {max_count}")),
                ("counter", "result", default),
            )
            .initialize_from(
                tracking_client,
                resume_at_next_action=True,
                default_state={"counter": 0, "break_at": -1},  # never break
                default_entrypoint="counter",
                fork_from_app_id=old_app_id,
                fork_from_sequence_id=old_sequence_id,
            )
            .with_identifiers(app_id=new_app_id)
            .with_tracker(tracking_client)
            .with_hooks(tracker)
            .build()
        )
        return app, tracker

    # create an initial one
    app_initial, tracker = create_application(None, initial_app_id, None, max_count=10)
    action_, result, state = app_initial.run(halt_after=["result"])  # Run all the way through
    assert state["counter"] == 10  # should have counted to 10
    assert tracker.count == 10  # 10 counts

    # create a new one from position 5

    forked_app_id = f"fork_1_{common_app_id}"
    forked_app_1, tracker = create_application(initial_app_id, forked_app_id, 5, max_count=15)
    assert forked_app_1.sequence_id == 5
    action_, result, state = forked_app_1.run(halt_after=["result"])  # Run all the way through
    assert state["counter"] == 15  # should have counted to 15
    assert tracker.count == 9  # start at 6, go to 15
    assert forked_app_1.parent_pointer.app_id == initial_app_id
    assert forked_app_1.parent_pointer.sequence_id == 5

    forked_forked_app_id = f"fork_2_{common_app_id}"
    forked_app_2, tracker = create_application(
        forked_app_id, forked_forked_app_id, 10, max_count=25
    )
    assert forked_app_2.sequence_id == 10
    action_, result, state = forked_app_2.run(halt_after=["result"])  # Run all the way through
    assert state["counter"] == 25  # should have counted to 15
    assert tracker.count == 14  # start at 11, go to 20

    assert forked_app_2.parent_pointer.app_id == forked_app_id
    assert forked_app_2.parent_pointer.sequence_id == 10

    # fork from latest
    # TODO -- break this up -- this test tests too much at once
    # This is a quick addition to test that forking from sequence_id=None picks up where the last one left off

    forked_forked_forked_app_id = f"fork_3_{common_app_id}"
    forked_app_3, tracker = create_application(
        forked_forked_app_id, forked_forked_forked_app_id, None, max_count=35
    )
    assert (
        forked_app_3.sequence_id == forked_app_2.sequence_id == 25
    )  # this should pick up where the last one left off
    assert forked_app_3.parent_pointer.app_id == forked_forked_app_id


def test_application_tracks_link_to_spawning_parent(tmpdir: str):
    """Tests that we record the parent of the spawned application in the metadata file for the spawned application."""
    app_id = str(uuid.uuid4())
    log_dir = os.path.join(tmpdir, "tracking_parent_test")
    project_name = "test_application_tracks_end_to_end_with_spawning_parent"
    # constructing this will cause the desired side-effect
    sample_application(project_name, log_dir, app_id, spawn_from=(f"spawn_{app_id}", 5))
    results_dir = os.path.join(log_dir, project_name, app_id)
    assert os.path.exists(results_dir)
    assert os.path.exists(
        metadata_output := os.path.join(results_dir, LocalTrackingClient.METADATA_FILENAME)
    )
    with open(metadata_output) as f:
        metadata = json.load(f)
    metadata_parsed = ApplicationMetadataModel.model_validate(metadata)
    assert metadata_parsed.spawning_parent_pointer.app_id == f"spawn_{app_id}"
    assert metadata_parsed.spawning_parent_pointer.sequence_id == 5


def test_application_tracks_link_from_spawning_parent(tmpdir: str):
    """Tests that we record the child in the parent's directory when instantiated."""
    spawning_parent_app_id = str(uuid.uuid4())
    project_name = "test_application_tracks_link_from_spawning_parent"
    log_dir = os.path.join(tmpdir, "tracking_child_test")
    # creates the directory for the parent
    # technically not needed (it'll create an empty directory), but nice to have
    sample_application(project_name, log_dir, spawning_parent_app_id)
    parent_result_dir = os.path.join(log_dir, project_name, spawning_parent_app_id)
    spawned_children = [str(uuid.uuid4()), str(uuid.uuid4())]
    for child_app_id in spawned_children:
        # constructing this will cause the desired side effect -- crating the pointer to the child in the parent's directory
        sample_application(
            project_name, log_dir, child_app_id, spawn_from=(spawning_parent_app_id, 5)
        )
        assert os.path.exists(
            children_output := os.path.join(
                parent_result_dir, LocalTrackingClient.CHILDREN_FILENAME
            )
        )
        with open(children_output) as f:
            children = [json.loads(line) for line in f.readlines()]
    children_parsed = [ChildApplicationModel.model_validate(child) for child in children]
    assert set(child.child.app_id for child in children_parsed) == set(spawned_children)
    assert all(child.event_type == "spawn_start" for child in children_parsed)


def test_that_we_fail_on_non_unicode_characters(tmp_path):
    """This is a test to log expected behavior.

    Right now it is on the developer to ensure that state can be encoded into UTF-8.

    This test is here to capture this assumption.
    """

    @action(reads=["test"], writes=["test"])
    def state_1(state: State) -> State:
        return state.update(test="test")

    @action(reads=["test"], writes=["test"])
    def state_2(state: State) -> State:
        return state.update(test="\ud800")  # Invalid UTF-8 byte sequence

    tracker = LocalTrackingClient(project="test", storage_dir=tmp_path)
    app: Application = (
        ApplicationBuilder()
        .with_actions(state_1, state_2)
        .with_transitions(("state_1", "state_2"), ("state_2", "state_1"))
        .with_tracker(tracker=tracker)
        .initialize_from(
            initializer=tracker,
            resume_at_next_action=False,
            default_entrypoint="state_1",
            default_state={},
        )
        .with_identifiers(app_id="3")
        .build()
    )

    with pytest.raises(ValueError):
        app.run(halt_after=["state_2"])


def test_that_we_can_read_write_local_tracker(tmp_path):
    """Integration like test to ensure we can write and then read what was written"""

    @action(
        reads=[],
        writes=[
            "text",
            "greek",
            "cyrillic",
            "hebrew",
            "arabic",
            "hindi",
            "chinese",
            "japanese",
            "korean",
            "emoji",
        ],
    )
    def state_1(state: State) -> State:
        text = "á, é, í, ó, ú, ñ, ü"
        greek = "α, β, γ, δ"
        cyrillic = "ж, ы, б, ъ"
        hebrew = "א, ב, ג, ד"
        arabic = "خ, د, ذ, ر"
        hindi = "अ, आ, इ, ई"
        chinese = "中, 国, 文"
        japanese = "日, 本, 語"
        korean = "한, 국, 어"
        emoji = "😀, 👍, 🚀, 🌍"
        return state.update(
            text=text,
            greek=greek,
            cyrillic=cyrillic,
            hebrew=hebrew,
            arabic=arabic,
            hindi=hindi,
            chinese=chinese,
            japanese=japanese,
            korean=korean,
            emoji=emoji,
        )

    @action(reads=["text"], writes=["text"])
    def state_2(state: State) -> State:
        return state.update(text="\x9d")  # encode-able UTF-8 sequence

    tracker = LocalTrackingClient(
        project="test",
        storage_dir=tmp_path,
    )

    for i in range(2):
        # reloads from log.jsonl in the second run and errors
        app: Application = (
            ApplicationBuilder()
            .with_actions(state_1, state_2)
            .with_transitions(("state_1", "state_2"), ("state_2", "state_1"))
            .with_tracker(tracker=tracker)
            .initialize_from(
                initializer=tracker,
                resume_at_next_action=False,
                default_entrypoint="state_1",
                default_state={},
            )
            .with_identifiers(app_id="3")
            .build()
        )

        app.run(halt_after=["state_2"])


def test_local_tracking_client_copy():
    """Tests tracking client .copy() method for serialization/parallelism.
    Internal-facing contracts but we want coverage here."""
    tracking_client = LocalTrackingClient("foo", "storage_dir", serde_kwargs={"foo": "bar"})
    copy = tracking_client.copy()
    assert copy.project_id == tracking_client.project_id
    assert copy.serde_kwargs == tracking_client.serde_kwargs
    assert copy.storage_dir == tracking_client.storage_dir
