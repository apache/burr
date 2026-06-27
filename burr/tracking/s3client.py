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
import datetime
import json
import logging
import queue
import re
import threading
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

import pydantic

from burr import system
from burr.common import types as burr_types
from burr.core import Action, ApplicationGraph, State, serde
from burr.integrations.base import require_plugin
from burr.tracking.base import SyncTrackingClient
from burr.tracking.client import StateKey, StreamState
from burr.tracking.common.models import (
    ApplicationMetadataModel,
    ApplicationModel,
    AttributeModel,
    BeginEntryModel,
    BeginSpanModel,
    EndEntryModel,
    EndSpanModel,
    EndStreamModel,
    FirstItemStreamModel,
    InitializeStreamModel,
    PointerModel,
)
from burr.visibility import ActionSpan

logger = logging.getLogger(__name__)

try:
    import boto3
except ImportError as e:
    require_plugin(
        e,
        "tracking-s3",
    )


def fire_and_forget(func):
    def wrapper(self, *args, **kwargs):
        if self.non_blocking:  # must be used with the S3TrackingClient

            def run():
                try:
                    func(self, *args, **kwargs)
                except Exception:
                    logger.exception(
                        "Exception occurred in fire-and-forget function: %s", func.__name__
                    )

            threading.Thread(target=run).start()
        return func(self, *args, **kwargs)

    return wrapper


# TODO -- move to common and share with client.py

INPUT_FILTERLIST = {"__tracer"}


def _format_exception(exception: Exception) -> Optional[str]:
    if exception is None:
        return None
    return "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))


INPUT_FILTERLIST = {"__tracer"}


def _filter_inputs(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in INPUT_FILTERLIST}


def _allowed_project_name(project_name: str, on_windows: bool) -> bool:
    allowed_chars = "a-zA-Z0-9_\-"
    if not on_windows:
        allowed_chars += ":"
    pattern = f"^[{allowed_chars}]+$"

    # Use regular expression to check if the string is valid
    return bool(re.match(pattern, project_name))


EventType = Union[
    BeginEntryModel,
    EndEntryModel,
    BeginSpanModel,
    EndSpanModel,
    AttributeModel,
    InitializeStreamModel,
    FirstItemStreamModel,
    EndStreamModel,
]


def unique_ordered_prefix() -> str:
    return datetime.datetime.now().isoformat() + str(uuid.uuid4())


def str_partition_key(partition_key: Optional[str]) -> str:
    return partition_key or "__none__"


class S3TrackingClient(SyncTrackingClient):
    """Synchronous tracking client that logs to S3. Experimental. Errs on the side of writing many little files.
    General schema is:
    - bucket
        - data/
            - project_name_1
                - YYYY/MM/DD/HH
                    - application.json (optional, will be on the first write from this tracker object)
                    - metadata.json (optional, will be on the first write from this tracker object)
                    - log_<timestamp>.jsonl
                    - log_<timestamp>.jsonl
                - YYYY/MM/DD/HH
                    ...
            ...

    This is designed to be fast to write, generally slow(ish) to read, but doable, and require no db.
    This also has a non-blocking mode that just launches a thread (expensive but doable solution)
    TODO -- get working with aiobotocore and an async tracker
    """

    def do_log_attributes(
        self,
        *,
        attributes: Dict[str, Any],
        action: str,
        action_sequence_id: int,
        span: Optional["ActionSpan"],
        app_id: str,
        partition_key: Optional[str],
        tags: dict,
        **future_kwargs: Any,
    ):
        # TODO -- log attributes to s3 as well
        # Coming up shortly
        for attribute_name, attribute in attributes.items():
            attribute_model = AttributeModel(
                key=attribute_name,
                action_sequence_id=action_sequence_id,
                span_id=span.uid if span is not None else None,
                value=serde.serialize(attribute, **self.serde_kwargs),
                tags=tags,
                time_logged=system.now(),
            )
            self.submit_log_event(attribute_model, app_id=app_id, partition_key=partition_key)

    def __init__(
        self,
        project: str,
        bucket: str,
        region: str = None,
        endpoint_url: Optional[str] = None,
        non_blocking: bool = False,
        serde_kwargs: Optional[dict] = None,
        unique_tracker_id: str = None,
        flush_interval: int = 5,
    ):
        self.bucket = bucket
        self.project = project
        self.region = region
        self.endpoint_url = endpoint_url
        self.non_blocking = non_blocking
        self.s3 = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)
        self.serde_kwargs = serde_kwargs or {}
        self.unique_tracker_id = (
            unique_tracker_id
            if unique_tracker_id is not None
            else datetime.datetime.now().isoformat() + "-" + str(uuid.uuid4())
        )
        self.log_queue = queue.Queue()  # Tuple[app_id, EventType]
        self.flush_interval = flush_interval
        self.max_batch_size = 10000  # rather large batch size -- why not? It'll flush every 5 seconds otherwise and we don't want to spam s3 with files
        self.initialized = False
        self.running = True
        self.init()
        self.stream_state: Dict[StateKey, StreamState] = dict()

    def _get_time_partition(self):
        time = datetime.datetime.now(datetime.UTC).isoformat()
        return [time[:4], time[5:7], time[8:10], time[11:13], time[14:]]

    def get_prefix(self):
        return [
            "data",
            self.project,
            *self._get_time_partition(),
        ]

    def init(self):
        if not self.initialized:
            logger.info("Initializing S3TrackingClient with flushing thread")
            thread = threading.Thread(target=self.thread)
            # This will quit when the main thread is ready to, and gracefully
            # But it will gracefully exit due to the "None" on the queue
            threading.Thread(
                target=lambda: threading.main_thread().join() or self.log_queue.put(None)
            ).start()
            thread.start()
            self.initialized = True

    def thread(self):
        batch = []
        last_flush_time = time.time()

        while self.running:
            try:
                logger.debug(f"Checking for new data to flush -- s3 batch is of size: {len(batch)}")
                # Wait up to flush_interval for new data
                item = self.log_queue.get(timeout=self.flush_interval)
                # signal that we're done
                if item is None:
                    self.log_events(batch)
                    self.running = False
                    break
                batch.append(item)
                # Check if batch is full or flush interval has passed
                if (
                    len(batch) >= self.max_batch_size
                    or (time.time() - last_flush_time) >= self.flush_interval
                ):
                    logger.debug(f"Flushing s3 batch with {len(batch)} events")
                    self.log_events(batch)
                    batch = []
                    last_flush_time = time.time()
            except queue.Empty:
                # Flush on timeout if there's any data
                if batch:
                    logger.debug(f"Flushing s3 batch on queue empty with {len(batch)} events")
                    self.log_events(batch)
                    batch = []
                    last_flush_time = time.time()

    def stop(self, thread: threading.Thread):
        self.running = False  # will stop the thread
        thread.join()  # then wait for it to be done
        events = []
        # Flush any remaining events
        while self.log_queue.qsize() > 0:
            events.append(self.log_queue.get())
        self.log_events(events)

    def submit_log_event(self, event: EventType, app_id: str, partition_key: str):
        self.log_queue.put((app_id, partition_key, event))

    def log_events(self, events: List[Tuple[str, EventType]]):
        events_by_app_id = {}
        for app_id, partition_key, event in events:
            if (app_id, partition_key) not in events_by_app_id:
                events_by_app_id[(app_id, partition_key)] = []
            events_by_app_id[(app_id, partition_key)].append(event)
        for (app_id, partition_key), app_events in events_by_app_id.items():
            logger.debug(f"Logging {len(app_events)} events for app {app_id}")
            min_sequence_id = min([e.sequence_id for e in app_events])
            max_sequence_id = max([e.sequence_id for e in app_events])
            path = [
                str_partition_key(partition_key),
                app_id,
                str(uuid.uuid4())
                + "__log.jsonl",  # in case we happen to have multiple at the same time....
            ]
            self.log_object(
                *path,
                data=app_events,
                metadata={
                    "min_sequence_id": str(min_sequence_id),
                    "max_sequence_id": str(max_sequence_id),
                },
            )

    def log_object(
        self,
        *path_within_project: str,
        data: Union[pydantic.BaseModel, List[pydantic.BaseModel]],
        metadata: Dict[str, str] = None,
    ):
        if metadata is None:
            metadata = {}
        metadata = {**metadata, "tracker_id": self.unique_tracker_id}
        full_path = self.get_prefix() + list(path_within_project)
        key = "/".join(full_path)
        if isinstance(data, list):
            body = "\n".join([d.model_dump_json() for d in data])
        else:
            body = data.model_dump_json()
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body, Metadata=metadata)

    @fire_and_forget
    def post_application_create(
        self,
        *,
        app_id: str,
        partition_key: Optional[str],
        state: "State",
        application_graph: "ApplicationGraph",
        parent_pointer: Optional[burr_types.ParentPointer],
        spawning_parent_pointer: Optional[burr_types.ParentPointer],
        **future_kwargs: Any,
    ):
        graph = ApplicationModel.from_application_graph(
            application_graph,
        )
        graph_path = [str_partition_key(partition_key), app_id, "graph.json"]
        self.log_object(*graph_path, data=graph)
        metadata = ApplicationMetadataModel(
            partition_key=partition_key,
            parent_pointer=PointerModel.from_pointer(parent_pointer),
            spawning_parent_pointer=PointerModel.from_pointer(spawning_parent_pointer),
        )
        metadata_path = [str_partition_key(partition_key), app_id, "metadata.json"]
        # we put these here to allow for quicker retrieval on the server side
        # It's a bit of a hack to put it all into metadata, but it helps with ingestion
        self.log_object(
            *metadata_path,
            data=metadata,
            metadata={
                "parent_pointer": json.dumps(dataclasses.asdict(parent_pointer))
                if parent_pointer is not None
                else "None",
                "spawning_parent_pointer": json.dumps(dataclasses.asdict(spawning_parent_pointer))
                if spawning_parent_pointer is not None
                else "None",
            },
        )

    def pre_run_step(
        self,
        *,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        state: "State",
        action: "Action",
        inputs: Dict[str, Any],
        **future_kwargs: Any,
    ):
        _filtered_inputs = _filter_inputs(inputs)
        pre_run_entry = BeginEntryModel(
            start_time=datetime.datetime.now(),
            action=action.name,
            inputs=serde.serialize(_filtered_inputs, **self.serde_kwargs),
            sequence_id=sequence_id,
        )
        self.submit_log_event(pre_run_entry, app_id, partition_key)

    def post_run_step(
        self,
        *,
        app_id: str,
        partition_key: str,
        sequence_id: int,
        state: "State",
        action: "Action",
        result: Optional[Dict[str, Any]],
        exception: Exception,
        **future_kwargs: Any,
    ):
        post_run_entry = EndEntryModel(
            end_time=datetime.datetime.now(),
            action=action.name,
            result=serde.serialize(result, **self.serde_kwargs),
            sequence_id=sequence_id,
            exception=_format_exception(exception),
            state=state.serialize(),
        )
        self.submit_log_event(post_run_entry, app_id, partition_key)

    def pre_start_span(
        self,
        *,
        action_sequence_id: int,
        partition_key: str,
        app_id: str,
        span: ActionSpan,
        span_dependencies: list[str],
        **future_kwargs: Any,
    ):
        begin_span_model = BeginSpanModel(
            start_time=datetime.datetime.now(),
            action_sequence_id=action_sequence_id,
            span_id=span.uid,
            parent_span_id=span.parent.uid if span.parent else None,
            span_dependencies=span_dependencies,
            span_name=span.name,
        )
        self.submit_log_event(begin_span_model, app_id, partition_key)

    def post_end_span(
        self,
        *,
        action: str,
        action_sequence_id: int,
        span: ActionSpan,
        span_dependencies: list[str],
        app_id: str,
        partition_key: str,
        **future_kwargs: Any,
    ):  # TODO -- implemenet
        end_span_model = EndSpanModel(
            end_time=datetime.datetime.now(),
            action_sequence_id=action_sequence_id,
            span_id=span.uid,
        )
        self.submit_log_event(end_span_model, app_id, partition_key)

    def copy(self):
        return S3TrackingClient(
            project=self.project,
            bucket=self.bucket,
            region=self.region,
            endpoint_url=self.endpoint_url,
            non_blocking=self.non_blocking,
            serde_kwargs=self.serde_kwargs,
            unique_tracker_id=self.unique_tracker_id,
            flush_interval=self.flush_interval,
        )

    def pre_start_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        initialize_stream_model = InitializeStreamModel(
            action_sequence_id=sequence_id,
            span_id=None,
            stream_init_time=system.now(),
        )
        self.submit_log_event(initialize_stream_model, app_id, partition_key)
        self.stream_state[app_id, action, partition_key] = StreamState(
            stream_init_time=system.now(),
            count=0,
        )

    def post_stream_item(
        self,
        *,
        item: Any,
        item_index: int,
        stream_initialize_time: datetime.datetime,
        first_stream_item_start_time: datetime.datetime,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        stream_state = self.stream_state[app_id, action, partition_key]
        if stream_state.count == 0:
            stream_state.count += 1
            self.submit_log_event(
                FirstItemStreamModel(
                    action_sequence_id=sequence_id,
                    span_id=None,
                    first_item_time=system.now(),
                ),
                app_id,
                partition_key,
            )
        else:
            stream_state.count += 1

    def post_end_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        stream_state = self.stream_state[app_id, action, partition_key]
        self.submit_log_event(
            EndStreamModel(
                action_sequence_id=sequence_id,
                span_id=None,
                end_time=system.now(),
                items_streamed=stream_state.count,
            ),
            app_id,
            partition_key,
        )
        del self.stream_state[app_id, action, partition_key]
