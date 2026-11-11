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

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# The module-level app serves the built UI, which a source checkout does not have
os.environ.setdefault("BURR_SERVE_STATIC", "false")

from burr.tracking.server import run  # noqa: E402


def test_mount_burr_ui_runs_ui_lifespan(monkeypatch):
    monkeypatch.setattr(run, "initialized", False)
    parent = FastAPI()
    run.mount_burr_ui(parent, path="/burr", serve_static=False)
    with TestClient(parent) as client:
        response = client.get("/burr/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True}


def test_mount_burr_ui_keeps_parent_lifespan(monkeypatch):
    monkeypatch.setattr(run, "initialized", False)
    events = []

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        events.append("startup")
        yield {"parent_value": 1}
        events.append("shutdown")

    parent = FastAPI(lifespan=lifespan)

    @parent.get("/parent_value")
    def parent_value(request: Request):
        return request.state.parent_value

    run.mount_burr_ui(parent, path="/burr", serve_static=False)
    with TestClient(parent) as client:
        assert client.get("/parent_value").json() == 1
        assert client.get("/burr/ready").status_code == 200
    assert events == ["startup", "shutdown"]
