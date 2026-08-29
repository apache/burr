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

import collections
import datetime
from typing import Any, Dict, List, Literal, Optional, Union

import pydantic
from pydantic import fields

from burr.tracking.common.models import (
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
from burr.tracking.utils import safe_json_load


class Project(pydantic.BaseModel):
    name: str
    id: str  # defaults to name for local, not for remote
    last_written: datetime.datetime
    created: datetime.datetime
    num_apps: int
    uri: str


class ApplicationSummary(pydantic.BaseModel):
    app_id: str
    partition_key: Optional[str]
    first_written: datetime.datetime
    last_written: datetime.datetime
    num_steps: int
    tags: Dict[str, str]
    parent_pointer: Optional[PointerModel] = None
    spawning_parent_pointer: Optional[PointerModel] = None


class ApplicationPage(pydantic.BaseModel):
    applications: List[ApplicationSummary]
    total: int
    has_another_page: bool


class ApplicationModelWithChildren(pydantic.BaseModel):
    application: ApplicationModel
    children: List[PointerModel]
    type: str = "application_with_children"


class PartialSpan(pydantic.BaseModel):
    begin_entry: Optional[BeginSpanModel] = fields.Field(default_factory=lambda: None)
    end_entry: Optional[EndSpanModel] = fields.Field(default_factory=lambda: None)


class Span(pydantic.BaseModel):
    """Represents a span. These have action sequence IDs associated with
    them to put them in order."""

    begin_entry: BeginSpanModel
    end_entry: Optional[EndSpanModel]


class PartialStep(pydantic.BaseModel):
    step_start_log: Optional[BeginEntryModel] = fields.Field(default_factory=lambda: None)
    step_end_log: Optional[EndEntryModel] = fields.Field(default_factory=lambda: None)
    spans: List[Span] = fields.Field(default_factory=list)
    streaming_events: List[Union[InitializeStreamModel, FirstItemStreamModel, EndStreamModel]] = (
        fields.Field(default_factory=list)
    )


class Step(pydantic.BaseModel):
    """Log of  astep -- has a start and an end."""

    step_start_log: BeginEntryModel
    step_end_log: Optional[EndEntryModel]
    spans: List[Span]
    attributes: List[AttributeModel]
    streaming_events: List[Union[InitializeStreamModel, FirstItemStreamModel, EndStreamModel]]

    @staticmethod
    def from_logs(log_lines: List[bytes]) -> List["Step"]:
        steps_by_sequence_id = collections.defaultdict(PartialStep)
        spans_by_id = collections.defaultdict(PartialSpan)
        attributes_by_step: dict[int, List[AttributeModel]] = collections.defaultdict(list)
        for line in log_lines:
            json_line = safe_json_load(line)
            # TODO -- make these into constants
            if json_line["type"] == "begin_entry":
                begin_step = BeginEntryModel.model_validate(json_line)
                steps_by_sequence_id[begin_step.sequence_id].step_start_log = begin_step
            elif json_line["type"] == "end_entry":
                step_end_log = EndEntryModel.model_validate(json_line)
                steps_by_sequence_id[step_end_log.sequence_id].step_end_log = step_end_log
            elif json_line["type"] == "begin_span":
                span = BeginSpanModel.model_validate(json_line)
                spans_by_id[span.span_id] = PartialSpan(
                    begin_entry=span,
                    end_entry=None,
                )
            elif json_line["type"] == "end_span":
                end_span = EndSpanModel.model_validate(json_line)
                span = spans_by_id[end_span.span_id]
                span.end_entry = end_span
            elif json_line["type"] == "attribute":
                attribute = AttributeModel.model_validate(json_line)
                attributes_by_step[attribute.action_sequence_id].append(attribute)
            elif json_line["type"] in ["begin_stream", "first_item_stream", "end_stream"]:
                streaming_event = {
                    "begin_stream": InitializeStreamModel,
                    "first_item_stream": FirstItemStreamModel,
                    "end_stream": EndStreamModel,
                }[json_line["type"]].model_validate(json_line)
                steps_by_sequence_id[streaming_event.sequence_id].streaming_events.append(
                    streaming_event
                )
        for span in spans_by_id.values():
            sequence_id = (
                span.begin_entry.action_sequence_id
                if span.begin_entry
                else span.end_entry.action_sequence_id
            )
            step = (
                steps_by_sequence_id[sequence_id] if sequence_id in steps_by_sequence_id else None
            )
            if step is not None:
                if span.begin_entry is not None:
                    full_span = Span(
                        begin_entry=span.begin_entry,
                        end_entry=span.end_entry,
                    )
                    step.spans.append(full_span)
        # filter out all the non-null start steps
        return [
            Step(
                step_start_log=value.step_start_log,
                step_end_log=value.step_end_log,
                spans=[Span(**span.dict()) for span in value.spans if span.begin_entry is not None],
                attributes=attributes_by_step[key],
                streaming_events=value.streaming_events,
            )
            for key, value in sorted(steps_by_sequence_id.items())
            if value.step_start_log is not None
        ]


class StepWithMinimalData(Step):
    step_start_log: Optional[BeginEntryModel]


class ApplicationLogs(pydantic.BaseModel):
    """Application logs are purely flat --
    we will likely be rethinking this but for now this provides for easy parsing."""

    application: ApplicationModel
    children: List[ChildApplicationModel]
    steps: List[Step]
    parent_pointer: Optional[PointerModel] = None
    spawning_parent_pointer: Optional[PointerModel] = None


class IndexingJob(pydantic.BaseModel):
    """Generic link for indexing job -- can be exposed in 'admin mode' in the UI"""

    id: int
    start_time: datetime.datetime
    end_time: Optional[datetime.datetime]
    status: str
    records_processed: int
    metadata: Dict[str, Any]


class BackendSpec(pydantic.BaseModel):
    """Generic link for indexing job -- can be exposed in 'admin mode' in the UI"""

    indexing: bool
    snapshotting: bool
    supports_demos: bool
    supports_annotations: bool


class AnnotationDataPointer(pydantic.BaseModel):
    type: Literal["state_field", "attribute"]
    field_name: str  # key of attribute/state field
    span_id: Optional[
        str
    ]  # span_id if it's associated with a span, otherwise it's associated with an action


AllowedDataField = Literal["note", "ground_truth"]


class AnnotationObservation(pydantic.BaseModel):
    data_fields: dict[str, Any]
    thumbs_up_thumbs_down: Optional[bool]
    data_pointers: List[AnnotationDataPointer]


class AnnotationCreate(pydantic.BaseModel):
    """Generic link for indexing job -- can be exposed in 'admin mode' in the UI"""

    span_id: Optional[str]
    step_name: str  # Should be able to look it up but including for now
    tags: List[str]
    observations: List[AnnotationObservation]


class AnnotationUpdate(AnnotationCreate):
    """Generic link for indexing job -- can be exposed in 'admin mode' in the UI"""

    # Identification for association
    span_id: Optional[str] = None
    tags: Optional[List[str]] = []
    observations: List[AnnotationObservation]


class AnnotationOut(AnnotationCreate):
    """Generic link for indexing job -- can be exposed in 'admin mode' in the UI"""

    id: int
    # Identification for association
    project_id: str  # associated project ID
    app_id: str
    partition_key: Optional[str]
    step_sequence_id: int
    created: datetime.datetime
    updated: datetime.datetime
