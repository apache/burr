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
This module demonstrates the Hamilton plugin that Burr has.
It is equivalent to the telephone example, but the way actions
are specified are different. Specifically it uses Burr's Hamilton
plugin to provide some syntactic sugar for defining actions that run
Hamilton DAGs.
"""

import os
import uuid

import requests
from hamilton import dataflows, driver

from burr.core import Action, ApplicationBuilder, State, default, expr
from burr.core.action import action
from burr.integrations import hamilton
from burr.lifecycle import PostRunStepHook

caption_images = dataflows.import_module("caption_images", "elijahbenizzy")
generate_images = dataflows.import_module("generate_images", "elijahbenizzy")


class ImageSaverHook(PostRunStepHook):
    """Class to save images to a directory."""

    def __init__(self, save_dir: str = "saved_images"):
        self.save_dir = save_dir
        self.run_id = str(uuid.uuid4())[0:8]
        self.path = os.path.join(self.save_dir, self.run_id)
        if not os.path.exists(self.path):
            os.makedirs(self.path)

    def post_run_step(self, *, state: "State", action: "Action", **future_kwargs):
        """Pulls the image URL from the state and saves it to the save directory."""
        if action.name == "generate":
            image_url = state["current_image_location"]
            image_name = "image_" + str(state["__SEQUENCE_ID"]) + ".png"
            with open(os.path.join(self.path, image_name), "wb") as f:
                f.write(requests.get(image_url).content)
                print(f"Saved image to {self.path}/{image_name}")


# instantiate hamilton drivers and then bind them to the actions.
caption_image_driver = (
    driver.Builder().with_config({"include_embeddings": True}).with_modules(caption_images).build()
)
generate_image_driver = driver.Builder().with_config({}).with_modules(generate_images).build()

caption = hamilton.Hamilton(
    inputs={"image_url": hamilton.from_state("current_image_location")},
    outputs={
        "generated_caption": hamilton.update_state("current_image_caption"),
        "image_url": hamilton.append_state("image_location_history"),
    },
    driver=caption_image_driver,
)
analysis = hamilton.Hamilton(
    inputs={
        "image_url": hamilton.from_state("current_image_location"),
        "generated_caption": hamilton.from_state("current_image_caption"),
    },
    outputs={
        "metadata": hamilton.append_state("caption_analysis"),
    },
    driver=caption_image_driver,
)
generate = hamilton.Hamilton(
    inputs={"image_generation_prompt": hamilton.from_state("current_image_caption")},
    outputs={
        "generated_image": hamilton.update_state("current_image_location"),
        "image_generation_prompt": hamilton.append_state("image_caption_history"),
    },
    driver=generate_image_driver,
)


@action(reads=["image_location_history", "image_caption_history", "caption_analysis"], writes=[])
def terminal_step(state: State) -> tuple[dict, State]:
    result = {
        "image_location_history": state["image_location_history"],
        "image_caption_history": state["image_caption_history"],
        "caption_analysis": state["caption_analysis"],
    }
    # Could save everything to S3 here.
    return result, state


def hamilton_action_main(
    max_iterations: int = 5, starting_image_location: str = "statemachine.png"
):
    """This shows how to use the Hamilton syntactic wrapper for the nodes."""
    app = (
        ApplicationBuilder()
        .with_state(
            current_image_location=starting_image_location,
            current_image_caption="",
            image_location_history=[],
            image_caption_history=[],
            caption_analysis=[],
        )
        .with_actions(
            caption=caption,
            analysis=analysis,
            generate=generate,
            terminal=terminal_step,
        )
        .with_transitions(
            ("caption", "terminal", expr(f"len(image_caption_history) == {max_iterations}")),
            ("caption", "analysis", default),
            ("analysis", "generate", default),
            ("generate", "caption", default),
        )
        .with_entrypoint("caption")
        .with_hooks(ImageSaverHook())
        .with_tracker(project="image-telephone")
        .build()
    )
    return app


if __name__ == "__main__":
    import random

    coin_flip = random.choice([True, False])
    app = hamilton_action_main()
    app.visualize(output_file_path="statemachine", include_conditions=True, view=True, format="png")
    if coin_flip:
        _last_action, _result, _state = app.run(halt_after=["terminal"])
    else:
        # alternate way to run:
        while True:
            _action, _result, _state = app.step()
            print("action=====\n", _action)
            print("result=====\n", _result)
            print("state======\n", _state)
            if _action.name == "terminal":
                break
