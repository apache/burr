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

"""Unit tests for MongoDB driver handshake metadata (no live DB required)."""

from unittest.mock import MagicMock, patch

from pymongo.driver_info import DriverInfo

from burr.integrations.persisters.b_pymongo import (
    _DRIVER_INFO,
    _VERSION,
    MongoDBBasePersister,
)


def test_driver_info_name():
    assert isinstance(_DRIVER_INFO, DriverInfo)
    assert _DRIVER_INFO.name == "Burr"


def test_driver_info_version_matches_package():
    assert _DRIVER_INFO.version == _VERSION


def test_from_values_passes_driver_info():
    """from_values() injects driver=_DRIVER_INFO into MongoClient."""
    with patch("burr.integrations.persisters.b_pymongo.MongoClient") as mock_ctor:
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=MagicMock())
        mock_ctor.return_value = mock_client
        MongoDBBasePersister.from_values(uri="mongodb://localhost:27017")
    _, kwargs = mock_ctor.call_args
    assert "driver" in kwargs
    assert isinstance(kwargs["driver"], DriverInfo)
    assert kwargs["driver"].name == "Burr"


def test_from_values_does_not_override_caller_driver():
    """from_values() preserves a driver value supplied via mongo_client_kwargs."""
    custom = DriverInfo(name="MyApp", version="9.9")
    with patch("burr.integrations.persisters.b_pymongo.MongoClient") as mock_ctor:
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=MagicMock())
        mock_ctor.return_value = mock_client
        MongoDBBasePersister.from_values(
            uri="mongodb://localhost:27017",
            mongo_client_kwargs={"driver": custom},
        )
    _, kwargs = mock_ctor.call_args
    assert kwargs["driver"] is custom


def test_init_calls_append_metadata_when_available():
    """__init__() calls append_metadata on a client that supports it."""
    mock_client = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=MagicMock())
    MongoDBBasePersister(client=mock_client)
    mock_client.append_metadata.assert_called_once_with(_DRIVER_INFO)


def test_init_skips_append_metadata_when_absent():
    """__init__() does not raise when client lacks append_metadata (older driver)."""
    mock_client = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=MagicMock())
    # Simulate a client without append_metadata by deleting the attribute
    del mock_client.append_metadata
    # Should not raise
    MongoDBBasePersister(client=mock_client)
