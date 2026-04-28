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
from typing import Dict, Optional, TypedDict

import openai
from hamilton.function_modifiers import config

ChatContents = TypedDict("ChatContents", {"role": str, "content": str, "type": str})


def processed_prompt(prompt: str) -> dict:
    return {"role": "user", "content": prompt, "type": "text"}


@config.when(provider="openai")
def client() -> openai.Client:
    return openai.Client()


def text_model() -> str:
    return "gpt-4o-mini"


def image_model() -> str:
    return "dall-e-2"


def safe(prompt: str) -> bool:
    if "unsafe" in prompt:
        return False
    return True


def modes() -> Dict[str, str]:
    return {
        "answer_question": "text",
        "generate_image": "image",
        "generate_code": "code",
        "unknown": "text",
    }


def find_mode_prompt(prompt: str, modes: Dict[str, str]) -> str:
    return (
        f"You are a chatbot. You've been prompted this: {prompt}. "
        f"You have the capability of responding in the following modes: {', '.join(modes)}. "
        "Please respond with *only* a single word representing the mode that most accurately"
        " corresponds to the prompt. Fr instance, if the prompt is 'draw a picture of a cat', "
        "the mode would be 'generate_image'. If the prompt is 'what is the capital of France', the mode would be 'answer_question'."
        "If none of these modes apply, please respond with 'unknown'."
    )


def suggested_mode(find_mode_prompt: str, client: openai.Client, text_model: str) -> str:
    result = client.chat.completions.create(
        model=text_model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": find_mode_prompt},
        ],
    )
    content = result.choices[0].message.content
    return content


def mode(suggested_mode: str, modes: Dict[str, str]) -> str:
    # TODO -- use instructor!
    print(f"Mode: {suggested_mode}")
    lowercase = suggested_mode.lower()
    if lowercase not in modes:
        return "unknown"  # default to unknown
    return lowercase


def generated_text(chat_history: list[dict], text_model: str, client: openai.Client) -> str:
    chat_history_api_format = [
        {
            "role": chat["role"],
            "content": chat["content"],
        }
        for i, chat in enumerate(chat_history)
    ]
    result = client.chat.completions.create(
        model=text_model,
        messages=chat_history_api_format,
    )
    return result.choices[0].message.content


# def generated_text_error(generated_text) -> dict:
#     ...


def generated_image(prompt: str, image_model: str, client: openai.Client) -> str:
    result = client.images.generate(
        model=image_model, prompt=prompt, size="1024x1024", quality="standard", n=1
    )
    return result.data[0].url


def answered_question(chat_history: list[dict], text_model: str, client: openai.Client) -> str:
    chat_history = copy.deepcopy(chat_history)
    chat_history[-1][
        "content"
    ] = f"Please answer the following question: {chat_history[-1]['content']}"

    chat_history_api_format = [
        {
            "role": chat["role"],
            "content": chat["content"],
        }
        for i, chat in enumerate(chat_history)
    ]
    response = client.chat.completions.create(
        model=text_model,
        messages=chat_history_api_format,
    )
    return response.choices[0].message.content


def generated_code(chat_history: list[dict], text_model: str, client: openai.Client) -> str:
    chat_history = copy.deepcopy(chat_history)
    chat_history[-1][
        "content"
    ] = f"Please respond to the following with *only* code: {chat_history[-1]['content']}"

    chat_history_api_format = [
        {
            "role": chat["role"],
            "content": chat["content"],
        }
        for i, chat in enumerate(chat_history)
    ]
    response = client.chat.completions.create(
        model=text_model,
        messages=chat_history_api_format,
    )
    return response.choices[0].message.content


def prompt_for_more(modes: Dict[str, str]) -> str:
    return (
        f"I can't find a mode that applies to your input. Can you"
        f" please clarify? I support: {', '.join(modes)}."
    )


def processed_response(
    response: Optional[str], mode: str, modes: Dict[str, str], safe: bool
) -> ChatContents:
    if not safe:
        return {"role": "assistant", "content": "I'm sorry, I can't do that.", "type": "text"}
    return {"role": "assistant", "type": modes[mode], "content": response}


def processed_error(error: str) -> dict:
    return {"role": "assistant", "error": error, "type": "text"}
