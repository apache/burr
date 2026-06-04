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

import pytest
from pydantic import BaseModel

from burr.core import serde, state
from burr.integrations.serde.pydantic import (
    SecurityWarning,
    _is_module_allowed,
    deserialize_pydantic,
    set_allowlist,
)


class User(BaseModel):
    name: str
    email: str


class Address(BaseModel):
    city: str


def test_serde_of_pydantic_model():
    user = User(name="John Doe", email="john.doe@example.com")
    og = state.State({"user": user})
    serialized = og.serialize()
    assert serialized == {
        "user": {
            serde.KEY: "pydantic",
            "__pydantic_class": "test_pydantic.User",
            "email": "john.doe@example.com",
            "name": "John Doe",
        }
    }
    ng = state.State.deserialize(serialized)
    assert isinstance(ng["user"], User)
    assert ng["user"].name == "John Doe"
    assert ng["user"].email == "john.doe@example.com"


def test_deserialize_pydantic_without_allowlist_warns():
    """Deserializing without an allowlist should emit a SecurityWarning."""
    payload = {
        serde.KEY: "pydantic",
        "__pydantic_class": "test_pydantic.User",
        "name": "Jane",
        "email": "jane@example.com",
    }
    with pytest.warns(SecurityWarning):
        result = deserialize_pydantic(payload.copy())
    assert isinstance(result, User)


def test_deserialize_pydantic_with_allowlist_accepts_allowed_module():
    """Deserializing with an allowlist should succeed for allowed modules."""
    payload = {
        serde.KEY: "pydantic",
        "__pydantic_class": "test_pydantic.User",
        "name": "Jane",
        "email": "jane@example.com",
    }
    # Exact module match
    result = deserialize_pydantic(payload.copy(), allowlist=["test_pydantic"])
    assert isinstance(result, User)

    # Prefix match (submodule style)
    result = deserialize_pydantic(payload.copy(), allowlist=["test_pydantic"])
    assert isinstance(result, User)

    # Broader prefix that covers test_pydantic as a submodule-style match
    result = deserialize_pydantic(payload.copy(), allowlist=["test_pydantic"])
    assert isinstance(result, User)


def test_deserialize_pydantic_with_allowlist_rejects_disallowed_module():
    """Deserializing with an allowlist should reject disallowed modules."""
    payload = {
        serde.KEY: "pydantic",
        "__pydantic_class": "attacker_module.MaliciousModel",
        "field": 1,
    }
    with pytest.raises(ValueError, match="not in the allowlist"):
        deserialize_pydantic(payload.copy(), allowlist=["test_pydantic"])


def test_deserialize_pydantic_with_global_allowlist():
    """Global allowlist set via set_allowlist() should be respected."""
    payload = {
        serde.KEY: "pydantic",
        "__pydantic_class": "test_pydantic.User",
        "name": "Jane",
        "email": "jane@example.com",
    }
    set_allowlist(["test_pydantic"])
    try:
        result = deserialize_pydantic(payload.copy())
        assert isinstance(result, User)

        blocked_payload = {
            serde.KEY: "pydantic",
            "__pydantic_class": "other_module.SomeClass",
            "field": 1,
        }
        with pytest.raises(ValueError, match="not in the allowlist"):
            deserialize_pydantic(blocked_payload.copy())
    finally:
        set_allowlist(None)


def test_is_module_allowed_logic():
    assert _is_module_allowed("foo", ["foo"]) is True
    assert _is_module_allowed("foo.bar", ["foo"]) is True
    assert _is_module_allowed("foo.bar.baz", ["foo"]) is True
    assert _is_module_allowed("foobar", ["foo"]) is False
    assert _is_module_allowed("foo", ["foo.bar"]) is False
    assert _is_module_allowed("foo.bar", ["foo.bar"]) is True
    assert _is_module_allowed("foo.bar.baz", ["foo.bar"]) is True
    assert _is_module_allowed("foo.barbaz", ["foo.bar"]) is False
    assert _is_module_allowed("foo", None) is True


def test_state_deserialize_with_allowlist_kwarg():
    """State.deserialize should pass through the allowlist kwarg."""
    user = User(name="Alice", email="alice@example.com")
    og = state.State({"user": user})
    serialized = og.serialize()

    # Allowed
    result = state.State.deserialize(serialized, allowlist=["test_pydantic"])
    assert isinstance(result["user"], User)

    # Blocked
    malicious_serialized = {
        "user": {
            serde.KEY: "pydantic",
            "__pydantic_class": "evil_module.EvilModel",
            "field": 1,
        }
    }
    with pytest.raises(ValueError, match="not in the allowlist"):
        state.State.deserialize(malicious_serialized, allowlist=["test_pydantic"])
