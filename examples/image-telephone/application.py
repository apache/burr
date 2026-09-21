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
This module demonstrates a telephone application
using Burr that:
 - captions an image
 - creates caption embeddings (for analysis)
 - creates a new image based on the created caption

We use pre-defined Hamilton DAGs to perform the
image captioning and image generation tasks. Unlike other frameworks
Hamilton doesn't hide the contents of the defined DAG from the user.
You can easily introspect, and modify the code as needed.

The Hamilton DAGs used in this example can be found here:

  - https://hub.dagworks.io/docs/Users/elijahbenizzy/caption_images/
  - https://hub.dagworks.io/docs/Users/elijahbenizzy/generate_images/
"""
import os
import uuid

import requests
from hamilton import dataflows, driver

from burr.core import Action, ApplicationBuilder, State, default, expr
from burr.core.action import action
from burr.lifecycle import PostRunStepHook

IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30

# import hamilton modules that define the DAGs for image captioning and image generation
caption_images = dataflows.import_module("caption_images", "elijahbenizzy")
generate_images = dataflows.import_module("generate_images", "elijahbenizzy")


class ImageSaverHook(PostRunStepHook):
    """Class to save images to a directory.
    This is an example of a custom way to interact indirectly.

    This is one way you could save to S3 by writing something like this.
    """

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
                response = requests.get(
                    image_url, timeout=IMAGE_DOWNLOAD_TIMEOUT_SECONDS
                )
                response.raise_for_status()
                f.write(response.content)
                print(f"Saved image to {self.path}/{image_name}")


@action(
    reads=["current_image_location"],
    writes=["current_image_caption", "image_location_history"],
)
def image_caption(state: State, caption_image_driver: driver.Driver) -> tuple[dict, State]:
    """Action to caption an image.
    This delegates to the Hamilton DAG for image captioning.
    For more details go here: https://hub.dagworks.io/docs/Users/elijahbenizzy/caption_images/.
    """
    current_image = state["current_image_location"]
    result = caption_image_driver.execute(
        ["generated_caption"], inputs={"image_url": current_image}
    )
    updates = {
        "current_image_caption": result["generated_caption"],
    }
    # You could save to S3 here
    return result, state.update(**updates).append(image_location_history=current_image)


@action(
    reads=["current_image_caption"],
    writes=["caption_analysis"],
)
def caption_embeddings(state: State, caption_image_driver: driver.Driver) -> tuple[dict, State]:
    """Action to analyze the caption and create embeddings for analysis.

    This delegates to the Hamilton DAG for getting embeddings for the caption.
    For more details go here: https://hub.dagworks.io/docs/Users/elijahbenizzy/caption_images/.

    This uses the overrides functionality to use the result of the prior Hamilton DAG run
    to avoid re-computation.
    """
    result = caption_image_driver.execute(
        ["metadata"],
        inputs={"image_url": state["current_image_location"]},
        overrides={"generated_caption": state["current_image_caption"]},
    )
    # You could save to S3 here
    return result, state.append(caption_analysis=result["metadata"])


@action(
    reads=["current_image_caption"],
    writes=["current_image_location", "image_caption_history"],
)
def image_generation(state: State, generate_image_driver: driver.Driver) -> tuple[dict, State]:
    """Action to create an image.

    This delegates to the Hamilton DAG for image generation.
    For more details go here: https://hub.dagworks.io/docs/Users/elijahbenizzy/generate_images/.
    """
    current_caption = state["current_image_caption"]
    result = generate_image_driver.execute(
        ["generated_image"], inputs={"image_generation_prompt": current_caption}
    )
    updates = {
        "current_image_location": result["generated_image"],
    }
    # You could save to S3 here
    return result, state.update(**updates).append(image_caption_history=current_caption)


@action(reads=["image_location_history", "image_caption_history", "caption_analysis"], writes=[])
def terminal_step(state: State) -> tuple[dict, State]:
    """This is a terminal step. We can do any final processing here."""
    result = {
        "image_location_history": state["image_location_history"],
        "image_caption_history": state["image_caption_history"],
        "caption_analysis": state["caption_analysis"],
    }
    # Could save everything to S3 here.
    return result, state


def build_application(
    starting_image: str = "statemachine.png", number_of_images_to_caption: int = 4
):
    """This builds the Burr application and returns it.

    :param starting_image: the starting image to use
    :param number_of_images_to_caption: the number of iterations to go through
    :return: the built application
    """
    # instantiate hamilton drivers and then bind them to the actions.
    caption_image_driver = (
        driver.Builder()
        .with_config({"include_embeddings": True})
        .with_modules(caption_images)
        .build()
    )
    generate_image_driver = driver.Builder().with_config({}).with_modules(generate_images).build()
    app = (
        ApplicationBuilder()
        .with_state(
            current_image_location=starting_image,
            current_image_caption="",
            image_location_history=[],
            image_caption_history=[],
            caption_analysis=[],
        )
        .with_actions(
            caption=image_caption.bind(caption_image_driver=caption_image_driver),
            analyze=caption_embeddings.bind(caption_image_driver=caption_image_driver),
            generate=image_generation.bind(generate_image_driver=generate_image_driver),
            terminal=terminal_step,
        )
        .with_transitions(
            ("caption", "analyze", default),
            (
                "analyze",
                "terminal",
                expr(f"len(image_caption_history) == {number_of_images_to_caption}"),
            ),
            ("analyze", "generate", default),
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
    # app = build_application("path/to/my/image.png")
    app = build_application()
    app.visualize(output_file_path="statemachine", include_conditions=True, view=True, format="png")
    if coin_flip:
        _last_action, _result, _state = app.run(halt_after=["terminal"])
        # save to S3 / download images etc.
    else:
        # alternate way to run:
        while True:
            _action, _result, _state = app.step()
            print("action=====\n", _action)
            print("result=====\n", _result)
            # you could save to S3 / download images etc. here.
            if _action.name == "terminal":
                break
    print(_state)
