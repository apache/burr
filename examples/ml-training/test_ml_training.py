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

import joblib
from application import application


def _run(app, **inputs):
    app.run(
        halt_before=["human_review"], halt_after=["register_model", "reject_model"], inputs=inputs
    )


def test_train_review_resume(tmp_path, monkeypatch):
    """Trains to the review, resumes by app_id as a new process would, then approves."""
    monkeypatch.chdir(tmp_path)
    app = application(max_epochs=4, storage_dir=str(tmp_path))
    _run(app)
    assert app.get_next_action().name == "human_review"
    assert app.state["epoch"] == 4

    resumed = application(max_epochs=4, app_id=app.uid, storage_dir=str(tmp_path))
    assert resumed.state["epoch"] == 4
    _run(resumed, decision="continue", extra_epochs=2, learning_rate=0.01)
    assert resumed.state["epoch"] > 4
    assert joblib.load(resumed.state["latest_checkpoint"]).eta0 == 0.01
    assert resumed.get_next_action().name == "human_review"

    _run(resumed, decision="approve")
    assert os.path.exists(resumed.state["final_model"])
    best = resumed.state["best_epoch"]
    assert resumed.state["best_checkpoint"].endswith(f"epoch_{best}.joblib")
    assert resumed.state["val_scores"][best - 1] == resumed.state["best_score"]
    assert resumed.get_next_action() is None

    rejected = application(max_epochs=2, storage_dir=str(tmp_path))
    _run(rejected)
    _run(rejected, decision="reject")
    assert rejected.state["final_model"] is None
    assert rejected.state["checkpoint_dir"] != resumed.state["checkpoint_dir"]
