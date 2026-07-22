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

# Langfuse + Burr

This shows how to trace a Burr application to [Langfuse](https://langfuse.com)
using the `LangfuseBridge` hook.

What gets logged:

1. One Langfuse **trace** per application execution call (`run`/`step`/`iterate`/`stream_result`/...)
2. One **span** per step, with the action's inputs/read state as observation input and
   its result/written state as observation output
3. One **span** per span opened through Burr's tracing API (`__tracer`)
4. Attributes logged via `__tracer.log_attribute(s)` as observation **metadata**
5. Burr's `app_id` maps to the Langfuse **session** and `partition_key` to the
   Langfuse **user** (both overridable)

If you also install an OpenTelemetry LLM instrumentor (e.g.
`opentelemetry-instrumentation-openai`), LLM calls show up as generations nested
inside the corresponding Burr steps, with prompts/completions/token usage.

## Running

```bash
pip install "apache-burr[langfuse]" openai opentelemetry-instrumentation-openai

export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"  # or your self-hosted URL
export OPENAI_API_KEY="sk-..."

python application.py
```

Then open your Langfuse project -- you will see one trace per `.run()` call, with
the step spans, tracer spans, and (if instrumented) OpenAI generations nested inside.

See [application.py](./application.py) for the full code, and the
[integration docs](https://burr.apache.org/reference/integrations/langfuse/) for
configuration options (custom session/user IDs, disabling state capture, passing
your own `Langfuse` client).

## Note on langfuse v4+

Langfuse SDK v4+ only exports LLM-relevant spans by default. `LangfuseBridge`
handles this automatically when it constructs the client. If you construct the
`Langfuse` client yourself, pass the provided filter:

```python
from langfuse import Langfuse
from burr.integrations.langfuse import LangfuseBridge, burr_span_export_filter

client = Langfuse(should_export_span=burr_span_export_filter)
bridge = LangfuseBridge(langfuse_client=client)
```
