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

# Burr with an OpenAI API -compatible server

Connect to your Burr agent using your favorite open-source tooling! This includes:
- Local chat frontends such as [Ollama](https://github.com/ollama/ollama/blob/4ec7445a6f678b6efc773bb9fa886d7c9b075577/docs/openai.md#supported-request-fields), [Jan](https://jan.ai/docs/remote-models/generic-openai), [text-generation-webui](https://github.com/oobabooga/text-generation-webui/wiki/12-%E2%80%90-OpenAI-API#openai-compatible-api)
- Code assistants like [Continue](https://docs.continue.dev/reference/Model%20Providers/openai#openai-compatible-servers--apis), [llm-vscode](https://github.com/huggingface/llm-vscode?tab=readme-ov-file#backend) by HuggingFace
- Other productivity tools like the [llm](https://llm.datasette.io/en/stable/other-models.html#openai-compatible-models) command line tool

## Context

The [OpenAI API](https://platform.openai.com/docs/overview) allows you to send HTTP requests to large language models (LLMs) such as GPT-4. When interacting with ChatGPT, we're using the API endpoint `v1/chat/completions`, but there are many others:

- `v1/embeddings` get an embedding, i.e., a vector representation of the input text
- `v1/audio/transcriptions` uses the Whisper model to convert audio to text
- `v1/audio/speech` convert text to audio
- `v1/images/generations` uses DALL-E to generate images from a text prompt

Other LLM providers (e.g., Cohere, HuggingFace) have their own set of endpoints. But given the influence of OpenAI, many open-source tools include a "OpenAI API-compatible" version. By creating a server that implements endpoints respecting the request and response formats, we can directly interface with them!

## OpenAI API compatible Burr application
This example contains a very simple Burr application (`application.py`) and a FastAPI server to deploy this agent behind the OpenAI `v1/chat/completions` endpoint. After starting the server with `server.py`, you should be able to interact with it from your other tools ([Jan](https://jan.ai/docs) is easy and quick to install across platforms).

To run, execute:

```bash
python server.py
```

If you're using Jan, untoggle the `Stream` parameter (we will add an example of a stream-compatible application later).


![](statemachine.png)

This is great because we can quickly integrate our Burr Agent with high-quality UIs and tools. Simulaneously, you gain Burr's observability, logging, and persistence across your applications.

Most tools save state "in the frontend" because they don't have access to the official OpenAI backend. This means that each of your LLM applications are isolated. By using Burr and persisting state (e.g., chat history) on the backend, this means you can share and resume a conversation between your LLM frontend, CLI, or coding assistant!

## Resources
There are multiple implementations of OpenAI API-compatible servers. Here are some notable examples:

- [cortex](https://github.com/janhq/cortex.cpp)
- [llama-cpp-python](https://github.com/abetlen/llama-cpp-python/blob/main/llama_cpp/server/app.py)
- [FastChat](https://github.com/lm-sys/FastChat/blob/main/fastchat/serve/openai_api_server.py)
- [text-generation-webui](https://github.com/oobabooga/text-generation-webui/blob/abe5ddc8833206381c43b002e95788d4cca0893a/extensions/openai/script.py)
