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

"""Validation for the identifiers (project names, application ids) that the tracking
layer turns into filesystem paths, plus a helper that keeps the resulting paths inside
the storage directory."""

import os
import re
from typing import Optional

from burr import system

# Any character except the path separators ("/" and "\") and the control characters
# (NUL through unit separator, and DEL). Checked with ``fullmatch`` so the whole value
# has to satisfy it; a trailing newline is a control character and is refused like any
# other.
IDENTIFIER_PATTERN = re.compile(r"[^/\\\x00-\x1f\x7f]+")
MAX_IDENTIFIER_LENGTH = 255


class InvalidIdentifier(ValueError):
    """An identifier cannot be used as a path segment under the storage directory, or a
    joined path would not stay inside it.

    Subclasses :class:`ValueError` so existing ``except ValueError`` handlers keep working;
    callers that want to report the problem specifically (for instance as an HTTP 400) can
    catch this class instead.
    """


def validate_identifier(value: str, what: str, *, on_windows: Optional[bool] = None) -> str:
    """Checks that ``value`` can be used as any single path segment under the storage directory.

    The rule: a non-empty string of at most 255 characters that is not the special directory
    name ``.`` or ``..`` and contains no ``/``, ``\\``, NUL or other control character. On
    Windows ``:`` is also refused, as it is a drive/stream separator there. Everything else --
    spaces, ``@``, dots, unicode letters -- is an ordinary filename character and is accepted,
    so ids such as ``user@example.com`` or ``chat session 1`` keep working.

    :param value: the identifier to check
    :param what: short label for the error message, e.g. ``"app_id"`` or ``"project"``
    :param on_windows: platform override, defaults to the current platform; exposed for tests
    :return: ``value`` unchanged, so the call can be used inline
    :raises InvalidIdentifier: if the identifier does not meet the rule
    """
    if on_windows is None:
        on_windows = system.IS_WINDOWS
    if not isinstance(value, str):
        raise InvalidIdentifier(f"{what} must be a string, got {type(value).__name__}: {value!r}")
    if not value:
        raise InvalidIdentifier(f"{what} must not be empty")
    if len(value) > MAX_IDENTIFIER_LENGTH:
        raise InvalidIdentifier(
            f"{what} must be at most {MAX_IDENTIFIER_LENGTH} characters, got {len(value)}"
        )
    if value in (".", ".."):
        raise InvalidIdentifier(f"{what} must not be '.' or '..', got {value!r}")
    if IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise InvalidIdentifier(
            f"{what} must be a single path segment: it may not contain '/', '\\' or control "
            f"characters, got {value!r}"
        )
    if on_windows and ":" in value:
        raise InvalidIdentifier(f"{what} may not contain ':' on Windows, got {value!r}")
    return value


def join_within(base: str, *parts: str) -> str:
    """Joins ``parts`` onto ``base`` and checks that the result stays strictly inside ``base``.

    Both sides are resolved with :func:`os.path.realpath` before comparing, so ``..`` segments
    and symlinks are accounted for. The path returned is the plain join (not the resolved
    form) so callers see the same spelling they would get from :func:`os.path.join`.

    :param base: the directory the result must stay inside
    :param parts: path components to join onto ``base``
    :return: ``os.path.join(base, *parts)``
    :raises InvalidIdentifier: if the joined path would land outside ``base``
    """
    joined = os.path.join(base, *parts)
    base_resolved = os.path.realpath(base)
    target_resolved = os.path.realpath(joined)
    try:
        inside = (
            target_resolved != base_resolved
            and os.path.commonpath([base_resolved, target_resolved]) == base_resolved
        )
    except ValueError:
        # commonpath refuses to compare paths on different drives (Windows); treat as outside
        inside = False
    if not inside:
        raise InvalidIdentifier(f"Path {joined!r} is not inside the storage directory {base!r}")
    return joined
