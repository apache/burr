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
This is a sketch of an example of a machine learning training pipeline using Burr where you
want to do something dynamic like train a model for a variable number of iterations and then
pick the best model from each of the iterations based on some validation metric. E.g. hyperparameter search.

You could adjust this example to continue training a model until you reach a certain validation metric,
or hit a max number of iterations (or epochs), etc.

Note: this example uses the class based API to define the actions. You could also use the function+decorator API.
"""

import burr.core.application
from burr.core import Action, Condition, State, default


class ProcessDataAction(Action):
    @property
    def reads(self) -> list[str]:
        return ["data_path"]

    def run(self, state: State, **run_kwargs) -> dict:
        """This is where you would load and process your data.
        You can take in state and reference object fields.

        You need to return a dictionary of the results that `update()` will then use to update the state.
        """
        # load data, and run some feature engineering -- create the data sets
        # TODO: fill in
        return {"training_data": "SOME_OBJECT/PATH", "evaluation_data": "SOME_OBJECT/PATH"}

    @property
    def writes(self) -> list[str]:
        return ["training_data", "evaluation_data"]

    def update(self, result: dict, state: State) -> State:
        return state.update(
            training_data=result["training_data"], evaluation_data=result["evaluation_data"]
        )


class TrainModel(Action):
    @property
    def reads(self) -> list[str]:
        return ["training_data", "iterations"]

    def run(self, state: State, **run_kwargs) -> dict:
        """This is where you'd build the model and on each iteration do something different.
        E.g. hyperparameter search.
        """
        # train the model, i.e. run one "iteration" whatever that means for you.
        # TODO: fill in
        return {
            "model": "SOME_MODEL",
            "iterations": state["iterations"] + 1,
            "metrics": "SOME_METRICS",
        }

    @property
    def writes(self) -> list[str]:
        return ["models", "training_metrics", "iterations"]

    def update(self, result: dict, state: State) -> State:
        return state.update(
            iterations=result["iterations"],  # set current iteration value
        ).append(
            models=result["model"],  # append -- note this can get big if your model is big
            # so you'll want to overwrite but store the conditions, or log somewhere
            metrics=result["metrics"],  # append the metrics
        )


class ValidateModel(Action):
    @property
    def reads(self) -> list[str]:
        return ["models", "evaluation_data"]

    def run(self, state: State, **run_kwargs) -> dict:
        """Compute validation metrics using the model and evaluation data."""
        # TODO: fill in
        return {"validation_metrics": "SOME_METRICS"}

    @property
    def writes(self) -> list[str]:
        return ["validation_metrics"]

    def update(self, result: dict, state: State) -> State:
        return state.append(validation_metrics=result["validation_metrics"])


class BestModel(Action):
    @property
    def reads(self) -> list[str]:
        return ["validation_metrics", "models"]

    def run(self, state: State, **run_kwargs) -> dict:
        """Select the best model based on the validation metrics."""
        # TODO: fill in
        return {"best_model": "SOME_MODEL"}

    @property
    def writes(self) -> list[str]:
        return ["best_model"]

    def update(self, result: dict, state: State) -> State:
        return state.update(best_model=result["best_model"])


def application(iterations: int) -> burr.core.application.Application:
    return (
        burr.core.ApplicationBuilder()
        .with_state(
            data_path="data.csv",
            iterations=10,
            training_data=None,
            evaluation_data=None,
            models=[],
            training_metrics=[],
            validation_metrics=[],
            best_model=None,
        )
        .with_actions(
            process_data=ProcessDataAction(),
            train_model=TrainModel(),
            validate_model=ValidateModel(),
            best_model=BestModel(),
        )
        .with_transitions(
            ("process_data", "train_model", default),
            ("train_model", "validate_model", default),
            ("validate_model", "best_model", Condition.expr(f"iterations>{iterations}")),
            ("validate_model", "train_model", default),
        )
        .with_entrypoint("process_data")
        .build()
    )


if __name__ == "__main__":
    app = application(100)  # doing good data science is up to you...
    app.visualize(output_file_path="statemachine", include_conditions=True, view=True, format="png")
    # you could run things like this:
    # last_action, result, state = app.run(halt_after=["best_model"])
