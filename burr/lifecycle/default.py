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

import datetime
import json
import time
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional

if TYPE_CHECKING:
    from burr.core import State, Action

from burr.lifecycle.base import PostRunStepHook, PreRunStepHook


def safe_json(obj: Any) -> str:
    return json.dumps(obj, default=str)


class StateAndResultsFullLogger(PostRunStepHook, PreRunStepHook):
    """Logs the state and results of the action in a jsonl file."""

    DONT_INCLUDE = object()  # sentinel value

    def __init__(
        self,
        jsonl_path: str,
        mode: Literal["append", "w"] = "append",
        json_dump: Callable[[dict], str] = safe_json,
    ):
        """Initializes the logger.

        :param jsonl_path: Path to the jsonl file
        :param mode: Mode to open the file in. Either "append" or "w"
        :param json_dump: Function to use to dump the json. Default is safe_json
        """
        if not jsonl_path.endswith(".jsonl"):
            raise ValueError(f"jsonl_path must end with .jsonl. Got: {jsonl_path}")
        self.jsonl_path = jsonl_path
        open_mode = "a" if mode == "append" else "w"
        self.f = open(jsonl_path, mode=open_mode, encoding="utf-8")
        self.tracker = []  # tracker to keep track of timing/whatnot
        self.json_dump = json_dump

    def pre_run_step(self, **future_kwargs: Any):
        self.tracker.append({"time": datetime.datetime.now()})

    def post_run_step(
        self,
        *,
        state: "State",
        action: "Action",
        result: Optional[dict],
        exception: Exception,
        **future_kwargs: Any,
    ):
        state_and_result = {
            "state": state.get_all(),
            "action": action.name,
            "result": result,
            "exception": str(exception),
            "start_time": self.tracker[-1]["time"].isoformat(),
            "end_time": datetime.datetime.now().isoformat(),
        }
        self.f.writelines([self.json_dump(state_and_result) + "\n"])

    def __del__(self):
        if hasattr(self, "f"):
            # possible something fails beforehand
            self.f.close()


class SlowDownHook(PostRunStepHook, PreRunStepHook):
    """Slows down execution. You'll only want to use this for debugging/visualizing."""

    def __init__(self, pre_sleep_time: float = 0.5, post_sleep_time: float = 0.5):
        """Initializes the hook.

        :param pre_sleep_time: Time to sleep before the step
        :param post_sleep_time: Time to sleep after the step
        """
        self.post_sleep_time = post_sleep_time
        self.pre_sleep_time = pre_sleep_time

    def post_run_step(
        self,
        *,
        state: "State",
        action: "Action",
        result: Optional[dict],
        exception: Exception,
        **future_kwargs: Any,
    ):
        time.sleep(self.post_sleep_time)

    def pre_run_step(self, *, state: "State", action: "Action", **future_kwargs: Any):
        time.sleep(self.pre_sleep_time)
