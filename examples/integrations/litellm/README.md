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

# LiteLLM integration

This example shows how to use Burr's LiteLLM helpers:

- `LiteLLMAction` - single-step completion call via the LiteLLM AI gateway.
- `LiteLLMStreamingAction` - streaming completion with `Application.stream_result`.

LiteLLM provides a unified interface to 100+ LLM providers (OpenAI, Anthropic, Google, Azure, AWS Bedrock, Ollama, Groq, Mistral, and more).

## Setup

1. Install dependencies (from the repo root):

   ```bash
   pip install -r examples/integrations/litellm/requirements.txt
   ```

2. Set the API key for the provider you want to use. For example:

   ```bash
   export OPENAI_API_KEY="sk-..."       # for OpenAI models
   export ANTHROPIC_API_KEY="sk-ant-..."  # for Anthropic models
   ```

3. Optionally override the default model with `LITELLM_MODEL` (default is `openai/gpt-4o-mini`):

   ```bash
   export LITELLM_MODEL="anthropic/claude-sonnet-4-6"
   ```

## Run

```bash
python examples/integrations/litellm/application.py
```

The script runs a non-streaming call, then a streaming call, using two small Burr graphs defined in `application()` and `streaming_application()`.
