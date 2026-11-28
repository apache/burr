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

import threading
import uuid

import pytest

from burr.core import state
from burr.core.persistence import PersistenceConflictError


def _save_step_at_once(persisters, app_id):
    """Each persister saves step 0 of app_id at the same moment. Returns what each save raised."""
    barrier = threading.Barrier(len(persisters))
    outcomes = [None] * len(persisters)

    def save(writer):
        barrier.wait()
        try:
            persisters[writer].save(
                "race", app_id, 0, "step", state.State({"writer": writer}), "completed"
            )
        except Exception as e:
            outcomes[writer] = e

    threads = [threading.Thread(target=save, args=(writer,)) for writer in range(len(persisters))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


@pytest.fixture
def assert_one_concurrent_save_wins():
    """The persisters stand for processes running the same app. When they save the same step at
    the same moment, exactly one save succeeds, the others raise PersistenceConflictError, and
    the stored state is the winner's."""

    def check(persisters, rounds=50):
        for _ in range(rounds):
            app_id = f"race-{uuid.uuid4()}"
            outcomes = _save_step_at_once(persisters, app_id)
            winners = [writer for writer, raised in enumerate(outcomes) if raised is None]
            assert len(winners) == 1, outcomes
            losers = [raised for raised in outcomes if raised is not None]
            assert all(isinstance(raised, PersistenceConflictError) for raised in losers), losers
            assert persisters[0].load("race", app_id, 0)["state"]["writer"] == winners[0]

    return check
