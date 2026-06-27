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

"""Workspace API router for the Burr tracking server.

Provides endpoints for:
- File browsing and content reading within a workspace directory
- Python script execution with SSE output streaming
- Process lifecycle management (start, stop, list)
- Workspace-to-project linking (stored in ~/.burr/workspace_links.json)
- Builder project persistence (stored in ~/.burr/builder_projects/)
- Burr ApplicationBuilder usage scanning across .py files
"""

import asyncio
import json as json_module
import logging
import os
import re
import signal
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

_initialized = True  # Module loaded successfully if we reach this point

MAX_FILE_SIZE = 1_048_576  # 1MB

LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".sh": "bash",
    ".txt": "text",
}

BURR_APP_PATTERN = re.compile(r"ApplicationBuilder")


# --- Pydantic Models ---


class WorkspaceLinkRequest(BaseModel):
    """Request body for linking a workspace directory to a project."""

    project_id: str
    workspace_path: str


class WorkspaceLinkInfo(BaseModel):
    """Response for workspace link queries. workspace_path is None if not linked."""

    project_id: str
    workspace_path: Optional[str]


class BuilderProjectSave(BaseModel):
    """Request body for saving a builder project."""

    name: str
    graph_json: str  # JSON-serialized tree


class BuilderProjectSummary(BaseModel):
    """Summary of a saved builder project (used in list responses)."""

    id: str
    name: str
    updated_at: float


class BuilderProjectFull(BaseModel):
    """Full builder project including the serialized graph."""

    id: str
    name: str
    graph_json: str
    updated_at: float


class WorkspaceOpenRequest(BaseModel):
    """Request body for opening/validating a workspace directory."""

    path: str


class WorkspaceInfo(BaseModel):
    """Basic info about an opened workspace."""

    path: str
    name: str


class FileEntry(BaseModel):
    """A single file or directory entry in a workspace listing."""

    name: str
    path: str  # relative to workspace root
    is_dir: bool
    size: int
    modified: float
    is_python: bool
    has_burr_app: bool


class FileContent(BaseModel):
    """Contents of a single file with detected language."""

    path: str
    content: str
    language: str
    size: int


class ProcessInfo(BaseModel):
    """Status of a running or completed Python process."""

    pid: int
    script_path: str
    started_at: float
    status: str  # "running" | "stopped" | "exited"
    exit_code: Optional[int]


class RunRequest(BaseModel):
    """Request body to start a Python script."""

    workspace: str
    script: str


# --- Security ---


def _validate_path(workspace: str, relative: str) -> str:
    """Resolve and validate a file path within a workspace.

    Prevents path traversal by ensuring the resolved target stays within
    the workspace directory. Uses os.sep suffix check to prevent /foo
    matching /foobar.

    Args:
        workspace: Absolute path to the workspace root.
        relative: Relative path within the workspace (may be empty).

    Returns:
        The resolved absolute path to the target.

    Raises:
        HTTPException: 403 if path traversal is detected.
    """
    workspace_real = os.path.realpath(workspace)
    if relative:
        target = os.path.realpath(os.path.join(workspace_real, relative))
    else:
        target = workspace_real
    # Use os.sep suffix to prevent /foo matching /foobar
    if target != workspace_real and not target.startswith(workspace_real + os.sep):
        raise HTTPException(status_code=403, detail="Path traversal detected")
    return target


def _validate_workspace(workspace: str) -> str:
    """Validate that a workspace path is registered via the /link endpoint.

    Checks the workspace against ~/.burr/workspace_links.json to ensure
    only explicitly linked directories can be accessed.

    Args:
        workspace: Absolute path to validate.

    Returns:
        The resolved absolute path.

    Raises:
        HTTPException: 400 if directory doesn't exist, 403 if not registered.
    """
    workspace_real = os.path.realpath(workspace)
    if not os.path.isdir(workspace_real):
        raise HTTPException(status_code=400, detail="Workspace directory does not exist")
    links = _read_links()
    allowed = {os.path.realpath(p) for p in links.values()}
    if workspace_real not in allowed:
        raise HTTPException(status_code=403, detail="Workspace not registered")
    return workspace_real


def _is_binary(file_path: str) -> bool:
    """Detect if a file is binary by checking for null bytes in the first 8KB."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except OSError:
        return True


# --- Workspace Links ---

_LINKS_PATH = os.path.join(os.path.expanduser("~/.burr"), "workspace_links.json")

# In-process cache for workspace links to avoid disk reads on every request.
# No lock needed: all callers are async endpoints on the single event loop
# thread and these helpers never await, so they run serialized.
_links_cache: Optional[dict] = None


def _read_links() -> dict:
    """Read workspace-to-project links from ~/.burr/workspace_links.json.

    Uses an in-process cache that is invalidated on writes via _write_links().
    """
    global _links_cache
    if _links_cache is not None:
        return _links_cache
    if os.path.exists(_LINKS_PATH):
        with open(_LINKS_PATH, "r") as f:
            data = json_module.load(f)
    else:
        data = {}
    _links_cache = data
    return data


def _write_links(data: dict):
    """Write workspace-to-project links to ~/.burr/workspace_links.json.

    Invalidates the in-process cache so subsequent reads pick up changes.
    """
    global _links_cache
    os.makedirs(os.path.dirname(_LINKS_PATH), exist_ok=True)
    with open(_LINKS_PATH, "w") as f:
        json_module.dump(data, f, indent=2)
    _links_cache = data


def is_available() -> bool:
    """Return True if the workspace module initialized successfully.

    Used by run.py to dynamically set supports_workspace in the BackendSpec
    instead of hardcoding True.
    """
    return _initialized


# --- Process Management ---
# Uses asyncio.create_subprocess_exec which takes explicit argv (no shell injection).

_processes: Dict[int, dict] = {}


async def cleanup_processes():
    """Terminate all tracked subprocesses. Called during FastAPI lifespan shutdown."""
    for pid, info in list(_processes.items()):
        proc = info.get("process")
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
    _processes.clear()


# --- Endpoints ---


@router.post("/open", response_model=WorkspaceInfo)
async def open_workspace(request: WorkspaceOpenRequest):
    """Validate and return info about a workspace directory."""
    path = os.path.realpath(request.path)
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Directory does not exist")
    return WorkspaceInfo(path=path, name=os.path.basename(path))


@router.get("/link", response_model=WorkspaceLinkInfo)
async def get_workspace_link(project_id: str = Query(...)):
    """Get the linked workspace path for a project, or null if not linked."""
    links = _read_links()
    return WorkspaceLinkInfo(
        project_id=project_id,
        workspace_path=links.get(project_id),
    )


@router.post("/link", response_model=WorkspaceLinkInfo)
async def set_workspace_link(request: WorkspaceLinkRequest):
    """Link a workspace directory to a project."""
    path = os.path.realpath(request.workspace_path)
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Directory does not exist")
    links = _read_links()
    links[request.project_id] = path
    _write_links(links)
    return WorkspaceLinkInfo(project_id=request.project_id, workspace_path=path)


@router.delete("/link")
async def remove_workspace_link(project_id: str = Query(...)):
    """Remove the workspace link for a project."""
    links = _read_links()
    links.pop(project_id, None)
    _write_links(links)
    return {"ok": True}


@router.get("/tree", response_model=List[FileEntry])
async def get_tree(
    workspace: str = Query(...),
    relative_path: str = Query(""),
):
    """List one level of a directory within a workspace."""
    _validate_workspace(workspace)
    target = _validate_path(workspace, relative_path)
    if not os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Not a directory")

    entries = []
    try:
        for item in sorted(os.listdir(target)):
            if item.startswith("."):
                continue
            full_path = os.path.join(target, item)
            rel = os.path.relpath(full_path, os.path.realpath(workspace))
            try:
                stat = os.stat(full_path)
            except OSError:
                continue
            is_dir = os.path.isdir(full_path)
            is_python = item.endswith(".py")
            has_burr = False
            if is_python and not is_dir:
                try:
                    with open(full_path, "r", errors="ignore") as f:
                        content = f.read(65536)
                        has_burr = bool(BURR_APP_PATTERN.search(content))
                except OSError:
                    pass
            entries.append(
                FileEntry(
                    name=item,
                    path=rel,
                    is_dir=is_dir,
                    size=stat.st_size if not is_dir else 0,
                    modified=stat.st_mtime,
                    is_python=is_python,
                    has_burr_app=has_burr,
                )
            )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
    return entries


@router.get("/file", response_model=FileContent)
async def get_file(
    workspace: str = Query(...),
    relative_path: str = Query(...),
):
    """Read the contents of a file within a workspace. Max 1MB, no binaries."""
    _validate_workspace(workspace)
    target = _validate_path(workspace, relative_path)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="File not found")
    size = os.path.getsize(target)
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 1MB)")
    if _is_binary(target):
        raise HTTPException(status_code=415, detail="Binary file not supported")

    ext = os.path.splitext(target)[1].lower()
    language = LANGUAGE_MAP.get(ext, "text")

    with open(target, "r", errors="replace") as f:
        content = f.read()

    return FileContent(
        path=relative_path,
        content=content,
        language=language,
        size=size,
    )


@router.post("/run", response_model=ProcessInfo)
async def run_script(request: RunRequest):
    """Start a Python script as a subprocess within a workspace."""
    _validate_workspace(request.workspace)
    target = _validate_path(request.workspace, request.script)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="Script not found")
    if not target.endswith(".py"):
        raise HTTPException(status_code=400, detail="Only Python scripts supported")

    # asyncio.create_subprocess_exec takes an explicit argv list,
    # so there is no shell interpretation and no injection risk.
    proc = await asyncio.create_subprocess_exec(
        "python",
        target,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=os.path.realpath(request.workspace),
    )

    started_at = time.time()
    info = {
        "process": proc,
        "script_path": request.script,
        "started_at": started_at,
        "workspace": request.workspace,
    }
    _processes[proc.pid] = info

    return ProcessInfo(
        pid=proc.pid,
        script_path=request.script,
        started_at=started_at,
        status="running",
        exit_code=None,
    )


@router.get("/run/{pid}/output")
async def stream_output(pid: int):
    """Stream stdout/stderr from a running process via Server-Sent Events."""
    if pid not in _processes:
        raise HTTPException(status_code=404, detail="Process not found")

    proc = _processes[pid]["process"]

    async def event_generator():
        """Yield SSE-formatted lines by interleaving stdout and stderr."""

        async def read_stream(stream, stream_type):
            """Read lines from an async stream and yield them as SSE data."""
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                yield f'data: {{"type": "{stream_type}", "data": {_json_escape(text)}}}\n\n'

        stdout_gen = read_stream(proc.stdout, "stdout")
        stderr_gen = read_stream(proc.stderr, "stderr")

        stdout_done = False
        stderr_done = False

        while not stdout_done or not stderr_done:
            tasks = []
            if not stdout_done:
                tasks.append(("stdout", stdout_gen))
            if not stderr_done:
                tasks.append(("stderr", stderr_gen))

            for name, gen in tasks:
                try:
                    line = await asyncio.wait_for(gen.__anext__(), timeout=0.1)
                    yield line
                except StopAsyncIteration:
                    if name == "stdout":
                        stdout_done = True
                    else:
                        stderr_done = True
                except asyncio.TimeoutError:
                    continue

        exit_code = await proc.wait()
        yield f'data: {{"type": "exit", "data": "{exit_code}"}}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/run/{pid}/stop", response_model=ProcessInfo)
async def stop_process(pid: int):
    """Send SIGTERM to a running process."""
    if pid not in _processes:
        raise HTTPException(status_code=404, detail="Process not found")

    info = _processes[pid]
    proc = info["process"]

    if proc.returncode is None:
        try:
            proc.send_signal(signal.SIGTERM)
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (ProcessLookupError, asyncio.TimeoutError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    return ProcessInfo(
        pid=pid,
        script_path=info["script_path"],
        started_at=info["started_at"],
        status="stopped" if proc.returncode is None else "exited",
        exit_code=proc.returncode,
    )


@router.get("/processes", response_model=List[ProcessInfo])
async def list_processes(workspace: str = Query(...)):
    """List all tracked processes for a workspace."""
    _validate_workspace(workspace)
    result = []
    for pid, info in _processes.items():
        if info["workspace"] != workspace:
            continue
        proc = info["process"]
        if proc.returncode is None:
            status = "running"
        else:
            status = "exited"
        result.append(
            ProcessInfo(
                pid=pid,
                script_path=info["script_path"],
                started_at=info["started_at"],
                status=status,
                exit_code=proc.returncode,
            )
        )
    return result


@router.get("/scan", response_model=List[FileEntry])
async def scan_burr_apps(workspace: str = Query(...)):
    """Scan a workspace for .py files containing ApplicationBuilder usage."""
    _validate_workspace(workspace)
    workspace_real = os.path.realpath(workspace)
    if not os.path.isdir(workspace_real):
        raise HTTPException(status_code=400, detail="Workspace not found")

    results = []
    for root, dirs, filenames in os.walk(workspace_real):
        dirs[:] = [
            d for d in dirs if not d.startswith(".") and d != "__pycache__" and d != "node_modules"
        ]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            full_path = os.path.join(root, fname)
            rel = os.path.relpath(full_path, workspace_real)
            try:
                with open(full_path, "r", errors="ignore") as f:
                    content = f.read(65536)
                if BURR_APP_PATTERN.search(content):
                    stat = os.stat(full_path)
                    results.append(
                        FileEntry(
                            name=fname,
                            path=rel,
                            is_dir=False,
                            size=stat.st_size,
                            modified=stat.st_mtime,
                            is_python=True,
                            has_burr_app=True,
                        )
                    )
            except OSError:
                continue
    return results


def _json_escape(s: str) -> str:
    """Escape a string for embedding in SSE JSON data."""
    import json

    return json.dumps(s)


# --- Builder Projects ---

_BUILDER_DIR = os.path.join(os.path.expanduser("~/.burr"), "builder_projects")


def _ensure_builder_dir():
    """Create the builder projects directory if it doesn't exist."""
    os.makedirs(_BUILDER_DIR, exist_ok=True)


@router.get("/builder/projects", response_model=List[BuilderProjectSummary])
async def list_builder_projects():
    """List all saved builder projects from ~/.burr/builder_projects/."""
    _ensure_builder_dir()
    projects = []
    for fname in sorted(os.listdir(_BUILDER_DIR)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(_BUILDER_DIR, fname)
        try:
            with open(fpath, "r") as f:
                data = json_module.load(f)
            projects.append(
                BuilderProjectSummary(
                    id=fname.replace(".json", ""),
                    name=data.get("name", fname),
                    updated_at=os.path.getmtime(fpath),
                )
            )
        except (OSError, json_module.JSONDecodeError):
            continue
    return sorted(projects, key=lambda p: p.updated_at, reverse=True)


@router.post("/builder/projects", response_model=BuilderProjectFull)
async def save_builder_project(request: BuilderProjectSave):
    """Save a builder project graph to ~/.burr/builder_projects/."""
    _ensure_builder_dir()
    # Generate ID from name
    project_id = re.sub(r"[^a-zA-Z0-9_-]", "_", request.name).lower()
    if not project_id:
        project_id = "untitled"
    fpath = os.path.join(_BUILDER_DIR, f"{project_id}.json")
    data = {
        "name": request.name,
        "graph_json": request.graph_json,
    }
    with open(fpath, "w") as f:
        json_module.dump(data, f, indent=2)
    return BuilderProjectFull(
        id=project_id,
        name=request.name,
        graph_json=request.graph_json,
        updated_at=time.time(),
    )


@router.get("/builder/projects/{project_id}", response_model=BuilderProjectFull)
async def get_builder_project(project_id: str):
    """Load a saved builder project by ID."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", project_id)
    fpath = os.path.join(_BUILDER_DIR, f"{safe_id}.json")
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="Project not found")
    with open(fpath, "r") as f:
        data = json_module.load(f)
    return BuilderProjectFull(
        id=safe_id,
        name=data.get("name", safe_id),
        graph_json=data.get("graph_json", "{}"),
        updated_at=os.path.getmtime(fpath),
    )


@router.delete("/builder/projects/{project_id}")
async def delete_builder_project(project_id: str):
    """Delete a saved builder project by ID."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", project_id)
    fpath = os.path.join(_BUILDER_DIR, f"{safe_id}.json")
    if os.path.isfile(fpath):
        os.remove(fpath)
    return {"ok": True}
