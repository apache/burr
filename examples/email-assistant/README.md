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

# Email Assistant

This example shows how to create a basic email assistant. This assistant
takes in an email and will write a response. It allows you to prompt it with:
1. An email
2. Directions on how to respond

Then it generates questions for you for clarifications, and uses the answer to write a draft.
It will go back and forth with you until you are satisfied with the response.

This demonstrates how to do multi-shot modeling interactively with an LLM. You'll learn:

1. How to move in/out of program control -> user control
2. How to process inputs at multiple points through the process
3. How to involve multi-shot modeling with an LLM

## How to run

To run this example, you need to install the following dependencies:

```bash
pip install -r requirements.txt
```

Then if you run `jupyter lab` you can open/execute the notebook.
This simulates an interactive web app. The notebook is the best way to get started.

Note we will be adding two things to this demo:
1. An integration with the burr web app
2. a standalone server example with a walkthrough

Open the notebook <a target="_blank" href="https://colab.research.google.com/github/apache/burr/blob/main/examples/email-assistant/notebook.ipynb">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/>
</a>

## Running the UI with Email Server Backend in a Docker Container

We have added Docker support along with a compose file and nginx as a proxy for the API and Burr UI. To run the email assistant app with these new features:

1. Run the following command:
   ```
   docker compose up --build
   ```

2. This will start the email assistant app along with nginx, which allows you to access:
   - BURR UI on `telemetry.localhost`
   - API on `api.localhost`

3. If you prefer not to use subdomains powered by nginx, you can also access:
   - Email server running Burr: Navigate to `localhost:7242/docs`
   - Burr UI: Navigate to `localhost:7241`

4. If you don't have a UI, go to demos and play with the email-assistant. Otherwise, connect to the Burr email server with your UI code.

Note: This setup does not mount a persistent volume, so state is lost once the container goes down.

## Additional Information

We will be adding two things to this demo:
1. An integration with the Burr web app
2. A standalone server example with a walkthrough
