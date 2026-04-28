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

# Examples

This contains a series of examples. Each example is meant to demonostrate a feature/use-case of the Burr library.

Each example contains:
1. A `README.md` file that explains the example (what its teaching/how it works)
2. A `application.py` file that contains the code for the example. This will have a function `application` that creates the example, and a mainline that demonstrates it.
3. A `requirements.txt` file that contains the dependencies for the example
4. A `notebook.ipynb` file that contains the example in a Jupyter notebook
5. A `statemachine.png` file that contains the graphical representation of the state machine
6. A `__init__.py` file that allows the example to be imported as a module

You can run any example with the following commands:

```python
pip install -r examples/<example>/requirements.txt # use your favorite package manager/venv tool
python examples/<example>/application.py
```

Note we have a few more in [other-examples](other-examples/), but those do not yet adhere to the same format/are as well documented.

# Index

- [simple-chatbot-intro](simple-chatbot-intro/) - This is a simple chatbot that shows how to use Burr to create a simple chatbot. This is a good starting point for understanding how to use Burr -- the notebook follows the original [blog post](https://blog.dagworks.io/p/burr-develop-stateful-ai-applications).
- [conversational-rag](conversational-rag/) - This shows multiple examples on how to use Burr to create a conversational RAG chatbot. This shows how to use state/prior knowledge to augment your LLM call with Burr.
- [hello-world-counter](hello-world-counter/) - This is an example of a simple state machine, used in the docs.
- [llm-adventure-game](llm-adventure-game/) - This is an example of a simple text-based adventure game using LLMs -- it shows how to progress through hidden states while reusing components.
- [ml-training](ml-training/) - This is an example of a simple ML training pipeline. It shows how to use Burr to track the training of a model. This is not complete.
- [multi-agent-collaboration](multi-agent-collaboration/) - This example shows how to use Burr to create a multi-agent collaboration. This is a clone of the following [LangGraph example](https://github.com/langchain-ai/langgraph/blob/main/examples/multi_agent/multi-agent-collaboration.ipynb).
- [multi-modal-chatbot](multi-modal-chatbot/) - This example shows how to use Burr to create a multi-modal chatbot. This demonstrates how to use a model to delegate to other models conditionally.
- [streaming-overview](streaming-overview/) - This example shows how we can use the streaming API to respond to return quicker results to the user and build a seamless experience
- [integrations/bedrock](integrations/bedrock/) - Minimal graphs using Amazon Bedrock (`BedrockAction` and `BedrockStreamingAction`).
- [tracing-and-spans](tracing-and-spans/) - This example shows how to use Burr to create a simple chatbot with additional visibility. This is a good starting point for understanding how to use Burr's tracing functionality.
- [web-server](web-server/) - This example shows how to use Burr in a web server. This is a good starting point for understanding how to use Burr for interaction.
