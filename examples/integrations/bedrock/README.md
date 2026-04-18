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

# Amazon Bedrock integration

This example shows how to use Burr’s Bedrock helpers:

- `BedrockAction` — single-step [Converse](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html) call.
- `BedrockStreamingAction` — streaming [ConverseStream](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseStream.html) with `Application.stream_result`.

## Setup

1. Install dependencies (from the repo root):

   ```bash
   pip install -r examples/integrations/bedrock/requirements.txt
   ```

2. Configure AWS credentials and a region where Bedrock is available (for example `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_DEFAULT_REGION`).

3. Ensure your account can invoke the model you choose. Override the default model with `BEDROCK_MODEL_ID` if needed (default in code is Claude 3 Haiku on Bedrock).

## Run

```bash
python examples/integrations/bedrock/application.py
```

The script runs a non-streaming call, then a streaming call, using two small Burr graphs defined in `application()` and `streaming_application()`.
