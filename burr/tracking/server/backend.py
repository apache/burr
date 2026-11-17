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
import collections
import importlib
import json
import logging
import os.path
import sys
from datetime import datetime
from typing import Any, Optional, Sequence, Tuple, Type, TypeVar

import aiofiles
import aiofiles.os as aiofilesos
import fastapi
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from burr.tracking.common import models
from burr.tracking.common.models import ChildApplicationModel
from burr.tracking.common.partition_paths import (
    application_directory,
    join_path,
    log_has_end_entry,
    metadata_partition_key,
    partition_directories,
    partition_matches,
    partition_segment,
    read_metadata,
)
from burr.tracking.server import schema
from burr.tracking.server.schema import (
    AnnotationCreate,
    AnnotationOut,
    AnnotationUpdate,
    ApplicationLogs,
    ApplicationSummary,
    Step,
)

T = TypeVar("T")

logger = logging.getLogger(__name__)

# The following is a backend for the server.
# Note this is not a fixed API yet, and thus not documented (in Burr's documentation)
# Specifically, this does not have:
# - Streaming returns (just log tails)
# - Pagination
# - Authentication/Authorization


if sys.version_info <= (3, 11):
    Self = Any
else:
    from typing import Self


class BurrSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="burr_")


class IndexingBackendMixin(abc.ABC):
    """Base mixin for an indexing backend -- one that index from
    logs (E.G. s3)"""

    @abc.abstractmethod
    async def update(self):
        """Updates the index"""
        pass

    @abc.abstractmethod
    async def update_interval_milliseconds(self) -> Optional[int]:
        """Returns the update interval in milliseconds"""
        pass

    @abc.abstractmethod
    async def indexing_jobs(
        self, offset: int = 0, limit: int = 100, filter_empty: bool = True
    ) -> Sequence[schema.IndexingJob]:
        """Returns the indexing jobs"""
        pass


class AnnotationsBackendMixin(abc.ABC):
    @abc.abstractmethod
    async def create_annotation(
        self,
        annotation: AnnotationCreate,
        project_id: str,
        partition_key: Optional[str],
        app_id: str,
        step_sequence_id: int,
    ) -> AnnotationOut:
        """Createse an annotation -- annotation has annotation data, the other pointers are given in the parameters.

        :param annotation: Annotation object to create
        :param partition_key: Partition key to associate with
        :param project_id: Project ID to associate with
        :param app_id: App ID to associate with
        :param step_sequence_id: Step sequence ID to associate with
        :return:
        """

    @abc.abstractmethod
    async def update_annotation(
        self,
        annotation: AnnotationUpdate,
        project_id: str,
        annotation_id: int,
    ) -> AnnotationOut:
        """Updates an annotation -- annotation has annotation data, the other pointers are given in the parameters.

        :param annotation: Annotation object to update
        :param project_id: Project ID to associate with
        :param annotation_id: Annotation ID to update. We include this as we may have multiple...
        :return: Updated annotation
        """

    @abc.abstractmethod
    async def get_annotations(
        self,
        project_id: str,
        partition_key: Optional[str] = None,
        app_id: Optional[str] = None,
        step_sequence_id: Optional[int] = None,
    ) -> Sequence[AnnotationOut]:
        """Returns annotations for a given project, partition_key, app_id, and step sequence ID.
        If these are None it does not filter by them.

        :param project_id: Project ID to query for
        :param partition_key: Partition key to query for
        :param app_id: App ID to query for
        :param step_sequence_id: Step sequence ID to query for
        :return: Annotations
        """
        pass


class SnapshottingBackendMixin(abc.ABC):
    """Mixin for backend that conducts snapshotting -- e.g. saves
    the data to a file or database."""

    @abc.abstractmethod
    async def load_snapshot(self):
        """Loads the snapshot if it exists.

        :return:
        """
        pass

    @abc.abstractmethod
    async def snapshot(self):
        """Snapshots the data"""
        pass

    @abc.abstractmethod
    def snapshot_interval_milliseconds(self) -> Optional[int]:
        """Returns the snapshot interval in milliseconds"""
        pass


class EventDrivenBackendMixin(abc.ABC):
    """Mixin for backends that support event-driven updates.

    Enables backends to receive real-time notifications instead of polling
    for new files.
    """

    @abc.abstractmethod
    async def start_event_consumer(self):
        """Start the event consumer for event-driven tracking.

        This method should run indefinitely, processing event notifications
        from the configured message queue.
        """
        pass

    @abc.abstractmethod
    def is_event_driven(self) -> bool:
        """Check if this backend is configured for event-driven updates.

        :return: True if event-driven mode is enabled and configured, False otherwise
        """
        pass


class BackendBase(abc.ABC):
    async def lifespan(self, app: FastAPI):
        """Quick tool to allow plugin to the app's lifecycle.
        This is fine given that it's an internal API, but if we open it up more
        we should make this less flexible. For now this allows us to do clever
        initializations in the right order."""
        yield

    @abc.abstractmethod
    async def list_projects(self, request: fastapi.Request) -> Sequence[schema.Project]:
        """Lists out all projects -- this relies on the paginate function to work properly.

        :param request: The request object, used for authentication/authorization if needed
        :return: the next page
        """
        pass

    @abc.abstractmethod
    async def list_apps(
        self,
        request: fastapi.Request,
        project_id: str,
        partition_key: Optional[str],
        limit: int,
        offset: int,
    ) -> Tuple[Sequence[schema.ApplicationSummary], int]:
        """Lists out all apps (continual state machine runs with shared state) for a given project.

        :param request: The request object, used for authentication/authorization if needed
        :param project_id: filter by project id
        :param partition_key: filter by partition key
        :return: A list of apps and the total number of apps (given that we paginate)
        """
        pass

    @abc.abstractmethod
    async def get_application_logs(
        self, request: fastapi.Request, project_id: str, app_id: str, partition_key: Optional[str]
    ) -> ApplicationLogs:
        """Lists out all steps for a given app.

        :param request: The request object, used for authentication/authorization if needed
        :param app_id:
        :return:
        """
        pass

    @classmethod
    @abc.abstractmethod
    def settings_model(cls) -> Type[BaseSettings]:
        """Gives a settings model that tells us how to configure the backend.
        This is a class of pydantic BaseSettings type

        :return:  the settings model
        """
        pass

    @classmethod
    def from_settings(cls, settings_model: BaseSettings) -> Self:
        """Creates a backend from settings, of the type of settings_model above
        This defaults to assuming the constructor takes in settings parameters

        :param settings_model:
        :return:
        """
        return cls(**settings_model.dict())

    @classmethod
    def create_from_env(cls, dotenv_path: Optional[str] = None) -> Self:
        cls_path = os.environ.get("BURR_BACKEND_IMPL", "burr.tracking.server.backend.LocalBackend")
        mod_path = ".".join(cls_path.split(".")[:-1])
        mod = importlib.import_module(mod_path)
        cls_name = cls_path.split(".")[-1]
        if not hasattr(mod, cls_name):
            raise ValueError(f"Could not find {cls_name} in {mod_path}")
        cls = getattr(mod, cls_name)
        return cls.from_settings(
            cls.settings_model()(_env_file=dotenv_path, _env_file_encoding="utf-8")
        )

    def supports_demos(self) -> bool:
        """Whether this supports demos. Really we should abstract this out into a new mixin
        but for now this is OK.
        """
        return False


def safe_json_load(line: bytes):
    # Every once in a while we'll hit a non-utf-8 character
    # In this case we replace it and hope for the best
    return json.loads(line.decode("utf-8", errors="replace"))


def get_uri(project_id: str) -> str:
    project_id_map = {
        "demo_counter": "https://github.com/apache/burr/tree/main/examples/hello-world-counter",
        "demo_tracing": "https://github.com/apache/burr/tree/main/examples/tracing-and-spans/application.py",
        "demo_chatbot": "https://github.com/apache/burr/tree/main/examples/multi-modal-chatbot",
        "demo_conversational-rag": "https://github.com/apache/burr/tree/main/examples/conversational-rag",
    }
    return project_id_map.get(project_id, "")


DEFAULT_PATH = os.path.expanduser("~/.burr")


def _metadata_at(app_dir: str) -> Optional[dict]:
    return read_metadata(join_path(app_dir, "metadata.json"))


def _resolve_app_directory(
    storage_path: str, project_id: str, app_id: str, partition_key: Optional[str]
) -> str:
    """Locate the tracking directory for one (project, app_id, partition_key) triple.

    Only metadata that confirms the requested partition may authorize a legacy read.

    Status policy: 404 means no data exists for the requested identifiers; 400 means data
    exists but cannot be attributed to them (mismatched/missing partition metadata,
    ambiguity, or an invalid path).
    """
    app_root = join_path(storage_path, project_id, app_id)
    context = f"{project_id}/{app_id}"
    legacy_log = join_path(app_root, "log.jsonl")
    if partition_key is not None:
        nested = application_directory(app_root, partition_key)
        nested_log = join_path(nested, "log.jsonl")
        if log_has_end_entry(nested_log):
            if not partition_matches(_metadata_at(nested), partition_key):
                raise fastapi.HTTPException(
                    status_code=400,
                    detail=f"Partition directory metadata for {context} does not confirm {partition_key!r}.",
                )
            return nested
        if os.path.exists(legacy_log):
            metadata = _metadata_at(app_root)
            if partition_matches(metadata, partition_key):
                return app_root
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    f"Legacy data for {context} belongs to partition "
                    f"{metadata_partition_key(metadata)!r}, not {partition_key!r}."
                ),
            )
        if os.path.exists(nested_log):
            if not partition_matches(_metadata_at(nested), partition_key):
                raise fastapi.HTTPException(
                    status_code=400,
                    detail=f"Partition directory metadata for {context} does not confirm {partition_key!r}.",
                )
            return nested
        raise fastapi.HTTPException(status_code=404, detail=f"App: {context} not found")

    if os.path.exists(legacy_log):
        metadata = _metadata_at(app_root)
        if partition_matches(metadata, None):
            return app_root
        raise fastapi.HTTPException(
            status_code=400,
            detail=f"Data for {context} belongs to partition {metadata_partition_key(metadata)!r}; partition_key is required.",
        )
    nested_dirs = [
        directory
        for directory in partition_directories(app_root)
        if log_has_end_entry(join_path(directory, "log.jsonl"))
    ]
    if nested_dirs:
        raise fastapi.HTTPException(
            status_code=400, detail=f"Partition tracking data exists for {context}; select one."
        )
    raise fastapi.HTTPException(status_code=404, detail=f"App: {context} not found")


class LocalBackend(BackendBase, AnnotationsBackendMixin):
    """Quick implementation of a local backend for testing purposes. This is not a production backend.

    To override the path, set a `burr_path` environment variable to the path you want to use.
    """

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path

    def _get_annotation_path(self, project_id: str) -> str:
        return join_path(self.path, project_id, "annotations.jsonl")

    async def _load_project_annotations(self, project_id: str):
        annotations_path = self._get_annotation_path(project_id)
        annotations = []
        if os.path.exists(annotations_path):
            async with aiofiles.open(annotations_path, encoding="utf-8") as f:
                for line in await f.readlines():
                    annotations.append(AnnotationOut.parse_raw(line))
        return annotations

    async def create_annotation(
        self,
        annotation: AnnotationCreate,
        project_id: str,
        partition_key: Optional[str],
        app_id: str,
        step_sequence_id: int,
    ) -> AnnotationOut:
        """Creates an annotation by loading all annotations, finding the max ID, and then appending the new annotation.
        This is not efficient but it's OK -- this is the local version and the number of annotations will be unlikely to be
        huge.

        :param annotation: Annotation to create
        :param project_id: ID of the associated project
        :param partition_key: Partition key to associate with
        :param app_id: App ID to associate with
        :param step_sequence_id: Step sequence ID to associate with
        :return: The created annotation, complete with an ID + timestamps
        """
        all_annotations = await self._load_project_annotations(project_id)
        annotation_id = (
            max([a.id for a in all_annotations], default=-1) + 1
        )  # get the ID, increment
        annotation_out = AnnotationOut(
            id=annotation_id,
            project_id=project_id,
            app_id=app_id,
            partition_key=partition_key,
            step_sequence_id=step_sequence_id,
            created=datetime.now(),
            updated=datetime.now(),
            **annotation.dict(),
        )
        annotations_path = self._get_annotation_path(project_id)
        async with aiofiles.open(annotations_path, "a", encoding="utf-8") as f:
            await f.write(annotation_out.json() + "\n")
        return annotation_out

    async def update_annotation(
        self,
        annotation: AnnotationUpdate,
        project_id: str,
        annotation_id: int,
    ) -> AnnotationOut:
        """Updates an annotation by loading all annotations, finding the annotation, updating it, and then writing it back.
        Again, inefficient, but this is the local backend and we don't expect huge numbers of annotations.

        :param annotation: Annotation to update -- this is just the update fields to the full annotation
        :param project_id: ID of the associated project
        :param annotation_id: ID of the associated annotation, created by the backend
        :return: The updated annotation, complete with an ID + timestamps
        """
        all_annotations = await self._load_project_annotations(project_id)
        annotation_out = None
        for idx, a in enumerate(all_annotations):
            if a.id == annotation_id:
                annotation_out = a
                all_annotations[idx] = annotation_out.copy(
                    update={**annotation.dict(), "updated": datetime.now()}
                )
                break
        if annotation_out is None:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f"Annotation: {annotation_id} from project: {project_id} not found",
            )
        annotations_path = self._get_annotation_path(project_id)
        async with aiofiles.open(annotations_path, "w", encoding="utf-8") as f:
            for a in all_annotations:
                await f.write(a.json() + "\n")
        return annotation_out

    async def get_annotations(
        self,
        project_id: str,
        partition_key: Optional[str] = None,
        app_id: Optional[str] = None,
        step_sequence_id: Optional[int] = None,
    ) -> Sequence[AnnotationOut]:
        """Gets the annotation by loading all annotations and filtering by the parameters. Will return all annotations
        that match. Only project is required.


        :param project_id:
        :param partition_key:
        :param app_id:
        :param step_sequence_id:
        :return:
        """
        annotation_path = self._get_annotation_path(project_id)
        if not os.path.exists(annotation_path):
            return []
        annotations = []
        async with aiofiles.open(annotation_path, encoding="utf-8") as f:
            for line in await f.readlines():
                parsed = AnnotationOut.parse_raw(line)
                if (
                    (partition_key is None or parsed.partition_key == partition_key)
                    and (app_id is None or parsed.app_id == app_id)
                    and (step_sequence_id is None or parsed.step_sequence_id == step_sequence_id)
                ):
                    annotations.append(parsed)
        return annotations

    async def list_projects(self, request: fastapi.Request) -> Sequence[schema.Project]:
        out = []
        if not os.path.exists(self.path):
            return out
        for entry in await aiofilesos.listdir(self.path):
            full_path = join_path(self.path, entry)
            if os.path.isdir(full_path):
                out.append(
                    schema.Project(
                        name=entry,
                        id=entry,
                        uri=get_uri(entry),
                        last_written=await aiofilesos.path.getmtime(full_path),
                        created=await aiofilesos.path.getctime(full_path),
                        num_apps=len(await aiofilesos.listdir(full_path)),
                    )
                )
        return out

    async def get_number_of_steps(self, file_path: str) -> int:
        """Quick tool to get the latest sequence ID from a log file.
        This is not efficient and should be replaced."""
        async with aiofiles.open(file_path, "rb") as f:
            for line in reversed(await f.readlines()):
                line_data = safe_json_load(line)
                if "sequence_id" in line_data:
                    # Just return the latest we can determine for now
                    # We add one as it is the count, not the index
                    return line_data["sequence_id"] + 1
        return 0

    async def _load_metadata(self, metadata_path: str) -> models.ApplicationMetadataModel:
        if os.path.exists(metadata_path):
            async with aiofiles.open(metadata_path, "rb") as f:
                raw = await f.read()
                return models.ApplicationMetadataModel.parse_obj(safe_json_load(raw))
        return models.ApplicationMetadataModel()

    async def list_apps(
        self,
        request: fastapi.Request,
        project_id: str,
        partition_key: Optional[str],
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[Sequence[ApplicationSummary], int]:
        project_filepath = join_path(self.path, project_id)
        if not os.path.exists(project_filepath):
            return [], 0
        out = []
        for entry in await aiofilesos.listdir(project_filepath):
            if entry.startswith("."):
                # skip hidden files/directories
                continue
            app_root = join_path(project_filepath, entry)
            if not os.path.isdir(app_root):
                continue

            # A run is either the legacy root files or one partition subdirectory.
            runs = []
            legacy_log = join_path(app_root, "log.jsonl")
            if os.path.exists(legacy_log):
                legacy_metadata = _metadata_at(app_root)
                runs.append(
                    (
                        app_root,
                        metadata_partition_key(legacy_metadata),
                        entry,
                        log_has_end_entry(legacy_log),
                    )
                )
            for partition_dir in partition_directories(app_root):
                log_path = join_path(partition_dir, "log.jsonl")
                if not os.path.exists(log_path):
                    continue
                metadata = _metadata_at(partition_dir)
                run_partition = metadata_partition_key(metadata)
                if run_partition is None or partition_segment(run_partition) != os.path.basename(
                    partition_dir
                ):
                    logger.warning(
                        "Skipping %s: partition metadata does not match its directory",
                        partition_dir,
                    )
                    continue
                has_data = log_has_end_entry(log_path)
                if not has_data and any(run[1] == run_partition and run[3] for run in runs):
                    # An empty partitioned log must not hide completed legacy data during resume.
                    continue
                if has_data:
                    runs = [run for run in runs if run[1] != run_partition]
                runs.append((partition_dir, run_partition, entry, has_data))

            for run_dir, app_partition_key, app_id, _ in runs:
                if partition_key is not None and partition_key != app_partition_key:
                    continue
                metadata = await self._load_metadata(join_path(run_dir, "metadata.json"))
                out.append(
                    schema.ApplicationSummary(
                        app_id=app_id,
                        partition_key=app_partition_key,
                        first_written=await aiofilesos.path.getctime(run_dir),
                        last_written=await aiofilesos.path.getmtime(run_dir),
                        num_steps=await self.get_number_of_steps(join_path(run_dir, "log.jsonl")),
                        tags={},
                        parent_pointer=metadata.parent_pointer,
                        spawning_parent_pointer=metadata.spawning_parent_pointer,
                    )
                )
        out = sorted(out, key=lambda x: x.last_written, reverse=True)
        # TODO -- actually only get the most recent ones rather than reading everything, this is inefficient
        return out[offset : offset + limit], len(out)

    async def get_application_logs(
        self, request: fastapi.Request, project_id: str, app_id: str, partition_key: Optional[str]
    ) -> ApplicationLogs:
        app_filepath = _resolve_app_directory(self.path, project_id, app_id, partition_key)
        log_file = join_path(app_filepath, "log.jsonl")
        graph_file = join_path(app_filepath, "graph.json")
        metadata_file = join_path(app_filepath, "metadata.json")
        children_file = join_path(app_filepath, "children.jsonl")
        metadata = await self._load_metadata(metadata_file)
        if not os.path.exists(graph_file):
            raise fastapi.HTTPException(
                status_code=404,
                detail=f"Graph file for app: {app_id} from project: {project_id} not found",
            )
        async with aiofiles.open(graph_file, encoding="utf-8") as f:
            str_graph = await f.read()
        collections.defaultdict(list)
        steps = []
        if os.path.exists(log_file):
            async with aiofiles.open(log_file, "rb") as f:
                lines = await f.readlines()
                steps = Step.from_logs(lines)
        children = []
        if os.path.exists(children_file):
            async with aiofiles.open(children_file, encoding="utf-8") as f:
                str_children = await f.readlines()
                children = [
                    ChildApplicationModel.parse_obj(json.loads(item)) for item in str_children
                ]

        return ApplicationLogs(
            application=schema.ApplicationModel.parse_raw(str_graph),
            steps=steps,
            parent_pointer=metadata.parent_pointer,
            spawning_parent_pointer=metadata.spawning_parent_pointer,
            children=children,
        )

    def supports_demos(self) -> bool:
        return True

    class BackendSettings(BurrSettings):
        path: str = DEFAULT_PATH

    @classmethod
    def settings_model(cls) -> Type[BurrSettings]:
        return cls.BackendSettings

    @classmethod
    def from_settings(cls, settings_model: BurrSettings) -> Self:
        return cls(**settings_model.dict())
