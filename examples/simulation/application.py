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
This module contains a stubbed out structure for one way of doing a simulation
 for forecasting purposes.

For more sophisticated forecasts where prediction of one timestep
depends on the previous timestep, you need to forecast on a per-step basis. So
you're effectively simulating the future at each step. This is a simple example of
how you might structure such a simulation.
"""

from typing import Tuple

from burr.core import Application, ApplicationBuilder, State, expr
from burr.core.action import action


@action(reads=["data_path"], writes=["data"])
def prepare_data(state: State) -> Tuple[dict, State]:
    """This would pull the data, prepare it, and return it."""
    # pull data, prepare as necessary
    result = {"data": _process_data(state["data_path"])}
    return result, state.update(**result)


@action(reads=["data", "simulation_start"], writes=["model"])
def build_model(state: State) -> Tuple[dict, State]:
    """This would fit the model on data before the simulation start date."""
    training_data = state["data"]
    model = _fit_model(training_data, upto=state["simulation_start"])
    result = {"model": model}
    return result, state.update(**result)


@action(
    reads=["simulation_start", "simulation_end", "model", "data", "current_timestep"],
    writes=["data", "current_timestep"],
)
def forecast(state: State) -> Tuple[dict, State]:
    """This action forecasts the next timestep in the simulation and appends it to data."""
    model = state["model"]
    data = state["data"]
    start_time = state["simulation_start"]
    current_time_step = state.get("current_timestep", start_time)
    next_timestep = _forecast_timestep(model, data, current_time_step)
    data = _update_data(data, next_timestep)
    result = {"data": data, "current_timestep": next_timestep}
    return result, state.update(**result)


@action(reads=["data"], writes=[])
def terminate(state: State) -> Tuple[dict, State]:
    """This is a terminal step that would save the forecast or do something else."""
    return {}, state


def application() -> Application:
    app = (
        ApplicationBuilder()
        .with_actions(prepare_data, build_model, forecast, terminate)
        .with_transitions(
            ("prepare_data", "build_model"),
            ("build_model", "forecast"),
            ("forecast", "forecast", expr("current_timestep<simulation_end")),
            ("forecast", "terminate", expr("current_timestep>=simulation_end")),
        )
        .with_state(
            data_path="SOME_PATH",
            simulation_start="some-value",
            simulation_end="some-end-value",
        )
        .with_entrypoint("prepare_data")
        .build()
    )
    return app


# --- stubbed out functions to fill out for the simulation
def _process_data(data_path: str) -> object:
    """This function would read and process data from a file."""
    return {}


def _fit_model(data: object, upto: str) -> object:
    """This function would fit a model on data upto a certain date."""
    return {}


def _forecast_timestep(model: object, data: object, current_timestep: str) -> object:
    """This function would forecast the next timestep in the simulation given the model and data."""
    return {}


def _update_data(data: object, next_timestep: object) -> object:
    """This function would update the data with the forecasted timestep."""
    return {}


if __name__ == "__main__":
    _app = application()
    _app.visualize(
        output_file_path="statemachine", include_conditions=True, view=True, format="png"
    )
    # you could run things like this:
    # last_action, result, state = _app.run(halt_after=["terminate"])
