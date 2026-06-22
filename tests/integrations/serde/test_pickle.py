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

import pickle as _pickle
import warnings

import pytest

from burr.core import serde, state
from burr.integrations.serde import pickle
from burr.integrations.serde.pickle import (
    SecurityWarning,
    _is_allowed,
    set_pickle_serde_allowlist,
)


class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email


class Address:
    def __init__(self, city):
        self.city = city


class _ReduceCanary:
    """When unpickled, would call ``int("1")`` instead of doing the normal
    object reconstruction. We use this to exercise the ``find_class`` hook of
    the restricted unpickler without invoking anything actually dangerous.
    """

    def __reduce__(self):
        return (int, ("1",))


def test_serde_of_pickle_object():
    pickle.register_type_to_pickle(User)
    user = User(name="John Doe", email="john.doe@example.com")
    og = state.State({"user": user, "test": "test"})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SecurityWarning)
        serialized = og.serialize()
        ng = state.State.deserialize(serialized)
    assert serialized["user"][serde.KEY] == "pickle"
    assert isinstance(ng["user"], User)
    assert ng["user"].name == "John Doe"
    assert ng["user"].email == "john.doe@example.com"


def test_is_allowed_logic():
    assert _is_allowed("m", "C", [("m", "C")]) is True
    assert _is_allowed("m", "C", [("m", "*")]) is True
    assert _is_allowed("m", "C", [("other", "*")]) is False
    assert _is_allowed("m", "C", [("m", "D")]) is False
    assert _is_allowed("m", "C", []) is False


def test_malicious_reduce_payload_blocked_with_allowlist():
    """A pickle payload referencing a class outside the allowlist must be
    refused at find_class() time, before any object is reconstructed."""
    pickle.register_type_to_pickle(User, allowlist=[(__name__, "User")])

    malicious_bytes = _pickle.dumps(_ReduceCanary())
    tampered = {
        "user": {
            serde.KEY: "pickle",
            "value": malicious_bytes,
        }
    }
    with pytest.raises(ValueError, match="not in the pickle serde allowlist"):
        state.State.deserialize(tampered)


def test_legitimate_object_roundtrips_when_module_on_allowlist():
    pickle.register_type_to_pickle(User, allowlist=[(__name__, "User")])
    user = User(name="Alice", email="a@example.com")
    og = state.State({"user": user})
    serialized = og.serialize()
    ng = state.State.deserialize(serialized)
    assert isinstance(ng["user"], User)
    assert ng["user"].name == "Alice"


def test_module_level_allowlist_applies_to_fresh_registration():
    """A class registered after set_pickle_serde_allowlist() should pick up the
    process-wide default."""
    set_pickle_serde_allowlist([(__name__, "*")])
    try:
        pickle.register_type_to_pickle(Address)
        addr = Address(city="Berlin")
        og = state.State({"addr": addr})
        serialized = og.serialize()
        ng = state.State.deserialize(serialized)
        assert isinstance(ng["addr"], Address)
        assert ng["addr"].city == "Berlin"

        # And a tampered payload referencing a class outside the module is
        # still refused under the global allowlist.
        tampered = {
            "addr": {
                serde.KEY: "pickle",
                "value": _pickle.dumps(_ReduceCanary()),
            }
        }
        with pytest.raises(ValueError, match="not in the pickle serde allowlist"):
            state.State.deserialize(tampered)
    finally:
        set_pickle_serde_allowlist(None)


def test_instance_allowlist_overrides_module_default():
    """A per-call allowlist passed to register_type_to_pickle() should take
    precedence over the process-wide default."""
    # Global default permits everything in this module.
    set_pickle_serde_allowlist([(__name__, "*")])
    try:
        # But the per-registration allowlist only permits User. So a payload
        # referencing _ReduceCanary (also in this module) should be blocked.
        pickle.register_type_to_pickle(User, allowlist=[(__name__, "User")])

        tampered = {
            "user": {
                serde.KEY: "pickle",
                "value": _pickle.dumps(_ReduceCanary()),
            }
        }
        with pytest.raises(ValueError, match="not in the pickle serde allowlist"):
            state.State.deserialize(tampered)

        # And legitimate User payloads still work under the stricter local
        # allowlist.
        u = User(name="Bob", email="b@example.com")
        og = state.State({"user": u})
        ng = state.State.deserialize(og.serialize())
        assert isinstance(ng["user"], User)
    finally:
        set_pickle_serde_allowlist(None)


def test_per_call_allowlist_overrides_registration_and_global():
    """The allowlist kwarg passed at deserialize time should take precedence
    over both the registration-time allowlist and the global default."""
    set_pickle_serde_allowlist([(__name__, "User")])
    try:
        pickle.register_type_to_pickle(User, allowlist=[(__name__, "User")])
        # Legitimate User payload
        u = User(name="Carol", email="c@example.com")
        serialized = state.State({"user": u}).serialize()

        # Pass an allowlist that does NOT include User; deserialization should
        # fail even though both the registration and global allowlists permit
        # it.
        with pytest.raises(ValueError, match="not in the pickle serde allowlist"):
            state.State.deserialize(serialized, allowlist=[("nothing", "Nothing")])

        # And allowlist that includes User succeeds.
        ng = state.State.deserialize(serialized, allowlist=[(__name__, "User")])
        assert isinstance(ng["user"], User)
    finally:
        set_pickle_serde_allowlist(None)


def test_legacy_path_emits_security_warning_once_per_site():
    """When no allowlist is configured anywhere, deserialization should still
    work (backward compatibility) but emit a SecurityWarning. The warning
    should fire at most once per registration site."""
    # Reset the dedup set so the warning will fire for this test, then put it
    # back so we don't disturb other tests.
    from burr.integrations.serde.pickle import _warned_call_sites

    saved = set(_warned_call_sites)
    _warned_call_sites.clear()
    try:
        set_pickle_serde_allowlist(None)
        pickle.register_type_to_pickle(User)
        u = User(name="Dana", email="d@example.com")
        serialized = state.State({"user": u}).serialize()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ng1 = state.State.deserialize(serialized)
            ng2 = state.State.deserialize(serialized)
        sec_warnings = [w for w in caught if issubclass(w.category, SecurityWarning)]
        # Exactly one SecurityWarning across the two deserialize calls.
        assert len(sec_warnings) == 1, (
            f"expected 1 SecurityWarning, got {len(sec_warnings)}: "
            f"{[str(w.message) for w in sec_warnings]}"
        )
        assert isinstance(ng1["user"], User)
        assert isinstance(ng2["user"], User)
    finally:
        _warned_call_sites.clear()
        _warned_call_sites.update(saved)
