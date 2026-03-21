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

# Traces and spans

This demo covers the tracing/span capabilities in Burr.
For additional information, read over: [the documentation](https://burr.apache.org/concepts/additional-visibility/).
This does the same thing as the standard [multi-modal example](../multi-modal-chatbot), but leverages traces.

Note that you'll likely be integrating tracing into whatever framework (langchain/hamilton) you're using -- we're
still building out capabilities to do this more automatically.

These traces are used in the Burr UI. E.G. as follows:

![tracing](tracing_screencap.png)

The notebook also shows how things work. <a target="_blank" href="https://colab.research.google.com/github/apache/burr/blob/main/examples/tracing-and-spans/notebook.ipynb">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/>
</a>
