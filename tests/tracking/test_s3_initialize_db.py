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

import asyncio
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("tortoise")
from burr.tracking.server.s3 import initialize_db, settings


def test_connect_uses_configured_database_path(tmp_path, monkeypatch):
    db_path = tmp_path / "nested" / "custom.sqlite3"
    tortoise_config = {"connections": {"default": f"sqlite:///{db_path}"}, "apps": {}}
    tortoise_init = AsyncMock()
    monkeypatch.setattr(settings, "DB_PATH", str(db_path))
    monkeypatch.setattr(settings, "TORTOISE_ORM", tortoise_config)
    monkeypatch.setattr(initialize_db.Tortoise, "init", tortoise_init)

    asyncio.run(initialize_db.connect())

    assert db_path.parent.is_dir()
    tortoise_init.assert_awaited_once_with(config=tortoise_config)
