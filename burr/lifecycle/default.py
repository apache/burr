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

import copy
import dataclasses
import datetime
import json
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Literal, Optional

if TYPE_CHECKING:
    from burr.core import State, Action

from burr.lifecycle.base import PostRunStepHook, PreRunStepHook


def safe_json(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _values_equal(left: Any, right: Any) -> bool:
    if left is right:
        return True
    try:
        comparison = left == right
    except Exception:
        return False
    return comparison if isinstance(comparison, bool) else False


def _copy_for_recording(value: Any) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _copy_mapping_for_recording(values: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if values is None:
        return None
    return {key: _copy_for_recording(value) for key, value in values.items()}


@dataclasses.dataclass(frozen=True)
class StateChange:
    """A single state field change captured around an action execution."""

    key: str
    before_exists: bool
    before: Any
    after_exists: bool
    after: Any


@dataclasses.dataclass(frozen=True)
class ExecutionRecord:
    """An immutable record of one Burr action execution."""

    app_id: str
    partition_key: Optional[str]
    sequence_id: int
    action: str
    inputs: Dict[str, Any]
    result: Optional[Dict[str, Any]]
    exception: Optional[Exception]
    state_changes: tuple[StateChange, ...]


class InMemoryExecutionRecorder(PreRunStepHook, PostRunStepHook):
    """Capture action executions in memory for tests and local debugging.

    The recorder stores inputs, results, exceptions, and business-state changes.
    Burr's private ``__`` state fields are excluded from the change list.
    """

    def __init__(self):
        self._records: list[ExecutionRecord] = []
        self._pending: dict[tuple[str, Optional[str], int], tuple[dict, dict]] = {}

    @property
    def records(self) -> tuple[ExecutionRecord, ...]:
        """Return an immutable snapshot of captured execution records."""
        return tuple(self._records)

    def clear(self) -> None:
        """Remove all completed and pending records."""
        self._records.clear()
        self._pending.clear()

    def pre_run_step(
        self,
        *,
        app_id: str,
        partition_key: Optional[str],
        sequence_id: int,
        state: "State",
        inputs: Dict[str, Any],
        **future_kwargs: Any,
    ) -> None:
        key = (app_id, partition_key, sequence_id)
        self._pending[key] = (
            _copy_mapping_for_recording(state.get_all()),
            _copy_mapping_for_recording(inputs),
        )

    def post_run_step(
        self,
        *,
        app_id: str,
        partition_key: Optional[str],
        sequence_id: int,
        state: "State",
        action: "Action",
        result: Optional[Dict[str, Any]],
        exception: Optional[Exception],
        **future_kwargs: Any,
    ) -> None:
        key = (app_id, partition_key, sequence_id)
        before, inputs = self._pending.pop(key)
        after = state.get_all()
        changed_keys = sorted(
            key
            for key in before.keys() | after.keys()
            if not key.startswith("__")
            and (
                (key in before) != (key in after)
                or not _values_equal(before.get(key), after.get(key))
            )
        )
        changes = tuple(
            StateChange(
                key=state_key,
                before_exists=state_key in before,
                before=_copy_for_recording(before.get(state_key)),
                after_exists=state_key in after,
                after=_copy_for_recording(after.get(state_key)),
            )
            for state_key in changed_keys
        )
        self._records.append(
            ExecutionRecord(
                app_id=app_id,
                partition_key=partition_key,
                sequence_id=sequence_id,
                action=action.name,
                inputs=inputs,
                result=_copy_mapping_for_recording(result),
                exception=exception,
                state_changes=changes,
            )
        )


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
