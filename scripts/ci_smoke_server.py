#!/usr/bin/env python3
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

"""
End-to-end smoke test for a built Burr wheel.

Installs the wheel into a fresh venv (outside the source tree), starts the
`burr` tracking server, runs a simple tracked application, and verifies the
server observes it via the HTTP API.

Fails fast with clear output if any step breaks. Designed to run in CI.

Usage:
    python scripts/ci_smoke_server.py --wheel dist/apache_burr-0.42.0-py3-none-any.whl

The `burr.examples.hello-world-counter` bug (missing module at server import
time) would be caught here because starting the server triggers the module-
level importlib.import_module calls in burr/tracking/server/run.py.
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def _free_port() -> int:
    """Pick an available localhost port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _log(msg: str) -> None:
    print(f"[smoke] {msg}", flush=True)


def _fail(msg: str) -> "None":
    print(f"[smoke] FAIL: {msg}", flush=True)
    sys.exit(1)


def _poll_url(url: str, timeout_s: int = 30, server_proc: "subprocess.Popen | None" = None) -> bool:
    """Poll URL until 200 or timeout. Fails fast if server process dies."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if server_proc is not None and server_proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionResetError, TimeoutError):
            pass
        time.sleep(1)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, help="Path to the wheel to smoke-test")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter to use for the venv (default: current)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port for the burr server (0 = auto-pick free port)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=45,
        help="Seconds to wait for the server to become ready",
    )
    args = parser.parse_args()

    wheel_path = Path(args.wheel).resolve()
    if not wheel_path.is_file():
        _fail(f"Wheel not found: {wheel_path}")

    port = args.port if args.port else _free_port()

    # Fresh working dirs, outside of any source tree
    work_dir = Path(tempfile.mkdtemp(prefix="burr-smoke-"))
    venv_dir = work_dir / "venv"
    burr_data_dir = work_dir / "burr-data"
    burr_data_dir.mkdir()
    server_log = work_dir / "server.log"
    app_script = work_dir / "tracked_app.py"

    _log(f"Workspace: {work_dir}")
    _log(f"Python: {args.python}")
    _log(f"Wheel: {wheel_path}")

    server_proc = None
    try:
        # 1. Create venv
        _log("Creating venv...")
        subprocess.run([args.python, "-m", "venv", str(venv_dir)], check=True)

        venv_py = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        venv_burr = venv_dir / ("Scripts/burr.exe" if os.name == "nt" else "bin/burr")

        # 2. Install wheel
        _log("Installing wheel (with [learn] extras)...")
        subprocess.run(
            [str(venv_py), "-m", "pip", "install", "--upgrade", "pip", "--quiet"], check=True
        )
        subprocess.run(
            [str(venv_py), "-m", "pip", "install", f"{wheel_path}[learn]", "--quiet"],
            check=True,
        )

        # 3. Smoke check: import the server module. This is the minimal check that
        # would have caught the hello-world-counter regression without needing to
        # actually start uvicorn.
        _log("Importing burr.tracking.server.run (catches missing-example bugs)...")
        subprocess.run(
            [str(venv_py), "-c", "import burr.tracking.server.run"],
            check=True,
            cwd=str(work_dir),
        )

        # 4. Start server from outside the source tree so CWD can't shadow the install.
        _log(f"Starting burr server on port {port}...")
        env = os.environ.copy()
        env["burr_path"] = str(burr_data_dir)
        env["PYTHONUNBUFFERED"] = "1"
        with open(server_log, "w") as log_fh:
            server_proc = subprocess.Popen(
                [str(venv_burr), "--port", str(port), "--no-open"],
                cwd=str(work_dir),
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )

        base_url = f"http://127.0.0.1:{port}"
        _log(f"Waiting up to {args.timeout}s for {base_url}/ready ...")
        if not _poll_url(f"{base_url}/ready", timeout_s=args.timeout, server_proc=server_proc):
            if server_proc.poll() is not None:
                _log(f"Server process exited with code {server_proc.returncode}")
            _log("--- server log ---")
            print(server_log.read_text(), flush=True)
            _log("--- end server log ---")
            _fail("Server did not become ready")
        _log("Server is up")

        # 5. Run a tracked Burr app as a separate process using the venv.
        _log("Running tracked Burr app...")
        app_script.write_text(
            f"""\
from burr.core import ApplicationBuilder, State, default
from burr.core.action import action
from burr.tracking import LocalTrackingClient


@action(reads=["count"], writes=["count"])
def inc(state: State) -> State:
    return state.update(count=state["count"] + 1)


tracker = LocalTrackingClient(project="ci-smoke-test", storage_dir={str(burr_data_dir)!r})

app = (
    ApplicationBuilder()
    .with_actions(inc)
    .with_transitions(("inc", "inc", default))
    .with_state(count=0)
    .with_entrypoint("inc")
    .with_tracker(tracker)
    .build()
)

for _ in range(3):
    app.step()

print(f"count={{app.state['count']}} app_id={{app.uid}}")
"""
        )
        subprocess.run([str(venv_py), str(app_script)], check=True, cwd=str(work_dir), env=env)

        # 6. Verify the server sees the project.
        _log("Verifying server sees project 'ci-smoke-test'...")
        time.sleep(2)  # give the server a moment to pick up the filesystem change
        with urllib.request.urlopen(f"{base_url}/api/v0/projects", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = [p.get("name") for p in data]
        if "ci-smoke-test" not in names:
            _fail(f"Project 'ci-smoke-test' not found. Projects seen: {names}")
        _log(f"Projects: {names}")

        _log("SUCCESS")
    finally:
        if server_proc is not None and server_proc.poll() is None:
            _log("Stopping server...")
            server_proc.send_signal(signal.SIGTERM)
            try:
                server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_proc.kill()
        # Leave work_dir intact in CI (uploadable as artifact); also leave it locally
        # on failure for easier debugging. Caller can rm -rf /tmp/burr-smoke-* to clean up.


if __name__ == "__main__":
    main()
