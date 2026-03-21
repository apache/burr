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

import abc
import dataclasses
import datetime

from burr.common.types import BaseCopyable
from burr.lifecycle.base import (
    DoLogAttributeHook,
    PostEndStreamHook,
    PostStreamItemHook,
    PreStartStreamHook,
)

# this is a quick hack to get it to work on windows
# we'll have to implement a proper lock later
# but its better that it works than breaks on import
try:
    import fcntl
except ImportError:

    class fcntl:
        @staticmethod
        def flock(*args, **kwargs):
            return

        LOCK_EX = 0
        LOCK_UN = 0


import json
import logging
import os
import re
import traceback
from abc import ABC
from typing import Any, Dict, Optional, Tuple

try:
    from typing import Self
except ImportError:
    Self = "Self"

from burr import system
from burr.common import types as burr_types
from burr.core import Action, ApplicationGraph, State, serde
from burr.core.persistence import BaseStateLoader, PersistedStateData
from burr.integrations.base import require_plugin
from burr.lifecycle import (
    PostApplicationCreateHook,
    PostEndSpanHook,
    PostRunStepHook,
    PreRunStepHook,
    PreStartSpanHook,
)
from burr.tracking.common.models import (
    ApplicationMetadataModel,
    ApplicationModel,
    AttributeModel,
    BeginEntryModel,
    BeginSpanModel,
    ChildApplicationModel,
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
    import pydantic
except ImportError as e:
    require_plugin(
        e,
        "tracking-client",
    )


def _format_exception(exception: Exception) -> Optional[str]:
    if exception is None:
        return None
    return "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))


INPUT_FILTERLIST = {"__tracer"}


def _filter_inputs(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in INPUT_FILTERLIST}


def _allowed_project_name(project_name: str, on_windows: bool) -> bool:
    allowed_chars = r"a-zA-Z0-9_\-"
    if not on_windows:
        allowed_chars += ":"
    pattern = f"^[{allowed_chars}]+$"

    # Use regular expression to check if the string is valid
    return bool(re.match(pattern, project_name))


@dataclasses.dataclass
class StreamState:
    stream_init_time: datetime.datetime
    count: Optional[int]


StateKey = Tuple[str, str, Optional[str]]


class SyncTrackingClient(
    PostApplicationCreateHook,
    PreRunStepHook,
    PostRunStepHook,
    PreStartSpanHook,
    PostEndSpanHook,
    DoLogAttributeHook,
    PreStartStreamHook,
    PostStreamItemHook,
    PostEndStreamHook,
    BaseCopyable,
    ABC,
):
    @abc.abstractmethod
    def copy(self) -> Self:
        """Clones the tracking client. This is useful for forking applications.
        Note we have to copy the tracking client as it is stateful for tracking.
        We may make this called internally if it has started already,
        or make it so it carries multiple states at once.

        :return: a copy of the self.
        """
        pass


class LocalTrackingClient(
    SyncTrackingClient,
    BaseStateLoader,
):
    """Tracker to track locally -- goes along with the Burr UI. Writes
    down the following:
    #. The whole application + debugging information (e.g. source code) to a file
    #. A line for the start/end of each step
    """

    GRAPH_FILENAME = "graph.json"
    METADATA_FILENAME = "metadata.json"
    LOG_FILENAME = "log.jsonl"
    CHILDREN_FILENAME = (
        "children.jsonl"  # any applications that are spawned or forked will show up here
    )
    # This is purely an optimization for bi-directional relationships using filesystems (denormalized data)
    DEFAULT_STORAGE_DIR = "~/.burr"

    def __init__(
        self,
        project: str,
        storage_dir: str = DEFAULT_STORAGE_DIR,
        serde_kwargs: Optional[Dict[str, Any]] = None,
    ):
        """Instantiates a local tracking client. This will create the following directories, if they don't exist:
        #. The base directory (defaults to ~/.burr)
        #. The project directory (defaults to ~/.burr/<project>)
        #. The application directory (defaults to ~/.burr/<project>/<app_id>) on each

        On application create, it will write the state machine to the application directory.
        On pre/post run step, it will write the start/end of each step to the application directory.

        :param project: Project name -- if this already exists it will be used, otherwise it will be created.
        :param storage_dir: Storage directory
        """

        self.f = None
        if not _allowed_project_name(project, on_windows=system.IS_WINDOWS):
            raise ValueError(
                f"Project: {project} is not valid. Project name cannot contain non-alphanumeric (except _ and -) characters."
                "We will be relaxing this restriction later but for now please rename your project!"
            )
        self.raw_storage_dir = storage_dir
        self.storage_dir = LocalTrackingClient.get_storage_path(project, storage_dir)
        self.project_id = project
        self.serde_kwargs = serde_kwargs if serde_kwargs is not None else {}
        # app_id, action, partition_key  -> stream data so we can track
        self.stream_state: Dict[StateKey, StreamState] = dict()

    def _log_child_relationships(
        self,
        fork_parent_pointer_model: Optional[burr_types.ParentPointer],
        spawn_parent_pointer_model: Optional[burr_types.ParentPointer],
        app_id: str,
        partition_key: Optional[str] = None,
    ):
        """Logs a child relationship. This is special as it does not log to the main log file. Rather
        it logs within the parent directory. Note this only exists to maintain (denormalized) bidirectional
        pointers, as the filesystem is not a database, so querying is very inefficient.

        This uses fctl.flock to ensure that the file is not written to by multiple processes at the same time.
        Read may be corrupted (by the server), as it does not use the lock, but that will retry.
        """
        parent_relationships = []
        if fork_parent_pointer_model is not None:
            parent_relationships.append(
                # This effectively inverts the pointers
                # The logging call is being made from the child, so we're logging to the parent
                # We do it once for the fork_parent (if it exists), and once for the spawn_parent (if it exists)
                (
                    fork_parent_pointer_model.app_id,
                    ChildApplicationModel(
                        child=PointerModel(
                            app_id=app_id,
                            sequence_id=None,
                            partition_key=partition_key,
                        ),
                        event_time=datetime.datetime.now(),
                        event_type="fork",
                        # this is the sequence ID at which this link occurred (from the parent)
                        sequence_id=fork_parent_pointer_model.sequence_id,
                    ),
                )
            )
        if spawn_parent_pointer_model is not None:
            # See the notes above
            parent_relationships.append(
                (
                    spawn_parent_pointer_model.app_id,
                    ChildApplicationModel(
                        child=PointerModel(
                            app_id=app_id,
                            sequence_id=None,
                            partition_key=partition_key,
                        ),
                        event_time=datetime.datetime.now(),
                        event_type="spawn_start",
                        sequence_id=spawn_parent_pointer_model.sequence_id,
                    ),
                )
            )
        for parent_id, child_of in parent_relationships:
            parent_path = os.path.join(self.storage_dir, parent_id)
            if not os.path.exists(parent_path):
                # This currently makes the parent directory so that it does not fail
                # If the parent directory exists we'll just use that
                os.makedirs(parent_path)
            parent_children_list_path = os.path.join(
                parent_path, LocalTrackingClient.CHILDREN_FILENAME
            )
            # Order should not matter here
            # currently we write start events, so it really won't matter
            # but in the future we'll write end events, but we'll parse it in a
            # way that allows them to be interwoven
            with open(parent_children_list_path, "a", errors="replace", encoding="utf-8") as f:
                fileno = f.fileno()
                try:
                    fcntl.flock(fileno, fcntl.LOCK_EX)
                    f.write(child_of.model_dump_json() + "\n")
                finally:
                    # we always want to release the lock so its not held indefinitely
                    fcntl.flock(fileno, fcntl.LOCK_UN)

    def copy(self) -> "LocalTrackingClient":
        return LocalTrackingClient(
            project=self.project_id,
            storage_dir=self.raw_storage_dir,
            serde_kwargs=self.serde_kwargs,
        )

    @classmethod
    def get_storage_path(cls, project, storage_dir) -> str:
        return str(os.path.join(os.path.expanduser(storage_dir), project))

    @classmethod
    def app_log_exists(
        cls,
        project: str,
        app_id: str,
        storage_dir: str = DEFAULT_STORAGE_DIR,
    ) -> bool:
        """Function to check if state exists for a given project and app_id.

        :param project: the name of the project
        :param app_id: the application instance id
        :param storage_dir: the storage directory.
        :return: True if state exists, False otherwise.
        """
        path = os.path.join(cls.get_storage_path(project, storage_dir), app_id, cls.LOG_FILENAME)
        if not os.path.exists(path):
            return False
        lines = open(path, "r", errors="replace", encoding="utf-8").readlines()
        if len(lines) == 0:
            return False
        return True

    @classmethod
    def load_state(
        cls,
        project: str,
        app_id: str,
        sequence_id: int = -1,
        storage_dir: str = DEFAULT_STORAGE_DIR,
    ) -> tuple[dict, str]:
        """This is deprecated and will be removed when we migrate over demos. Do not use! Instead use
        the persistence API :py:class:`initialize_from <burr.core.application.ApplicationBuilder.initialize_from>`
        to load state.

        It defaults to loading the last state, but you can supply a sequence number.

        This is a temporary solution -- not particularly ergonomic, and makes assumptions (particularly that
        all logging is in order), which is fine for now. We will be improving this and making it a first-class
        citizen.


        :param project: the name of the project
        :param app_id: the application instance id
        :param sequence_id: the sequence number of the state to load. Defaults to last index (i.e. -1).
        :param storage_dir: the storage directory.
        :return: the state as a dictionary, and the entry point as a string.
        """
        if sequence_id is None:
            sequence_id = -1  # get the last one
        path = os.path.join(cls.get_storage_path(project, storage_dir), app_id, cls.LOG_FILENAME)
        if not os.path.exists(path):
            raise ValueError(f"No logs found for {project}/{app_id} under {storage_dir}")
        with open(path, "r", errors="replace", encoding="utf-8") as f:
            json_lines = f.readlines()
        # load as JSON
        json_lines = [json.loads(js_line) for js_line in json_lines]
        # filter to only end_entry
        json_lines = [js_line for js_line in json_lines if js_line["type"] == "end_entry"]
        try:
            line = json_lines[sequence_id]
        except IndexError:
            raise ValueError(f"Sequence number {sequence_id} not found for {project}/{app_id}.")
        # check sequence number matches if non-negative; will break if either is None.
        line_seq = int(line["sequence_id"])
        if -1 < sequence_id != line_seq:
            logger.warning(
                f"Sequence number mismatch. For {project}/{app_id}: "
                f"actual:{line_seq} != expected:{sequence_id}"
            )
        # get the prior state
        prior_state = line["state"]
        entry_point = line["action"]
        # delete internally stuff. We can't loop over the keys and delete them in the same loop
        to_delete = []
        for key in prior_state.keys():
            # remove any internal "__" state
            if key.startswith("__"):
                to_delete.append(key)
        for key in to_delete:
            del prior_state[key]
        prior_state["__SEQUENCE_ID"] = line_seq  # add the sequence id back
        return prior_state, entry_point

    def _ensure_dir_structure(self, app_id: str):
        if not os.path.exists(self.storage_dir):
            logger.info(f"Creating storage directory: {self.storage_dir}")
            os.makedirs(self.storage_dir)
        application_path = os.path.join(self.storage_dir, app_id)
        if not os.path.exists(application_path):
            logger.info(f"Creating application directory: {application_path}")
            os.makedirs(application_path)

    def __setstate__(self, state):
        self.__dict__.update(state)

    def __getstate__(self):
        out = {
            key: value for key, value in self.__dict__.items() if key != "f"
        }  # the file we don't want to serialize
        # Note that this will only work if we also call post_application_create
        # For now that's OK as that's the only reason we'll add it -- if we want more distribution later we'll have to serialize the file
        out["f"] = None
        return out

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
        self._ensure_dir_structure(app_id)
        self.f = open(
            os.path.join(self.storage_dir, app_id, self.LOG_FILENAME),
            "a",
            encoding="utf-8",
            errors="replace",
        )

        graph_path = os.path.join(self.storage_dir, app_id, self.GRAPH_FILENAME)
        if os.path.exists(graph_path):
            logger.info(f"Graph already exists at {graph_path}. Not overwriting.")
            return
        graph = ApplicationModel.from_application_graph(
            application_graph,
        ).model_dump()
        with open(graph_path, "w", encoding="utf-8", errors="replace") as f:
            json.dump(graph, f)

        metadata_path = os.path.join(self.storage_dir, app_id, self.METADATA_FILENAME)
        if os.path.exists(metadata_path):
            logger.info(f"Metadata already exists at {metadata_path}. Not overwriting.")
            return
        metadata = ApplicationMetadataModel(
            partition_key=partition_key,
            parent_pointer=PointerModel.from_pointer(parent_pointer),
            spawning_parent_pointer=PointerModel.from_pointer(spawning_parent_pointer),
        ).model_dump()
        with open(metadata_path, "w", errors="replace", encoding="utf-8") as f:
            json.dump(metadata, f)

        # Append to the parents of this the pointer to this, now
        self._log_child_relationships(
            parent_pointer,
            spawning_parent_pointer,
            app_id,
            partition_key=partition_key,
        )

    def _append_write_line(self, model: pydantic.BaseModel):
        self.f.write(model.model_dump_json() + "\n")
        self.f.flush()

    def pre_run_step(
        self,
        state: State,
        action: Action,
        inputs: Dict[str, Any],
        sequence_id: int,
        **future_kwargs: Any,
    ):
        _filtered_inputs = _filter_inputs(inputs)
        pre_run_entry = BeginEntryModel(
            start_time=datetime.datetime.now(),
            action=action.name,
            inputs=serde.serialize(_filtered_inputs, **self.serde_kwargs),
            sequence_id=sequence_id,
        )
        self._append_write_line(pre_run_entry)

    def post_run_step(
        self,
        state: State,
        action: Action,
        result: Optional[dict],
        sequence_id: int,
        exception: Exception,
        **future_kwargs: Any,
    ):
        post_run_entry = EndEntryModel(
            end_time=datetime.datetime.now(),
            action=action.name,
            result=serde.serialize(result, **self.serde_kwargs),
            sequence_id=sequence_id,
            exception=_format_exception(exception),
            state=state.serialize(**self.serde_kwargs),
        )
        self._append_write_line(post_run_entry)

    def pre_start_span(
        self,
        *,
        action: str,
        action_sequence_id: int,
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
        self._append_write_line(begin_span_model)

    def post_end_span(
        self,
        *,
        action: str,
        action_sequence_id: int,
        span: ActionSpan,
        span_dependencies: list[str],
        **future_kwargs: Any,
    ):
        end_span_model = EndSpanModel(
            end_time=datetime.datetime.now(),
            action_sequence_id=action_sequence_id,
            span_id=span.uid,
        )
        self._append_write_line(end_span_model)

    def do_log_attributes(
        self,
        *,
        attributes: Dict[str, Any],
        tags: dict,
        action: str,
        action_sequence_id: int,
        span: Optional["ActionSpan"],
        **future_kwargs: Any,
    ):
        for attribute_name, attribute in attributes.items():
            attribute_model = AttributeModel(
                key=attribute_name,
                action_sequence_id=action_sequence_id,
                span_id=span.uid if span is not None else None,
                value=serde.serialize(attribute, **self.serde_kwargs),
                tags=tags,
                time_logged=system.now(),
            )
            self._append_write_line(attribute_model)

    def pre_start_stream(
        self,
        *,
        action: str,
        sequence_id: int,
        app_id: str,
        partition_key: Optional[str],
        **future_kwargs: Any,
    ):
        self._append_write_line(
            InitializeStreamModel(
                action_sequence_id=sequence_id,
                span_id=None,
                stream_init_time=system.now(),
            )
        )
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
            self._append_write_line(
                FirstItemStreamModel(
                    action_sequence_id=sequence_id,
                    span_id=None,
                    first_item_time=system.now(),
                )
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
        self._append_write_line(
            EndStreamModel(
                action_sequence_id=sequence_id,
                span_id=None,
                end_time=system.now(),
                items_streamed=stream_state.count,
            )
        )
        del self.stream_state[app_id, action, partition_key]

    def __del__(self):
        if self.f is not None:
            self.f.close()

    def list_app_ids(self, partition_key: str, **kwargs) -> list[str]:
        # TODO:
        return []

    def load(
        self, partition_key: str, app_id: Optional[str], sequence_id: Optional[int] = None, **kwargs
    ) -> Optional[PersistedStateData]:
        # TODO:
        if app_id is None:
            return  # no application ID
        path = os.path.join(self.storage_dir, app_id, self.LOG_FILENAME)
        if not os.path.exists(path):
            return None
        with open(path, "r", errors="replace", encoding="utf-8") as f:
            json_lines = f.readlines()
        if len(json_lines) == 0:
            return None  # in this case we have not logged anything yet
        # load as JSON
        json_lines = [json.loads(js_line) for js_line in json_lines]
        # filter to only end_entry
        line = None
        if sequence_id is None:
            # get the last one, we want to start at the end
            for _line in reversed(json_lines):
                if _line["type"] == "end_entry":
                    sequence_id = _line["sequence_id"]
                    line = _line
                    break
        else:
            for js_line in json_lines:
                if js_line["type"] == "end_entry":
                    if js_line["sequence_id"] == sequence_id:
                        line = js_line

        if line is None:
            raise ValueError(
                f"Sequence number {sequence_id} not found for {self.project_id}/{app_id}."
            )
        prior_state = line["state"]
        position = line["action"]
        # delete internally stuff. We can't loop over the keys and delete them in the same loop
        to_delete = []
        for key in prior_state.keys():
            # remove any internal "__" state
            if key.startswith("__"):
                to_delete.append(key)
        for key in to_delete:
            del prior_state[key]
        prior_state["__SEQUENCE_ID"] = sequence_id  # add the sequence id back
        return PersistedStateData(
            partition_key=partition_key,
            app_id=app_id,
            sequence_id=sequence_id,
            position=position,
            state=State.deserialize(prior_state, **self.serde_kwargs),
            created_at=datetime.datetime.fromtimestamp(os.path.getctime(path)).isoformat(),
            status="completed" if line["exception"] is None else "failed",
        )


# TODO -- implement async version
# class AsyncTrackingClient(PreRunStepHookAsync, PostRunStepHookAsync, PostApplicationCreateHook):
#     def post_application_create(self, *, state: State, state_graph: ApplicationGraph, **future_kwargs: Any):
#         pass
#
#     async def pre_run_step(self, *, state: State, action: Action, **future_kwargs: Any):
#         raise NotImplementedError(f"TODO: {self.__class__.__name__}.pre_run_step")
#
#     async def post_run_step(self, *, state: State, action: Action, result: Optional[dict], exception: Exception, **future_kwargs: Any):
#         raise NotImplementedError(f"TODO: {self.__class__.__name__}.pre_run_step")
#
