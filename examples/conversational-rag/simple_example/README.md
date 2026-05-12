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

# Conversational RAG with memory
This example demonstrates how to build a conversational RAG agent with "memory".

The "memory" here is stored in state, which Burr then can help you track,
manage, and introspect.

The set up of this example is that you have:

1. Some initial "documents" i.e. knowledge.
2. We bootstrap a vector store with these documents.
3. We then have a pipeline that uses a vector store for a RAG query. This example uses a [pre-made conversational RAG pipeline](https://hub.dagworks.io/docs/DAGWorks/conversational_rag/); the prompt isn't hidden under layers of abstraction.
4. We hook everything together with Burr that will manage the state
of the conversation and asking for user inputs.

To run this example, install Burr and the necessary dependencies:

```bash
pip install "apache-burr[start]" -r requirements.txt
```

Then run the server in the background:

```bash
burr
```

Make sure you have an `OPENAI_API_KEY` set in your environment.

Then run
```bash
python application.py
```

You'll then have a text terminal where you can interact. Type exit to stop.

# Application That's Defined:
![Application Image](statemachine.png)

# Video Walkthrough via Notebook
Open the notebook <a target="_blank" href="https://colab.research.google.com/github/apache/burr/blob/main/examples/conversational-rag/simple_example/notebook.ipynb">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/>
</a>

Watch the video walkthrough with the notebook (1.5x+ speed recommended):


<a href="http://www.youtube.com/watch?feature=player_embedded&v=t54DCiOH270" target="_blank">
 <img src="http://img.youtube.com/vi/t54DCiOH270/hqdefault.jpg" alt="Watch the video" border="10" />
</a>
