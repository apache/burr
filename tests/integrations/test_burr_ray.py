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

import uuid
from typing import Any, Dict, Generator

import pytest
import ray

from burr.core import (
    ApplicationBuilder,
    ApplicationContext,
    GraphBuilder,
    Result,
    State,
    action,
    expr,
)
from burr.core.parallelism import MapStates, RunnableGraph, SubgraphType
from burr.integrations.ray import RayExecutor


@pytest.fixture(scope="module")
def init():
    ray.init()
    yield "initialized"
    ray.shutdown()


def test_ray_executor_simple(init):
    executor = RayExecutor()

    futures = [executor.submit(lambda x: x * x, num) for num in range(0, 10)]
    results = [future.result(timeout=5) for future in futures]  # Adjust timeout as necessary
    expected_results = [num * num for num in range(0, 10)]
    assert results == expected_results, "Each number should be squared correctly"


def test_ray_executor_end_to_end_persistence(init, tmpdir):
    """Largely a duplicate of the test_parallelism test_end_to_end test with a few small changes.
    We don't have persistence as sqlite + ray are not happy together (need to shut down resources
    better, more likely, but really people should use a multi-tennant db. We should consider
    unifying but not worth it now"""

    MIN_NUMBER = 90
    MAX_NUMBER = 100

    # dummy as we want an initial action to decide between odd/even next
    @action(reads=["n"], writes=["n", "original_n"])
    def initial(state: State, __context: ApplicationContext) -> State:
        # This assert ensures we only visit once per app, globally
        # Thus if we're restarting this will break
        return state.update(original_n=state["n"])

    @action(reads=["n"], writes=["n", "n_history"])
    def even(state: State) -> State:
        return state.update(n=state["n"] // 2).append(n_history=state["n"])

    @action(reads=["n"], writes=["n", "n_history"])
    def odd(state: State) -> State:
        return state.update(n=3 * state["n"] + 1).append(n_history=state["n"])

    collatz_graph = (
        GraphBuilder()
        .with_actions(
            initial,
            even,
            odd,
            result=Result("n_history"),
        )
        .with_transitions(
            (["initial", "even"], "result", expr("n == 1")),
            (["initial", "even", "odd"], "even", expr("n % 2 == 0")),
            (["initial", "even", "odd"], "odd", expr("n % 2 != 0")),
        )
        .build()
    )

    @action(reads=[], writes=["ns"])
    def map_step(state: State, min_number: int = MIN_NUMBER, max_number: int = MAX_NUMBER) -> State:
        return state.update(ns=list(range(min_number, max_number)))

    class ParallelCollatz(MapStates):
        def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[State, None, None]:
            for item in state["ns"]:
                yield state.update(n=item)

        def action(self, state: State, inputs: Dict[str, Any]) -> SubgraphType:
            return RunnableGraph(
                collatz_graph,
                entrypoint="initial",
                halt_after=["result"],
            )

        def reduce(self, state: State, results: Generator[State, None, None]) -> State:
            new_state = state
            count_mapping = {}
            for result in results:
                count_mapping[result["original_n"]] = len(result["n_history"])
            return new_state.update(counts=count_mapping)

        @property
        def writes(self) -> list[str]:
            return ["counts"]

        @property
        def reads(self) -> list[str]:
            return ["ns"]

    app_id = f"collatz_test_{str(uuid.uuid4())}"
    containing_application = (
        ApplicationBuilder()
        .with_actions(
            map_step,
            parallel_collatz=ParallelCollatz(),
            final=Result("counts"),
        )
        .with_transitions(
            ("map_step", "parallel_collatz"),
            ("parallel_collatz", "final"),
        )
        .with_identifiers(app_id=app_id)
        .with_parallel_executor(RayExecutor)
        .with_entrypoint("map_step")
        .build()
    )
    *_, final_state = containing_application.run(halt_after=["final"])
    assert len(final_state["counts"]) == MAX_NUMBER - MIN_NUMBER


def _map_blob_writes_app(app_id: str, object_store, tracker=None):
    @action(reads=["n"], writes=["blob"])
    def write_blob(state: State, __context: ApplicationContext) -> State:
        ref = __context.object_store.put_artifact(f"blob-{state['n']}".encode())
        return state.update(blob=ref)

    class MapBlobs(MapStates):
        def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[State, None, None]:
            for n in range(3):
                yield state.update(n=n)

        def action(self, state: State, inputs: Dict[str, Any]) -> SubgraphType:
            return RunnableGraph.create(write_blob)

        def reduce(self, state: State, results: Generator[State, None, None]) -> State:
            return state.update(refs=[result["blob"] for result in results])

        @property
        def writes(self) -> list[str]:
            return ["refs"]

        @property
        def reads(self) -> list[str]:
            return []

    builder = (
        ApplicationBuilder()
        .with_actions(map_blobs=MapBlobs())
        .with_transitions()
        .with_identifiers(app_id=app_id)
        .with_parallel_executor(RayExecutor)
        .with_object_store(object_store)
        .with_entrypoint("map_blobs")
    )
    if tracker is not None:
        builder = builder.with_tracker(tracker)
    return builder.build()


def test_ray_executor_ships_s3_object_store_to_workers(init):
    """Regression test: the object store is carried to Ray workers by the context and the
    sub-application tasks, so it must survive pickling -- S3ArtifactStore drops its boto3 client
    and rebuilds it on the worker. The tasks here never call S3; this only exercises shipping the
    store and running the graph."""
    from burr.integrations.artifacts.s3 import S3ArtifactStore

    store = S3ArtifactStore.from_values(
        bucket="my-bucket",
        client_kwargs={
            "region_name": "us-east-1",
            "aws_access_key_id": "test",
            "aws_secret_access_key": "test",
        },
    )

    @action(reads=["n"], writes=["n_squared"])
    def square(state: State, __context: ApplicationContext) -> State:
        assert __context.object_store.bucket == "my-bucket"
        return state.update(n_squared=state["n"] ** 2)

    class MapSquares(MapStates):
        def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[State, None, None]:
            for n in range(3):
                yield state.update(n=n)

        def action(self, state: State, inputs: Dict[str, Any]) -> SubgraphType:
            return RunnableGraph.create(square)

        def reduce(self, state: State, results: Generator[State, None, None]) -> State:
            return state.update(squares=sorted(result["n_squared"] for result in results))

        @property
        def writes(self) -> list[str]:
            return ["squares"]

        @property
        def reads(self) -> list[str]:
            return []

    app = (
        ApplicationBuilder()
        .with_actions(map_squares=MapSquares())
        .with_transitions()
        .with_parallel_executor(RayExecutor)
        .with_object_store(store)
        .with_entrypoint("map_squares")
        .build()
    )
    *_, final_state = app.run(halt_after=["map_squares"])
    assert final_state["squares"] == [0, 1, 4]


def test_ray_executor_workers_write_and_track_artifacts_through_object_store(init, tmpdir):
    """Sub-applications on Ray workers write artifacts through the shipped store, and the
    cascaded tracker serializes their state (containing ArtifactRefs) on the worker; the parent
    can read every artifact back."""
    import glob
    import json
    import os

    from burr.core.artifacts import LocalFileSystemArtifactStore
    from burr.tracking.client import LocalTrackingClient

    store = LocalFileSystemArtifactStore(str(tmpdir / "blobs"))
    tracker = LocalTrackingClient(project="ray_artifacts", storage_dir=str(tmpdir / "tracking"))
    app = _map_blob_writes_app(f"ray_artifacts_{uuid.uuid4()}", store, tracker=tracker)

    *_, final_state = app.run(halt_after=["map_blobs"])

    assert sorted(store.get_artifact(ref) for ref in final_state["refs"]) == [
        b"blob-0",
        b"blob-1",
        b"blob-2",
    ]
    child_states = []
    for path in glob.glob(os.path.join(str(tmpdir), "tracking", "ray_artifacts", "*", "log.jsonl")):
        for line in open(path):
            entry = json.loads(line)
            if entry["type"] == "end_entry" and "blob" in entry["state"]:
                child_states.append(entry["state"])
    assert len(child_states) == 3
    assert all(state["blob"]["__burr_serde__"] == "ArtifactRef" for state in child_states)


def test_ray_workers_persist_and_reload_state_through_store_dependent_serde(init, tmpdir):
    """Type- and field-based serde that use the object store run on Ray workers both when child
    state is saved and when it is reloaded: the first run stops each child after `produce`; the
    second resumes the same children, which deserialize their state on the worker (into lazy
    values) and continue with `summarize`."""
    from burr.core import GraphBuilder
    from burr.core.artifacts import LocalFileSystemArtifactStore
    from burr.tracking.client import LocalTrackingClient

    from tests.integrations import ray_artifact_serde

    child_graph = (
        GraphBuilder()
        .with_actions(produce=ray_artifact_serde.produce, summarize=ray_artifact_serde.summarize)
        .with_transitions(("produce", "summarize"))
        .build()
    )

    class MapChildren(MapStates):
        def __init__(self, halt_after: str):
            super().__init__()
            self.halt_after = halt_after

        def states(
            self, state: State, context: ApplicationContext, inputs: Dict[str, Any]
        ) -> Generator[State, None, None]:
            for n in range(3):
                yield state.update(n=n)

        def action(self, state: State, inputs: Dict[str, Any]) -> SubgraphType:
            return RunnableGraph(child_graph, entrypoint="produce", halt_after=[self.halt_after])

        def reduce(self, state: State, results: Generator[State, None, None]) -> State:
            results = list(results)
            return state.update(
                summaries=sorted(r.get("summary") for r in results if "summary" in r),
                loaded_lazily=[r.get("loaded_lazily") for r in results],
            )

        @property
        def writes(self) -> list[str]:
            return ["summaries", "loaded_lazily"]

        @property
        def reads(self) -> list[str]:
            return []

    store = LocalFileSystemArtifactStore(str(tmpdir / "blobs"))
    tracker = LocalTrackingClient(project="ray_serde", storage_dir=str(tmpdir / "tracking"))

    def run(halt_after: str) -> State:
        app = (
            ApplicationBuilder()
            .with_actions(map_children=MapChildren(halt_after))
            .with_transitions()
            .with_identifiers(app_id="ray_serde_parent")
            .with_parallel_executor(RayExecutor)
            .with_object_store(store)
            .with_tracker(tracker)
            .initialize_from(
                tracker,
                resume_at_next_action=False,
                default_state={},
                default_entrypoint="map_children",
            )
            .build()
        )
        *_, state = app.run(halt_after=["map_children"])
        return state

    run(halt_after="produce")
    final_state = run(halt_after="summarize")

    assert final_state["summaries"] == [f"blob-{n}|report-{n}" for n in range(3)]
    assert final_state["loaded_lazily"] == [True, True, True]
