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

# Pickle serde registration
# This is not automatically registered because we want to register
# it based on class type.
import io
import pickle
import warnings
from typing import Iterable, List, Optional, Tuple

from burr.core import serde

# Type alias: an allowlist entry is ``(module, qualname)``.
# ``qualname`` may be ``"*"`` to permit any class in the given module.
AllowlistEntry = Tuple[str, str]


class SecurityWarning(Warning):
    """Warning issued when pickle deserialization proceeds without an allowlist."""


# Global allowlist for pickle deserialization. When set, only
# ``(module, qualname)`` pairs in this list are permitted to be
# reconstructed during ``pickle.loads``.
_global_allowlist: Optional[List[AllowlistEntry]] = None


def set_pickle_serde_allowlist(allowlist: Optional[Iterable[AllowlistEntry]]) -> None:
    """Set a process-wide allowlist of ``(module, qualname)`` pairs that may be
    reconstructed by ``deserialize_pickle``.

    Each entry is a tuple ``(module_name, class_name)``. Use ``"*"`` as the class
    name to permit any class in that module:

    .. code-block:: python

        from burr.integrations.serde import pickle as burr_pickle

        burr_pickle.set_pickle_serde_allowlist([
            ("myapp.models", "User"),
            ("myapp.models", "Address"),
            ("myapp.types", "*"),  # any class in myapp.types
        ])

    When the allowlist is set, any attempt to deserialize a class outside the
    allowlist raises ``pickle.UnpicklingError``. Pass ``None`` to clear it.

    :param allowlist: Iterable of ``(module, qualname)`` tuples, or ``None``.
    """
    global _global_allowlist
    _global_allowlist = list(allowlist) if allowlist is not None else None


def _is_allowed(module: str, name: str, allowlist: Iterable[AllowlistEntry]) -> bool:
    for allowed_module, allowed_name in allowlist:
        if module == allowed_module and (allowed_name == "*" or allowed_name == name):
            return True
    return False


class _RestrictedUnpickler(pickle.Unpickler):
    """Pickle unpickler that only resolves classes present in an allowlist.

    See https://docs.python.org/3/library/pickle.html#restricting-globals
    for the standard library guidance this is modeled on.
    """

    def __init__(self, file, allowlist: Iterable[AllowlistEntry], **kwargs):
        super().__init__(file, **kwargs)
        self._allowlist = list(allowlist)

    def find_class(self, module: str, name: str):
        if not _is_allowed(module, name, self._allowlist):
            raise pickle.UnpicklingError(
                f"Refusing to load pickled class '{module}.{name}': not in the "
                f"pickle serde allowlist. Add it via the ``allowlist`` argument "
                f"to register_type_to_pickle()/deserialize, or call "
                f"burr.integrations.serde.pickle.set_pickle_serde_allowlist([...])."
            )
        return super().find_class(module, name)


def _restricted_loads(data: bytes, allowlist: Iterable[AllowlistEntry], **kwargs):
    return _RestrictedUnpickler(io.BytesIO(data), allowlist, **kwargs).load()


# Tracks call sites that have already received a "no allowlist" warning, so the
# warning is emitted at most once per registration site rather than once per
# deserialization (which could be noisy on hot paths).
_warned_call_sites: set = set()


def register_type_to_pickle(cls, allowlist: Optional[Iterable[AllowlistEntry]] = None):
    """Register a class to be serialized/deserialized using pickle.

    Note: `pickle_kwargs` are passed to the pickle.dumps and pickle.loads functions.

    This will register the passed in class to be serialized/deserialized using pickle.

    .. code-block:: python

        class User:
            def __init__(self, name, email):
                self.name = name
                self.email = email

        from burr.integrations.serde import pickle
        pickle.register_type_to_pickle(User) # this will register the User class to be serialized/deserialized using pickle.

    Trust model
    -----------
    Pickle is, by design, capable of executing arbitrary code during
    deserialization. If the persistence backend (SQLite file, Redis, S3, the
    local filesystem, etc.) can be written to by an untrusted party, a tampered
    payload can trigger remote code execution when burr restores application
    state.

    To mitigate this, pass an ``allowlist`` of permitted ``(module, qualname)``
    pairs. When set, deserialization will refuse to import any class outside
    that list and raise ``pickle.UnpicklingError`` instead. You can also set a
    process-wide default via
    :func:`set_pickle_serde_allowlist`. If no allowlist is configured the legacy
    behavior is preserved but a :class:`SecurityWarning` is emitted once per
    call site.

    .. code-block:: python

        pickle.register_type_to_pickle(
            User,
            allowlist=[("myapp.models", "User")],
        )

    :param cls: The class to register
    :param allowlist: Optional iterable of ``(module, qualname)`` pairs that
        deserialization is permitted to import. ``"*"`` may be used as the
        qualname to allow any class in a given module. If ``None``, falls back
        to the global allowlist set via
        :func:`set_pickle_serde_allowlist`, and if that is also ``None`` the
        legacy unrestricted behavior is used with a :class:`SecurityWarning`.
    """
    local_allowlist: Optional[List[AllowlistEntry]] = (
        list(allowlist) if allowlist is not None else None
    )

    @serde.serialize.register(cls)
    def serialize_pickle(value: cls, pickle_kwargs: dict = None, **kwargs) -> dict:
        """Serializes the value using pickle.

        :param value: the value to serialize.
        :param pickle_kwargs: not required. Optional.
        :param kwargs:
        :return: dictionary of serde.KEY and value
        """
        if pickle_kwargs is None:
            pickle_kwargs = {}
        return {
            serde.KEY: "pickle",
            "value": pickle.dumps(value, **pickle_kwargs),
        }

    @serde.deserializer.register("pickle")
    def deserialize_pickle(
        value: dict,
        pickle_kwargs: dict = None,
        allowlist: Optional[Iterable[AllowlistEntry]] = None,
        **kwargs,
    ) -> cls:
        """Deserializes the value using pickle.

        Resolution order for the effective allowlist:

        1. The ``allowlist`` kwarg passed into deserialize (e.g. via
           ``State.deserialize(..., allowlist=...)``).
        2. The ``allowlist`` argument passed to ``register_type_to_pickle``.
        3. The process-wide default from
           :func:`set_pickle_serde_allowlist`.
        4. None — falls back to the legacy unrestricted ``pickle.loads`` path
           and emits a :class:`SecurityWarning`.

        :param value: the value to deserialize from.
        :param pickle_kwargs: note required. Optional.
        :param allowlist: per-call allowlist override, see above.
        :param kwargs:
        :return: object of type cls
        """
        if pickle_kwargs is None:
            pickle_kwargs = {}
        effective_allowlist: Optional[List[AllowlistEntry]] = None
        if allowlist is not None:
            effective_allowlist = list(allowlist)
        elif local_allowlist is not None:
            effective_allowlist = local_allowlist
        elif _global_allowlist is not None:
            effective_allowlist = _global_allowlist

        if effective_allowlist is not None:
            return _restricted_loads(value["value"], effective_allowlist, **pickle_kwargs)

        # Legacy path — warn once per registration site.
        site_key = (cls.__module__, cls.__qualname__)
        if site_key not in _warned_call_sites:
            _warned_call_sites.add(site_key)
            warnings.warn(
                f"Deserializing pickled class '{cls.__module__}.{cls.__qualname__}' "
                "without an allowlist. This is a remote-code-execution risk if the "
                "persistence backend is writable by untrusted parties. Pass "
                "allowlist=[(module, qualname), ...] to register_type_to_pickle() "
                "or call burr.integrations.serde.pickle.set_pickle_serde_allowlist([...]).",
                SecurityWarning,
                stacklevel=2,
            )
        return pickle.loads(value["value"], **pickle_kwargs)
