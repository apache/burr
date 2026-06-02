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

# try to import to serialize Pydantic Objects
import importlib
import warnings
from typing import List, Optional

import pydantic

from burr.core import serde

# Global allowlist for pydantic deserialization.
# When set, only modules/classes whose fully-qualified module name
# matches an entry in this list (or starts with it, e.g. "mymodule.")
# will be imported during deserialization.
_global_allowlist: Optional[List[str]] = None


def set_allowlist(allowlist: Optional[List[str]]) -> None:
    """Set a global allowlist of permitted modules for pydantic deserialization.

    Each entry should be a fully-qualified module name (e.g. ``myapp.models``).
    Submodules are matched by prefix, so ``myapp`` allows ``myapp``, ``myapp.foo``,
    ``myapp.foo.bar``, etc.

    When an allowlist is set, ``deserialize_pydantic`` will reject any
    ``__pydantic_class`` whose module is not allowed, raising a ``ValueError``.

    :param allowlist: List of permitted module name prefixes, or ``None`` to clear.
    """
    global _global_allowlist
    _global_allowlist = allowlist


def _is_module_allowed(module_name: str, allowlist: Optional[List[str]]) -> bool:
    if allowlist is None:
        return True
    for prefix in allowlist:
        if module_name == prefix or module_name.startswith(prefix + "."):
            return True
    return False


@serde.serialize.register(pydantic.BaseModel)
def serialize_pydantic(value: pydantic.BaseModel, **kwargs) -> dict:
    """Uses pydantic to dump the model to a dictionary and then adds the __pydantic_class to the dictionary."""
    _dict = value.model_dump()
    _dict[serde.KEY] = "pydantic"
    # get qualified name of pydantic class. The module name should be fully qualified.
    _dict["__pydantic_class"] = f"{value.__class__.__module__}.{value.__class__.__name__}"
    return _dict


@serde.deserializer.register("pydantic")
def deserialize_pydantic(
    value: dict, allowlist: Optional[List[str]] = None, **kwargs
) -> pydantic.BaseModel:
    """Deserializes a pydantic object from a dictionary.
    This will pop the __pydantic_class and then import the class.

    Security note: the module name is taken from the serialized payload.
    To mitigate arbitrary code execution from a compromised persistence
    backend, pass an ``allowlist`` of permitted modules, or call
    ``set_allowlist([...])`` globally.
    """
    value.pop(serde.KEY)
    pydantic_class_name = value.pop("__pydantic_class")
    module_name, class_name = pydantic_class_name.rsplit(".", 1)

    effective_allowlist = allowlist if allowlist is not None else _global_allowlist

    if effective_allowlist is not None:
        if not _is_module_allowed(module_name, effective_allowlist):
            raise ValueError(
                f"Pydantic deserialization blocked: module '{module_name}' "
                f"(class '{pydantic_class_name}') is not in the allowlist. "
                f"Add it to the allowlist or use set_allowlist() to permit it."
            )
    else:
        warnings.warn(
            f"Deserializing pydantic class '{pydantic_class_name}' without an allowlist. "
            "This is a security risk if the persistence backend is untrusted. "
            "Consider passing allowlist=... to State.deserialize() or calling "
            "burr.integrations.serde.pydantic.set_allowlist([...]).",
            SecurityWarning,
            stacklevel=2,
        )

    module = importlib.import_module(module_name)
    pydantic_class = getattr(module, class_name)
    return pydantic_class.model_validate(value)


class SecurityWarning(Warning):
    """Warning issued when pydantic deserialization proceeds without an allowlist."""
