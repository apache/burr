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

import functools
import importlib

import pydantic
from fastapi import APIRouter

from burr.core import Application, ApplicationBuilder, Result, default, expr
from burr.tracking import LocalTrackingClient

"""This file represents a simple counter API backed with Burr.
We manage an application, write to it with post endpoints, and read with
get/ endpoints.

This demonstrates how you can build interactive web applications with Burr!
"""

counter_application = importlib.import_module(
    "burr.examples.hello-world-counter.application"
)  # noqa: F401

router = APIRouter()

COUNTER_LIMIT = 1000


class CounterState(pydantic.BaseModel):
    """Pydantic model for the counter state."""

    counter: int
    app_id: str


@functools.lru_cache(maxsize=128)
def _get_application(project_id: str, app_id: str) -> Application:
    """Quick tool to get the application -- caches it"""
    tracker = LocalTrackingClient(project=project_id, storage_dir="~/.burr")
    return (
        ApplicationBuilder()
        .with_actions(
            counter=counter_application.counter,
            result=Result("counter"),
        )
        .with_transitions(
            ("counter", "counter", expr(f"counter < {COUNTER_LIMIT}")),
            ("counter", "result", default),
        )
        .initialize_from(
            tracker,
            resume_at_next_action=True,
            default_state={"counter": 0},
            default_entrypoint="counter",
        )
        .with_tracker(tracker)
        .with_identifiers(app_id=app_id)
        .build()
    )


@router.post("/count/{project_id}/{app_id}", response_model=CounterState)
def count(project_id: str, app_id: str) -> CounterState:
    """Increment the counter by one step and return the new state.

    :param project_id: Project ID to run
    :param app_id: Application ID to run
    :return: The current counter state
    """
    burr_app = _get_application(project_id, app_id)
    burr_app.step()
    return CounterState(
        counter=burr_app.state["counter"],
        app_id=app_id,
    )


@router.get("/state/{project_id}/{app_id}", response_model=CounterState)
def get_counter_state(project_id: str, app_id: str) -> CounterState:
    """Get the current counter state without incrementing.

    :param project_id: Project ID
    :param app_id: App ID
    :return: The current counter state
    """
    burr_app = _get_application(project_id, app_id)
    return CounterState(
        counter=burr_app.state["counter"],
        app_id=app_id,
    )


@router.post("/create/{project_id}/{app_id}", response_model=str)
async def create_new_application(project_id: str, app_id: str) -> str:
    """Endpoint to create a new application -- used by the FE when
    the user types in a new App ID

    :param project_id: Project ID
    :param app_id: App ID
    :return: The app ID
    """
    _get_application(app_id=app_id, project_id=project_id)
    return app_id
