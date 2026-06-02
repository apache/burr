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

# Cowsay

This is an example of a simple infinite state machine.

We have three files:

- [application.py](application.py) -- This contains a mainline to run the cowsay app as well as a function to export the app (for later use)
- [requirements.txt](requirements.txt) -- Just the requirements. All this needs is Burr/Streamlit/cowsay
- [streamlit_app.py](streamlit_app.py) -- This contains a simple Streamlit app to interact with the cow
- [notebook.ipynb](notebook.ipynb) -- A notebook that helps show things. <a target="_blank" href="https://colab.research.google.com/github/apache/burr/blob/main/examples/other-examples/cowsay/notebook.ipynb">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/>
</a>

To run just the application, you can run:

```bash
python application.py
```

Note this is an infinte state machine, so this will run forever! Thus remember to ctrl-c eventually.
To run the streamlit app, you can run:

```bash
streamlit run streamlit_app.py
```

This allows you to press a button and see the cow say something (or see it decide not to speak).

This will open a chrome window and print out the URL. The state machine this encapsulates takes the following form:

![State Machine](digraph.png)
