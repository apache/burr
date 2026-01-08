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

import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Optional

from burr import system, telemetry
from burr.core.persistence import PersistedStateData
from burr.integrations.base import require_plugin
from burr.log_setup import setup_logging

try:
    import click
    import requests
    from loguru import logger
except ImportError as e:
    require_plugin(
        e,
        "start",
    )

# Clear default handlers
setup_logging(logging.INFO)


# TODO -- add this as a general callback to the CLI
def _telemetry_if_enabled(event: str):
    if telemetry.is_telemetry_enabled():
        telemetry.create_and_send_cli_event(event)


def _command(command: str, capture_output: bool, addl_env: dict | None = None) -> str:
    """Runs a simple command"""
    if addl_env is None:
        addl_env = {}
    env = os.environ.copy()
    env.update(addl_env)
    logger.info(f"Running command: {command}")
    if isinstance(command, str):
        command = command.split(" ")
        if capture_output:
            try:
                return (
                    subprocess.check_output(command, stderr=subprocess.PIPE, shell=False, env=env)
                    .decode()
                    .strip()
                )
            except subprocess.CalledProcessError as e:
                print(e.stdout.decode())
                print(e.stderr.decode())
                raise e
        subprocess.run(command, shell=False, check=True, env=env)


def _get_git_root() -> str:
    env_root = os.environ.get("BURR_PROJECT_ROOT")
    if env_root:
        return env_root
    try:
        return _command("git rev-parse --show-toplevel", capture_output=True)
    except subprocess.CalledProcessError:
        package_root = _locate_package_root()
        if package_root is not None:
            logger.warning("Not inside a git repository; using package root %s.", package_root)
            return package_root
        logger.warning("Not inside a git repository; defaulting to current directory.")
        return os.getcwd()


def _locate_package_root() -> Optional[str]:
    path = Path(__file__).resolve()
    for candidate in (path.parent,) + tuple(path.parents):
        telemetry_dir = candidate / "telemetry" / "ui"
        if telemetry_dir.exists():
            return str(candidate)
    return None


def open_when_ready(check_url: str, open_url: str):
    while True:
        try:
            response = requests.get(check_url)
            if response.status_code == 200:
                webbrowser.open(open_url)
                return
            else:
                pass
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)


@contextmanager
def cd(path):
    old_dir = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_dir)


@click.group()
def cli():
    pass


def run_build_ui_bash_commands():
    """Execute the bash commands to build UI artifacts."""
    cmd = "npm install --prefix telemetry/ui"
    _command(cmd, capture_output=False)
    cmd = "npm run build --prefix telemetry/ui"
    _command(cmd, capture_output=False)
    # create a symlink so we can get packages inside it...
    cmd = "rm -rf burr/tracking/server/build"
    _command(cmd, capture_output=False)
    cmd = "mkdir -p burr/tracking/server/build"
    _command(cmd, capture_output=False)
    cmd = "cp -a telemetry/ui/build/. burr/tracking/server/build/"
    _command(cmd, capture_output=False)


@cli.command(name="build-ui")
def build_ui():
    """Build the UI artifacts from source."""
    git_root = _get_git_root()
    logger.info("UI build: using project root %s", git_root)
    with cd(git_root):
        run_build_ui_bash_commands()


BACKEND_MODULES = {
    "local": "burr.tracking.server.backend.LocalBackend",
    "s3": "burr.tracking.server.s3.backend.SQLiteS3Backend",
}


def _run_server(
    port: int,
    dev_mode: bool,
    no_open: bool,
    no_copy_demo_data: bool,
    initial_page="",
    host: str = "127.0.0.1",
    backend: str = "local",
):
    _telemetry_if_enabled("run_server")
    # TODO: Implement server running logic here
    # Example: Start a web server, configure ports, etc.
    logger.info(f"Starting server on port {port}")
    cmd = f"uvicorn burr.tracking.server.run:app --port {port} --host {host}"
    if dev_mode:
        cmd += " --reload"

    if backend == "local" and not no_copy_demo_data:
        # TODO: fix this so we don't leak burr_path here since that's the value the local backend users
        base_dir = os.environ.get("burr_path", os.path.expanduser("~/.burr"))
        logger.info(f"Copying demo data over to {base_dir}...")
        demo_data_path = files("burr").joinpath("tracking/server/demo_data")
        for top_level in os.listdir(demo_data_path):
            if not os.path.exists(f"{base_dir}/{top_level}"):
                # this is purely for legacy -- we used to name with `demo_`
                if not system.IS_WINDOWS and os.path.exists(
                    f"{base_dir}/{top_level.replace('demo_', 'demo:')}"
                ):
                    # in this case we don't need to copy it over, it already exists in the right place...
                    continue
                logger.info(f"Copying {top_level} over...")
                shutil.copytree(f"{demo_data_path}/{top_level}", f"{base_dir}/{top_level}")

    if not no_open:
        thread = threading.Thread(
            target=open_when_ready,
            kwargs={
                "open_url": (open_url := f"http://localhost:{port}/{initial_page}"),
                "check_url": f"{open_url}/ready",
            },
            daemon=True,
        )
        thread.start()
    env = {
        "BURR_BACKEND_IMPL": BACKEND_MODULES[backend],
    }
    _command(cmd, capture_output=False, addl_env=env)


@cli.command()
@click.option("--port", default=7241, help="Port to run the server on")
@click.option("--dev-mode", is_flag=True, help="Run the server in development mode")
@click.option("--no-open", is_flag=True, help="Run the server without opening it")
@click.option("--no-copy-demo_data", is_flag=True, help="Don't copy demo data over.")
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to run the server on -- use 0.0.0.0 if you want "
    "to expose it to the network (E.G. in a docker image)",
)
@click.option(
    "--backend",
    default="local",
    help="Backend to use for the server.",
    type=click.Choice(["local", "s3"]),
)
def run_server(
    port: int, dev_mode: bool, no_open: bool, no_copy_demo_data: bool, host: str, backend: str
):
    _run_server(port, dev_mode, no_open, no_copy_demo_data, host=host, backend=backend)


@cli.command()
@click.option("--port", default=7241, help="Port to run the server on")
def demo_server(port: int):
    _run_server(port, True, False, False, "demos/chatbot")


@cli.command(help="Publishes the package to a repository")
@click.option("--prod", is_flag=True, help="Publish to pypi (rather than test pypi)")
@click.option("--no-wipe-dist", is_flag=True, help="Wipe the dist/ directory before building")
def build_and_publish(prod: bool, no_wipe_dist: bool):
    _telemetry_if_enabled("build_and_publish")
    git_root = _get_git_root()
    with cd(git_root):
        logger.info("Building UI -- this may take a bit...")
        build_ui()
        logger.info("Built UI!")
        if not no_wipe_dist:
            logger.info("Wiping dist/ directory for a clean publish.")
            shutil.rmtree("dist", ignore_errors=True)
        _command("python3 -m build", capture_output=False)
        repository = "pypi" if prod else "testpypi"
        _command(f"python3 -m twine upload --repository {repository} dist/*", capture_output=False)
        logger.info(f"Published to {repository}! 🎉")


@cli.command(help="generate demo data for the UI")
@click.option(
    "--s3-bucket", help="S3 URI to save to, will use the s3 tracker, not local mode", required=False
)
@click.option(
    "--data-dir",
    help="Local directory to save to",
    required=False,
    default="burr/tracking/server/demo_data",
)
@click.option("--unique-app-names", help="Use unique app names", is_flag=True)
@click.option("--no-clear-current-data", help="Don't clear current data", is_flag=True)
def generate_demo_data(s3_bucket, data_dir, unique_app_names: bool, no_clear_current_data: bool):
    _telemetry_if_enabled("generate_demo_data")
    git_root = _get_git_root()
    # We need to add the examples directory to the path so we have all the imports
    # The GPT-one relies on a local import
    sys.path.extend([git_root, f"{git_root}/examples/multi-modal-chatbot"])
    from burr.cli.demo_data import generate_all

    # local mode
    if s3_bucket is None:
        with cd(git_root):
            logger.info("Removing old demo data")
            if not no_clear_current_data:
                shutil.rmtree(data_dir, ignore_errors=True)
            generate_all(data_dir=data_dir, unique_app_names=unique_app_names)
    else:
        generate_all(s3_bucket=s3_bucket, unique_app_names=unique_app_names)


def _remove_private_keys(state: dict):
    return {key: value for key, value in state.items() if not key.startswith("__")}


def _transform_state_to_test_case(
    before_action_state: dict, after_action_state: dict, action_name: str, test_name: str
) -> dict:
    """Helper function to transform a state into a test case.

    :param state:
    :param action_name:
    :param test_name:
    :return:
    """
    # Remove private Burr keys -- don't want to expose these in the test case since we could change them
    before_action_state = _remove_private_keys(before_action_state)
    after_action_state = _remove_private_keys(after_action_state)
    return {
        "action": action_name,
        "name": test_name,
        "input_state": before_action_state,
        "expected_state": after_action_state,
    }


@click.group()
def test_case():
    """Test case related commands."""
    pass


PYTEST_TEMPLATE = """import pytest
from burr.core import state
from burr.testing import pytest_generate_tests  # noqa: F401
# TODO: import action you're testing, i.e. import {ACTION_NAME}.

@pytest.mark.file_name("{FILE_NAME}")
def test_{ACTION_NAME}(input_state, expected_state):
    \"\"\"Function for testing the action\"\"\"
    input_state = state.State.deserialize(input_state)
    expected_state = state.State.deserialize(expected_state)
    _, output_state = {ACTION_NAME}(input_state)  # exercise the action
    # TODO: choose appropriate way to evaluate the output
    # e.g. exact match, fuzzy match, LLM grade, etc.
    # this is exact match here on all values in state
    assert output_state == expected_state
    # e.g.
    # assert 'some value' in output_state["response"]["content"]
    # assert llm_evaluator(..., ...) == "Y"
"""


def import_from_file(file_path: str) -> ModuleType:
    """Import a module from a file path.

    :param file_path: file path. Assume it exists.
    :return:
    """
    # Extract the module name and directory from the file path
    module_name = os.path.basename(file_path).replace(".py", "")
    module_dir = os.path.dirname(file_path)

    # Add the module directory to sys.path if not already included
    if module_dir not in sys.path:
        sys.path.append(module_dir)

    # Import the module
    module = importlib.import_module(module_name)

    return module


@click.command()
@click.option("--project-name", required=True, help="Name of the project.")
@click.option("--partition-key", required=False, help="Partition key to look at.")
@click.option("--app-id", required=True, help="App ID to pull from.")
@click.option("--sequence-id", required=True, help="Sequence ID to pull.")
@click.option(
    "--target-file-name",
    required=False,
    help="What file to write the data to. Else print to console.",
)
@click.option(
    "--serde-module",
    required=False,
    help="Python file or fully qualified python module to import for custom serialization/deserialization.",
)
@click.option(
    "--action-name",
    required=False,
    help="Provide name of the action for the test case. Defaults to the action name at the sequence ID.",
)
def create_test_case(
    project_name: str,
    partition_key: str,  # will be None if not passed in.
    app_id: str,
    sequence_id: str,
    target_file_name: str = None,
    serde_module: str = None,
    action_name: str = None,
):
    """Create a test case from a persisted state.

    Does two things:

    1. Pulls data specified and saves it/prints to console.
    2. Prints a pytest test case to the console for you to cut and paste.

    See examples/test-case-creation/notebook.ipynb for example usage.
    See examples/test-case-creation/test_application.py for details.

    If you have custom serialization/deserialization then pass in the name of a
    python module, or a path to a python file, to import with your custom serialization/deserialization
    registration functions. This will be imported so that they can be registered.

    Note:
        - when burr fails, then the state retrieved for a sequence ID is the state at the start of the sequence ID.
          The fixture created will only have input state.
        - when burr completes successfully, then the state retrieved for a sequence ID is the final modified state.
          The fixture created will have input and output state, as we will grab the prior sequence ID's state
          as the input state.
        - we strip any keys prefixed with __ from the state to avoid exposing private keys in the test case.
    """
    if serde_module:
        if os.path.exists(serde_module):
            logger.info(f"Importing from file {serde_module}")
            import_from_file(serde_module)
        else:
            logger.info(f"Importing module {serde_module}")
            import importlib

            importlib.import_module(serde_module)

    # TODO: make this handle instantiating/using a persister other than local tracker
    from burr.tracking.client import LocalTrackingClient

    local_tracker = LocalTrackingClient(project=project_name)
    sequence_id = int(sequence_id)

    after_action: PersistedStateData = local_tracker.load(
        partition_key=partition_key, app_id=app_id, sequence_id=sequence_id
    )
    if not after_action:
        print(f"No state found for {project_name}, {partition_key}, {app_id}, {sequence_id}.")
        return

    action_name = action_name if action_name else after_action["position"]
    """
    Explanation of the logic here.
    If there's an error:
     - status would be failed vs completed
     - state loaded would be the starting state
    If there's no error:
     - status would be completed
     - state loaded would be the ending state, so to get the starting state, we need to look at the prior sequence ID
    """
    if after_action["status"] == "completed":
        print("Action was successful so loading initial and expected state into test fixture.")
        after_action_state = after_action["state"].serialize()
        # if it's completed, then we need to look at the prior sequence ID to get the input state
        prior_sequence_id = sequence_id - 1
        try:
            # TODO: handle forked case. i.e. prior doesn't exist because it was a forked sequence.
            before_action: PersistedStateData = local_tracker.load(
                partition_key=partition_key, app_id=app_id, sequence_id=prior_sequence_id
            )
        except ValueError:
            before_action = None

        if not before_action:
            # there was no initial state saved for this sequence id
            print(
                f"Warning: there was no initial state found sequence ID {sequence_id}. That is, we looked for the "
                f"prior state corresponding to the prior sequence ID {prior_sequence_id}, but did not find a state "
                f"value. Was this application ID forked? Defaulting to empty state - please fill this in."
            )
            before_action_state = {"TODO:": "fill this in"}
        else:
            before_action_state = before_action["state"].serialize()
    else:
        print("Action was not successful so loading initial state into test fixture.")
        # there was an error so state is the starting state
        before_action_state = after_action["state"].serialize()
        after_action_state = {"TODO:": "fill this in"}

    # test case json
    tc_json = _transform_state_to_test_case(
        before_action_state,
        after_action_state,
        action_name,
        f"{action_name}_{app_id[:8] + '_' + str(sequence_id)}",
    )

    if target_file_name:
        # if it already exists, load it up and append to it
        if os.path.exists(target_file_name):
            with open(target_file_name, "r") as f:
                # assumes it's a list of test cases
                current_testcases = json.load(f)
            current_testcases.append(tc_json)
        else:
            current_testcases = [tc_json]
        print(f"\nWriting data to file {target_file_name}")
        with open(target_file_name, "w") as f:
            json.dump(current_testcases, f, indent=2)
    else:
        logger.info(json.dumps(tc_json, indent=2))
    # print out python test to add
    print("\nAdd the following to your test file:\n")
    print(PYTEST_TEMPLATE.format(FILE_NAME=target_file_name, ACTION_NAME=action_name))


test_case.add_command(create_test_case, name="create")
cli.add_command(test_case)

# quick trick to expose every subcommand as a variable
# will create a command called `cli_{command}` for every command we have
for key, command in cli.commands.items():
    globals()[f'cli_{key.replace("-", "_")}'] = command

if __name__ == "__main__":
    cli()
