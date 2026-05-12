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

# Streaming chatbot

This example shows how we can use the streaming API
to respond to return quicker results to the user and build a more
seamless interactive experience.

This is the same chatbot as the one in the `chatbot` example,
but it is built slightly differently (for streaming purposes).

## How to use

Run `streamlit run streamlit_app.py` from the command line and you will see the chatbot in action.
Open up the burr UI `burr` and you can track the chatbot.

## Async

We also have an async version in [async_application.py](async_application.py)
which demonstrates how to use streaming async. We have not hooked this up
to a streamlit application yet, but that should be trivial.

## Notebook
The notebook also shows how things work. <a target="_blank" href="https://colab.research.google.com/github/apache/burr/blob/main/examples/streaming-overview/notebook.ipynb">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/>
</a>
