<!--
     Licensed to the Apache Software Foundation (ASF) under one
     or more contributor license agreements.  See the NOTICE file
     distributed with this work for additional information
     regarding copyright ownership.  The ASF licenses this file
     to you under the Apache License, Version 2.0 (the
     "License"); you may not use this file except in compliance
     with the License.  You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

     Unless required by applicable law or agreed to in writing,
     software distributed under the License is distributed on an
     "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
     KIND, either express or implied.  See the License for the
     specific language governing permissions and limitations
     under the License.
-->

# A Burr agent backed by OrcaRouter

This example shows how to build a small stateful chat agent with Burr and have it
talk to [OrcaRouter](https://www.orcarouter.ai) — a gateway that provides an
OpenAI-compatible API for a wide range of models through a single endpoint.

It also runs gateway-level, zero-trust security for AI agents on the same endpoint —
screening every prompt/response and governing every tool call on a default-deny basis,
with no application code changes.

OrcaRouter exposes the OpenAI-compatible API at:

```
https://api.orcarouter.ai/v1
```

Because the API is OpenAI-compatible, we can use the `openai` Python client and
simply point `base_url` at OrcaRouter. The `orcarouter/auto` model alias routes to a
default capable model.

## Setup

```bash
pip install "apache-burr[start]" openai
```

Then set your OrcaRouter API key:

```bash
export ORCAROUTER_API_KEY="your-orca-key"
```

Optionally override the endpoint or model:

```bash
export ORCAROUTER_BASE_URL="https://api.orcarouter.ai/v1"   # default
export ORCAROUTER_MODEL="orcarouter/auto"                    # default
```

## Running

Run the example from the `examples/orcarouter-agent` directory:

```bash
python application.py "What is Apache Burr?"
```

This will build the state machine (`statemachine.png`), send your prompt to
OrcaRouter, and print the reply. The agent loops between a `human_input` action and
an `ai_response` action, accumulating a `chat_history` in state.

You can also open `notebook.ipynb` and run the cells step by step.

## How it works

- `human_input` reads the prompt and appends it to the chat history in state.
- `ai_response` sends the full chat history to
  `https://api.orcarouter.ai/v1/chat/completions` using the `orcarouter/auto` model
  and stores the reply back in state.

The state machine is small on purpose — swap in more actions (tool calls, human
approval, sub-agents) to build a full agent on top of OrcaRouter.
