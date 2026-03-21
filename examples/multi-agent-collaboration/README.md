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

# Multi Agent Collaboration

This example resembles the example from following [cookbook](https://github.com/langchain-ai/langgraph/blob/main/examples/multi_agent/multi-agent-collaboration.ipynb).

There are two implementations:

1. `hamilton/` -- this uses [Hamilton](https://github.com/apache/hamilton) inside the defined actions.
2. `lcel/` -- this uses LangChain's LCEL inside the defined actions.

# `hamilton/application.py` vs `lcel/application.py`:

- They should be functionally equivalent, except that langchain uses deprecated
openai function constructs underneath, while Hamilton uses the non-deprecated tool calling
constructs.
- Compare the two examples to see the code. Burr however doesn't change.

## show me the prompts
With Hamilton the prompts can be found in the moduel [`hamilton/func_agent.py`](hamilton/func_agent.py).

With LangChain that's difficult. You'll need to dive into their code to see what ends up being sent.

# Tracing
You'll see that both `hamilton/application.py` and `lcel/application.py`
have some lightweight `tracing` set up. This is a simple way to plug into Burr's
tracer functionality -- this will allow you to see more in the Burr UI.

More functionality is on the roadmap!

# Running the example

Install the dependencies:

```bash
pip install "burr[start]" -r requirements.txt
```

Make sure you have the API Keys in your environment:

```bash
export OPENAI_API_KEY=YOUR_KEY
export TAVILY_API_KEY=YOUR_KEY
```


To run the example, you can do:

Run the notebook:
<a target="_blank" href="https://colab.research.google.com/github/dagworks-inc/burr/blob/main/examples/multi-agent-collaboration/hamilton/notebook.ipynb">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/>
</a>

```bash
python hamilton/application.py
```
Application run:
![hamilton image](hamilton/statemachine.png)

or

Run the notebook:
<a target="_blank" href="https://colab.research.google.com/github/dagworks-inc/burr/blob/main/examples/multi-agent-collaboration/lcel/notebook.ipynb">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/>
</a>

```bash
python lcel/application.py
```
Application run:
![lcel image](lcel/statemachine.png)
