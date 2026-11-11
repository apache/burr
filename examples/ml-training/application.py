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
Epoch-based ML training with a human-in-the-loop sign-off, modeled as a Burr state machine.

- ``train_epoch`` runs a single epoch and checkpoints the model to disk.
- ``evaluate`` scores the checkpoint and tracks the best one.
- When to stop training is a *transition condition*, not part of the training code.
- ``human_review`` pauses the application (``halt_before``) until a person decides to
  approve the best model, train for more epochs, or reject it.

State only holds metrics and checkpoint *paths* (not models or data), so it stays small
and serializable, and the persister can resume the run from any step, e.g. after a human
has come back with their decision.
"""

import functools
import logging
import os
import shutil
import sys
import uuid
from typing import Optional

import joblib
import numpy as np
from sklearn.datasets import load_digits
from sklearn.linear_model import SGDClassifier
from sklearn.model_selection import train_test_split

import burr.core
from burr.core import Application, State, default, expr, when
from burr.core.action import action
from burr.core.persistence import SQLitePersister

logger = logging.getLogger(__name__)


@functools.lru_cache
def load_data():
    """Small built-in dataset, so the example runs offline in seconds. Swap in your own."""
    X, y = load_digits(return_X_y=True)
    return train_test_split(X / 16.0, y, test_size=0.25, random_state=42)


@action(
    reads=["epoch", "learning_rate", "checkpoint_dir", "latest_checkpoint"],
    writes=["epoch", "latest_checkpoint"],
)
def train_epoch(state: State) -> State:
    """Runs one epoch, starting from the latest checkpoint, and saves a new checkpoint."""
    X_train, _, y_train, _ = load_data()
    if state["latest_checkpoint"]:
        model = joblib.load(state["latest_checkpoint"])
    else:
        model = SGDClassifier(loss="log_loss", learning_rate="constant", random_state=0)
    # set every epoch, because the reviewer can change it
    model.set_params(eta0=state["learning_rate"])
    epoch = state["epoch"] + 1
    order = np.random.default_rng(epoch).permutation(len(X_train))
    model.partial_fit(X_train[order], y_train[order], classes=np.unique(y_train))

    os.makedirs(state["checkpoint_dir"], exist_ok=True)
    checkpoint = os.path.join(state["checkpoint_dir"], f"epoch_{epoch}.joblib")
    joblib.dump(model, checkpoint)
    return state.update(epoch=epoch, latest_checkpoint=checkpoint)


@action(
    reads=["epoch", "latest_checkpoint", "val_scores", "best_score", "epochs_since_best"],
    writes=["val_scores", "best_score", "best_epoch", "best_checkpoint", "epochs_since_best"],
)
def evaluate(state: State) -> State:
    """Scores the latest checkpoint on the validation set and tracks the best one so far."""
    _, X_val, _, y_val = load_data()
    score = float(joblib.load(state["latest_checkpoint"]).score(X_val, y_val))
    logger.info(f"epoch {state['epoch']}: val accuracy = {score:.4f}")
    state = state.append(val_scores=score)
    if score > state["best_score"]:
        return state.update(
            best_score=score,
            best_epoch=state["epoch"],
            best_checkpoint=state["latest_checkpoint"],
            epochs_since_best=0,
        )
    return state.update(epochs_since_best=state["epochs_since_best"] + 1)


@action(
    reads=["epoch", "learning_rate"],
    writes=["decision", "max_epochs", "epochs_since_best", "learning_rate"],
)
def human_review(
    state: State, decision: str, extra_epochs: int = 5, learning_rate: Optional[float] = None
) -> State:
    """The app halts before this action. A reviewer passes in their decision as an input:
    ``approve``, ``continue`` (train ``extra_epochs`` more), or ``reject``.
    With ``continue``, the reviewer can also pass a new ``learning_rate``."""
    if decision not in ("approve", "continue", "reject"):
        raise ValueError(f"decision must be approve, continue or reject, got {decision!r}")
    if learning_rate is not None and learning_rate <= 0:
        raise ValueError(f"learning_rate must be positive, got {learning_rate!r}")
    if decision == "continue":
        return state.update(
            decision=decision,
            max_epochs=state["epoch"] + extra_epochs,
            epochs_since_best=0,
            learning_rate=learning_rate or state["learning_rate"],
        )
    return state.update(decision=decision)


@action(reads=["best_checkpoint", "checkpoint_dir"], writes=["final_model"])
def register_model(state: State) -> State:
    """Promote the best checkpoint. In practice: push to a model registry, deploy, etc."""
    final_model = os.path.join(state["checkpoint_dir"], "model.joblib")
    shutil.copyfile(state["best_checkpoint"], final_model)
    return state.update(final_model=final_model)


@action(reads=[], writes=["final_model"])
def reject_model(state: State) -> State:
    return state.update(final_model=None)


def review_summary(state: State) -> str:
    """What the reviewer sees before they decide."""
    stalled = state["epochs_since_best"] >= state["patience"]
    reason = f"no new best for {state['patience']} epochs" if stalled else "reached max_epochs"
    recent = ", ".join(f"{s:.3f}" for s in state["val_scores"][-5:])
    return (
        f"Trained {state['epoch']} epochs. Stopped: {reason}.\n"
        f"Best validation accuracy: {state['best_score']:.4f} "
        f"at epoch {state['best_epoch']} of {state['epoch']}\n"
        f"Checkpoint: {state['best_checkpoint']}\n"
        f"Last 5 epochs: {recent}\n"
        f"Learning rate: {state['learning_rate']}"
    )


def application(
    max_epochs: int = 20,
    patience: int = 3,
    learning_rate: float = 0.001,
    checkpoint_dir: str = "checkpoints",
    app_id: Optional[str] = None,
    partition_key: str = "demo-user",
    storage_dir: Optional[str] = "~/.burr",
) -> Application:
    # known up front so each run gets its own checkpoint directory
    app_id = app_id or str(uuid.uuid4())
    persister = SQLitePersister("ml_training.db", "ml_training")
    persister.initialize()
    return (
        burr.core.ApplicationBuilder()
        .with_actions(
            train_epoch=train_epoch,
            evaluate=evaluate,
            human_review=human_review,
            register_model=register_model,
            reject_model=reject_model,
        )
        .with_transitions(
            ("train_epoch", "evaluate", default),
            # stopping rule lives here, decoupled from training; swap it without touching actions
            (
                "evaluate",
                "human_review",
                expr("epochs_since_best >= patience or epoch >= max_epochs"),
            ),
            ("evaluate", "train_epoch", default),
            ("human_review", "train_epoch", when(decision="continue")),
            ("human_review", "register_model", when(decision="approve")),
            ("human_review", "reject_model", when(decision="reject")),
        )
        .with_identifiers(app_id=app_id, partition_key=partition_key)
        .initialize_from(
            persister,
            resume_at_next_action=True,
            default_state={
                "epoch": 0,
                "max_epochs": max_epochs,
                "patience": patience,
                "learning_rate": learning_rate,
                "checkpoint_dir": os.path.join(checkpoint_dir, app_id),
                "latest_checkpoint": None,
                "best_checkpoint": None,
                "best_score": 0.0,
                "best_epoch": 0,
                "epochs_since_best": 0,
                "val_scores": [],
            },
            default_entrypoint="train_epoch",
        )
        .with_state_persister(persister)
        .with_tracker(project="demo_ml_training", params={"storage_dir": storage_dir})
        .build()
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # pass an app_id to resume a run, e.g. after the reviewer comes back
    app = application(app_id=sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"app_id: {app.uid} (run `python application.py {app.uid}` to resume)")
    while (next_action := app.get_next_action()) is not None:
        inputs = {}
        if next_action.name == "human_review":
            # in production the process exits here and is resumed by app_id once a human replies
            print("\n" + review_summary(app.state))
            inputs = {"decision": input("approve / continue / reject? ").strip()}
            if inputs["decision"] == "continue":
                rate = input(f"learning rate [{app.state['learning_rate']}]: ").strip()
                if rate:
                    inputs["learning_rate"] = float(rate)
        app.run(
            halt_before=["human_review"],
            halt_after=["register_model", "reject_model"],
            inputs=inputs,
        )
    print(f"Done. Final model: {app.state['final_model']}")
    app.visualize(
        output_file_path="statemachine.png", include_conditions=True, view=False, format="png"
    )
