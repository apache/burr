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
This module contains code that relates to sending Burr usage telemetry.

To disable sending telemetry there are three ways:

1. Set it to false programmatically in your driver:
  >>> from burr import telemetry
  >>> telemetry.disable_telemetry()
2. Set it to `false` in ~/.burr.conf under `DEFAULT`
  [DEFAULT]
  telemetry_enabled = False
3. Set BURR_TELEMETRY_ENABLED=false as an environment variable:
  BURR_TELEMETRY_ENABLED=false python run.py
  or:
  export BURR_TELEMETRY_ENABLED=false
"""

import configparser
import functools
import importlib.metadata
import json
import logging
import os
import platform
import threading
import uuid
from typing import TYPE_CHECKING, Callable, List, TypeVar
from urllib import request

if TYPE_CHECKING:
    from burr.lifecycle import internal

try:
    VERSION = importlib.metadata.version("apache-burr")
except importlib.metadata.PackageNotFoundError:
    # Fallback for older installations or development
    VERSION = importlib.metadata.version("burr")

logger = logging.getLogger(__name__)

STR_VERSION = ".".join([str(i) for i in VERSION])
HOST = "https://app.posthog.com"
TRACK_URL = f"{HOST}/capture/"  # https://posthog.com/docs/api/post-only-endpoints
API_KEY = "phc_qMa4hWDdTruKaDb4Oa0tK0i1SKf69xf81OCFzjX6z4U"
APPLICATION_FUNCTION = "os_burr_application_function_call"
CLI_COMMAND = "os_burr_cli_command"
TIMEOUT = 2
MAX_COUNT_SESSION = 10  # max number of events collected per python process

DEFAULT_CONFIG_LOCATION = os.path.expanduser("~/.burr.conf")


def _load_config(config_location: str) -> configparser.ConfigParser:
    """Pulls config. Gets/sets default anonymous ID.

    Creates the anonymous ID if it does not exist, writes it back if so.
    :param config_location: location of the config file.
    """
    config = configparser.ConfigParser()
    try:
        with open(config_location) as f:
            config.read_file(f)
    except Exception:
        config["DEFAULT"] = {}
    else:
        if "DEFAULT" not in config:
            config["DEFAULT"] = {}

    if "anonymous_id" not in config["DEFAULT"]:
        config["DEFAULT"]["anonymous_id"] = str(uuid.uuid4())
        try:
            with open(config_location, "w") as f:
                config.write(f)
        except Exception:
            pass
    return config


def _check_config_and_environ_for_telemetry_flag(
    telemetry_default: bool, config_obj: configparser.ConfigParser
):
    """Checks the config and environment variables for the telemetry value.

    Note: the environment variable has greater precedence than the config value.
    """
    telemetry_enabled = telemetry_default
    if "telemetry_enabled" in config_obj["DEFAULT"]:
        try:
            telemetry_enabled = config_obj.getboolean("DEFAULT", "telemetry_enabled")
        except ValueError as e:
            logger.debug(
                "Unable to parse value for `telemetry_enabled` from config. " f"Encountered {e}"
            )
    if os.environ.get("BURR_TELEMETRY_ENABLED") is not None:
        env_value = os.environ.get("BURR_TELEMETRY_ENABLED")
        # set the value
        config_obj["DEFAULT"]["telemetry_enabled"] = env_value
        try:
            telemetry_enabled = config_obj.getboolean("DEFAULT", "telemetry_enabled")
        except ValueError as e:
            logger.debug(
                "Unable to parse value for `BURR_TELEMETRY_ENABLED` from environment. "
                f"Encountered {e}"
            )
    return telemetry_enabled


config = _load_config(DEFAULT_CONFIG_LOCATION)
g_telemetry_enabled = _check_config_and_environ_for_telemetry_flag(True, config)
g_anonymous_id = config["DEFAULT"]["anonymous_id"]
call_counter = 0


def disable_telemetry():
    """Disables telemetry tracking."""
    global g_telemetry_enabled
    g_telemetry_enabled = False


def is_telemetry_enabled() -> bool:
    """Returns whether telemetry tracking is enabled or not.

    Increments a counter to stop sending telemetry after 1000 invocations.
    """
    if g_telemetry_enabled:
        global call_counter
        if call_counter == 0:
            # Log only the first time someone calls this function; don't want to spam them.
            logger.info(
                "Note: Burr collects completely anonymous data about usage. "
                "This will help us improve Burr over time. "
                "See https://github.com/dagworks-inc/burr#usage-analytics--data-privacy for details."
            )
        call_counter += 1
        if call_counter > MAX_COUNT_SESSION:
            # we have hit our limit -- disable telemetry.
            return False
        return True
    else:
        return False


# base properties to instantiate on module load.
BASE_PROPERTIES = {
    "os_type": os.name,
    "os_version": platform.platform(),
    "python_version": f"{platform.python_version()}/{platform.python_implementation()}",
    "distinct_id": g_anonymous_id,
    "burr_version": VERSION,
    "telemetry_version": "0.0.1",
}


def create_application_function_run_event(function_name: str) -> dict:
    """Function to create payload for tracking function name invocation.

    :param function_name: the name of the driver function
    :return: dict representing the JSON to send.
    """
    event = {
        "api_key": API_KEY,
        "event": APPLICATION_FUNCTION,
        "properties": {},
    }
    event["properties"].update(BASE_PROPERTIES)
    payload = {
        "function_name": function_name,  # what was the name of the driver function?
    }
    event["properties"].update(payload)
    return event


def _send_event_json(event_json: dict):
    """Internal function to send the event JSON to posthog.

    :param event_json: the dictionary of data to JSON serialize and send
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": "TODO",
        "User-Agent": f"burr/{STR_VERSION}",
    }
    try:
        data = json.dumps(event_json).encode()
        req = request.Request(TRACK_URL, data=data, headers=headers)
        with request.urlopen(req, timeout=TIMEOUT) as f:
            res = f.read()
            if f.code != 200:
                raise RuntimeError(res)
    except Exception as e:
        if logger.isEnabledFor(logging.DEBUG):
            logging.debug(f"Failed to send telemetry data: {e}")
    else:
        if logger.isEnabledFor(logging.DEBUG):
            logging.debug(f"Succeed in sending telemetry consisting of [{data}].")


def send_event_json(event_json: dict):
    """Sends the event json in its own thread.

    :param event_json: the data to send
    """
    if not g_telemetry_enabled:
        raise RuntimeError("Won't send; tracking is disabled!")
    try:
        th = threading.Thread(target=_send_event_json, args=(event_json,))
        th.start()
    except Exception as e:
        # capture any exception!
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Encountered error while sending event JSON via it's own thread:\n{e}")


def get_all_adapters_names(adapter: "internal.LifecycleAdapterSet") -> List[str]:
    """Gives a list of all adapter names in the LifecycleAdapterSet.
    Simply a loop over the adapters it contains.

    :param adapter: LifecycleAdapterSet object.
    :return: list of adapter names.
    """
    adapters = adapter.adapters
    out = []
    for adapter in adapters:
        out.append(get_adapter_name(adapter))
    return out


def get_adapter_name(adapter: "internal.LifecycleAdapter") -> str:
    """Get the class name of the ``burr`` adapter used.

    If we detect it's not a Burr one, we do not track it.

    :param adapter: lifecycle.internal.LifecycleAdapter object.
    :return: string module + class name of the adapter.
    """
    # Check whether it's a burr based adapter
    if adapter.__module__.startswith("burr."):
        adapter_name = f"{adapter.__module__}.{adapter.__class__.__name__}"
    else:
        adapter_name = "custom_adapter"
    return adapter_name


def create_and_send_cli_event(command: str):
    """Function that creates JSON and sends to track CLI usage.

    :param command: the CLI command run.
    """
    event = {
        "api_key": API_KEY,
        "event": CLI_COMMAND,
        "properties": {},
    }
    event["properties"].update(BASE_PROPERTIES)

    payload = {
        "command": command,
    }
    event["properties"].update(payload)
    send_event_json(event)


CallableT = TypeVar("CallableT", bound=Callable)


def capture_function_usage(call_fn: CallableT) -> CallableT:
    """Decorator to wrap some application functions for telemetry capture.

    We want to use this for non-execute functions.
    We don't capture information about the arguments at this stage,
    just the function name.

    :param call_fn: the Driver function to capture.
    :return: wrapped function.
    """

    @functools.wraps(call_fn)
    def wrapped_fn(*args, **kwargs):
        try:
            return call_fn(*args, **kwargs)
        finally:
            if is_telemetry_enabled():
                try:
                    function_name = call_fn.__name__
                    event_json = create_application_function_run_event(function_name)
                    send_event_json(event_json)
                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.error(
                            f"Failed to send telemetry for function usage. Encountered: {e}\n"
                        )

    return wrapped_fn
