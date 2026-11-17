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

"""Filesystem layout for partition-aware local tracking.

Legacy layout (still read, never rewritten or migrated)::

    <storage>/<project>/<app_id>/{graph.json,metadata.json,log.jsonl,children.jsonl}

New layout used for any non-``None`` partition key::

    <storage>/<project>/<app_id>/partitions/p-<sha256>/{graph.json,metadata.json,log.jsonl,children.jsonl}

The partition key itself is never used as a path segment. Its UTF-8 bytes are hashed, so
every separator, control character, Unicode string and empty string maps to one safe
directory name, and no new path-validation rules are needed. The original value remains in
``metadata.json`` and is verified before any legacy or partitioned data is loaded.
"""

import hashlib
import json
import os
from typing import Optional

try:  # #946/#948 add the shared path-containment helper; use it when available.
    from burr.tracking.common.identifiers import join_within as join_path
except ImportError:  # pragma: no cover - exercised only before those PRs land

    def join_path(base: str, *parts: str) -> str:
        return os.path.join(base, *parts)


PARTITIONS_DIRNAME = "partitions"
PARTITION_PREFIX = "p-"


def partition_segment(partition_key: str) -> str:
    """Return the directory name for a non-None partition key."""
    if not isinstance(partition_key, str):
        raise TypeError(
            f"partition_key must be a string or None, got {type(partition_key).__name__}"
        )
    if partition_key == "":
        # Keep the empty string distinct from None without relying on a special directory name.
        return PARTITION_PREFIX + "e"
    digest = hashlib.sha256(partition_key.encode("utf-8")).hexdigest()
    return PARTITION_PREFIX + digest


def application_directory(app_root: str, partition_key: Optional[str]) -> str:
    """Directory holding the tracking files for one (app_id, partition_key) pair."""
    if partition_key is None:
        return app_root
    return join_path(app_root, PARTITIONS_DIRNAME, partition_segment(partition_key))


def partition_directories(app_root: str) -> list[str]:
    """All known partition directories below an application root, in stable order."""
    parent = join_path(app_root, PARTITIONS_DIRNAME)
    if not os.path.isdir(parent):
        return []
    return [
        join_path(parent, name)
        for name in sorted(os.listdir(parent))
        if name.startswith(PARTITION_PREFIX) and os.path.isdir(join_path(parent, name))
    ]


def read_metadata(metadata_path: str) -> Optional[dict]:
    """Read a metadata file, returning None when it is absent or unreadable."""
    if not os.path.exists(metadata_path):
        return None
    try:
        with open(metadata_path, "r", encoding="utf-8", errors="replace") as f:
            value = json.load(f)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def log_has_end_entry(path: str) -> bool:
    """Whether a log file contains at least one completed step.

    An application build creates an empty log before the state loader runs. That empty file
    must not shadow legacy data during an upgrade resume.
    """
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                parsed = _parse_json_line(raw)
                if isinstance(parsed, dict) and parsed.get("type") == "end_entry":
                    return True
    except OSError:
        return False
    return False


def _parse_json_line(raw: str) -> Optional[dict]:
    try:
        return json.loads(raw)
    except ValueError:
        return None


def metadata_partition_key(metadata: Optional[dict]) -> Optional[str]:
    """Extract the partition key from a metadata dict, distinguishing missing values."""
    if metadata is None:
        return None
    return metadata.get("partition_key")


def partition_matches(metadata: Optional[dict], requested: Optional[str]) -> bool:
    """Whether metadata can be used to satisfy a load for ``requested``.

    ``None`` metadata cannot satisfy a request for a specific partition: an old directory
    with no partition information must never be silently attributed to a guessed partition.
    """
    if requested is None:
        return metadata is None or metadata.get("partition_key") is None
    return metadata is not None and metadata.get("partition_key") == requested
