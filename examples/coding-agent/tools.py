"""Tools the coding agent can call. Each takes typed args and returns a dict."""
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
import subprocess

# Everything is confined to this directory. See README on why this is not a sandbox.
WORKSPACE = os.environ.get("CODING_AGENT_WORKSPACE", "./workspace")


def _resolve(path: str) -> str:
    """Resolve a path inside the workspace, refusing anything that escapes it.

    Resolves symlinks (``realpath`` rather than ``abspath``) so that a link
    placed inside the workspace cannot be followed out of it.
    """
    root = os.path.realpath(WORKSPACE)
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(root + os.sep) and full != root:
        raise ValueError(f"path escapes workspace: {path}")
    return full


def list_files(directory: str = ".") -> dict:
    """Lists the files and directories at the given path inside the workspace."""
    try:
        target = _resolve(directory)
        return {"entries": sorted(os.listdir(target))}
    except (ValueError, OSError) as e:
        return {"error": str(e)}


def read_file(path: str) -> dict:
    """Reads a text file from the workspace and returns its contents."""
    try:
        with open(_resolve(path)) as f:
            return {"path": path, "contents": f.read()}
    except (ValueError, OSError) as e:
        return {"error": str(e)}


def write_file(path: str, contents: str) -> dict:
    """Writes text to a file in the workspace, creating or overwriting it."""
    try:
        full = _resolve(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(contents)
        return {"path": path, "bytes_written": len(contents)}
    except (ValueError, OSError) as e:
        return {"error": str(e)}


def run_bash(command: str) -> dict:
    """Runs a shell command in the workspace and returns its output."""
    try:
        workspace = os.path.realpath(WORKSPACE)
        # The workspace may not exist yet -- a model that starts by running a
        # command rather than writing a file should still get a useful answer.
        os.makedirs(workspace, exist_ok=True)
        proc = subprocess.run(
            command,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {"error": "command timed out after 30s"}
    except OSError as e:
        return {"error": str(e)}
