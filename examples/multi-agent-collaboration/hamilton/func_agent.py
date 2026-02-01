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
Hamilton module that defines the pipeline for
hitting an LLM model and asking it what to do.
"""

import inspect
import json
from typing import Callable

import openai
from langchain_core.utils.function_calling import convert_to_openai_function


def llm_client() -> openai.OpenAI:
    return openai.OpenAI()


def tool_names(tool_function_specs: list[dict]) -> list[str]:
    """Get the names of the tools from the tool function specs."""
    return [tool["function"]["name"] for tool in tool_function_specs]


def _langchain_tool_spec(tool: Callable) -> dict:
    """Converts a tool to a langchain tool spec."""
    t = convert_to_openai_function(tool)
    # print(t)
    return t


def _tool_function_spec(tool: Callable) -> dict:
    """Converts a python function into a specification for function calling.

    This is a little hacky. But it works.

    It takes a function, introspects it, and returns a spec.

    :param tool:
    :return:
    """
    # TODO: maybe just get people to wrap any external tool in a function
    # to make it clear what is going on.
    if hasattr(tool, "name") and hasattr(tool, "description") and hasattr(tool, "args_schema"):
        return {"type": "function", "function": _langchain_tool_spec(tool)}
    func_sig = inspect.signature(tool)
    name = tool.__name__
    docstring = inspect.getdoc(tool)
    doc_lines = docstring.split("\n") if docstring else []
    description = ""
    for line in doc_lines:
        stripped = line.strip()
        if stripped.startswith(":"):
            # we have reached the end of the description
            break
        description += stripped + "\n"
    description = description.strip()
    param_descriptions = {}
    for line in doc_lines:
        stripped = line.strip()
        if stripped.startswith(":param"):
            parts = stripped.split(" ", 2)
            param_name = parts[1].strip(":")
            param_description = parts[2]
            param_descriptions[param_name] = param_description
    parameters = func_sig.parameters
    func_parameters = {}
    required = []
    for param_name, param in parameters.items():
        param_type = param.annotation
        param_description = param_descriptions.get(param_name, "")
        if param_type == str:
            param_type = "string"
        elif param_type == int:
            param_type = "integer"
        elif param_type == float:
            param_type = "float"
        else:
            raise ValueError(f"Unsupported parameter type: {param_type}")
        func_parameters[param_name] = {
            "type": param_type,
            "description": param_description,
        }
        if param.default == inspect.Parameter.empty:
            required.append(param_name)
        else:
            func_parameters[param_name]["description"] += f" Defaults to {param.default}."

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": func_parameters,
                "required": required,
            },
        },
    }


def tool_function_specs(tools: list[Callable]) -> list[dict]:
    """Converts a list of tools into a list of tool function specs."""
    return [_tool_function_spec(tool) for tool in tools]


def base_system_prompt(tool_names: list[str], system_message: str) -> str:
    """Creates the base system prompt for the pipeline."""
    return (
        "You are a helpful AI assistant, collaborating with other assistants."
        " Use the provided tools to progress towards answering the question."
        " If you are unable to fully answer, that's OK, another assistant with different tools "
        " will help where you left off. Execute what you can to make progress.\n\n"
        "If you or any of the other assistants have the final answer or deliverable,"
        " prefix your response with 'FINAL ANSWER' so the team knows to stop.\n\n"
        f"You have access to the following tools: {tool_names}.\n{system_message}\n\n"
        "Remember to prefix your response with 'FINAL ANSWER' if you or another assistant "
        "thinks the task is complete; assume the user can visualize the result."
    )


def message_history(base_system_prompt: str, user_query: str, messages: list[dict]) -> list[dict]:
    """Creates the message history for the LLM model.

    :param base_system_prompt:
    :param user_query:
    :param messages:
    :return:
    """
    base = [
        {"role": "system", "content": base_system_prompt},
        {"role": "user", "content": user_query},
    ]
    sanitized_messages = []
    for message in messages:
        message_copy = message.copy()
        if not isinstance(message_copy["content"], str) and message_copy["content"] is not None:
            message_copy["content"] = (
                json.dumps(message_copy["content"]) if message_copy["content"] else None
            )
        sanitized_messages.append(message_copy)
    return base + sanitized_messages


def llm_function_response(
    message_history: list[dict],
    tool_function_specs: list[dict],
    llm_client: openai.OpenAI,
) -> openai.types.chat.chat_completion.ChatCompletion:
    """Creates the function response from the LLM model for the given prompt & functions.

    :param message_history:
    :param tool_function_specs:
    :param llm_client:
    :return:
    """
    response = llm_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=message_history,
        tools=tool_function_specs,
        tool_choice="auto",
    )
    return response


def llm_function_message(
    llm_function_response: openai.types.chat.chat_completion.ChatCompletion,
) -> dict:
    """Parses the LLM response message. Does extra parsing for tool invocations."""
    response_message = llm_function_response.choices[0].message
    if response_message.tool_calls:
        return {
            "role": response_message.role,
            "content": None,
            "tool_calls": [
                {
                    "id": t.id,
                    "type": "function",
                    "function": {"name": t.function.name, "arguments": t.function.arguments},
                }
                for t in response_message.tool_calls
            ],
        }
    return {
        "role": "assistant",
        "content": response_message.content,
    }


def parsed_tool_calls(
    llm_function_response: openai.types.chat.chat_completion.ChatCompletion,
) -> list[dict]:
    """Parses the tool calls from the LLM response message.

    :param llm_function_response: The response from the LLM model.
    :return: The parsed tool calls.
    """
    response_message = llm_function_response.choices[0].message
    tool_calls = response_message.tool_calls
    parsed_calls = []
    if tool_calls:
        for tool_call in tool_calls:
            func_call = {
                "id": tool_call.id,
                "function_name": tool_call.function.name,
                "function_args": tool_call.function.arguments,
            }
            parsed_calls.append(func_call)
    return parsed_calls


def executed_tool_calls(
    parsed_tool_calls: list[dict], tools: list[Callable]
) -> list[tuple[str, dict]]:
    """Executes the parsed tool calls.

    :param parsed_tool_calls: The parsed tool calls.
    :param tools: The tools to execute.
    :return: The results of the tool calls.
    """
    results = []
    for tool_call in parsed_tool_calls:
        tool_name = tool_call["function_name"]
        tool_args = tool_call["function_args"]
        tool_found = False
        for tool in tools:
            name = getattr(tool, "name", None)
            if name is None:
                name = tool.__name__
            if name == tool_name:
                tool_found = True
                kwargs = json.loads(tool_args)
                if hasattr(tool, "_run"):
                    result = tool._run(**kwargs)
                else:
                    result = tool(**kwargs)
                results.append(
                    (
                        tool_name,
                        {
                            "tool_call_id": tool_call["id"],
                            "role": "tool",
                            "name": tool_name,
                            "content": result,  # note: might not be a string.
                        },
                    )
                )
        if not tool_found:
            raise ValueError(f"Tool {tool_name} not found.")
    # TODO: do we add a sentinel if no tool call was required.
    return results


def _get_current_weather(location: str, unit: str = "fahrenheit") -> str:
    """Get the current weather in a given location

    Dummy function to simulate a weather API call.

    :param location: the location to get the weather for.
    :param unit: the unit of temperature to return. Celsius or Fahrenheit.
    :return: JSON string with the location and temperature, and unit.
    """
    if "tokyo" in location.lower():
        return json.dumps({"location": "Tokyo", "temperature": "10", "unit": unit})
    elif "san francisco" in location.lower():
        return json.dumps({"location": "San Francisco", "temperature": "72", "unit": unit})
    elif "paris" in location.lower():
        return json.dumps({"location": "Paris", "temperature": "22", "unit": unit})
    else:
        return json.dumps({"location": location, "temperature": "unknown"})


if __name__ == "__main__":
    # some code to test a few things.
    jspec = _tool_function_spec(_get_current_weather)
    import pprint

    pprint.pprint(jspec)

    import __main__
    from hamilton import driver

    dr = driver.Builder().with_modules(__main__).build()
    result = dr.execute(
        ["executed_tool_calls"],
        inputs={
            "tools": [_get_current_weather],
            "system_message": "You are an accurate weather forecaster.",
            "user_query": "What is the weather in Tokyo, Japan? Use celsius.",
            "messages": [],
        },
    )
    print(result)
