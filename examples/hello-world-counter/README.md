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

# Counter

This is an example of a simple state machine.

We have three files:

- [application.py](application.py) -- This contains a mainline to run the counter as well as a function to export the counter (for later use)
- [requirements.txt](requirements.txt) -- Just the requirements. All this needs is Burr/Streamlit
- [streamlit_app.py](streamlit_app.py) -- This contains a simple Streamlit app to interact with the counter.
- [notebook.ipynb](notebook.ipynb) -- A notebook that shows the counter app too. Open the notebook <a target="_blank" href="https://colab.research.google.com/github/apache/burr/blob/main/examples/hello-world-counter/notebook.ipynb">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/>
</a>

To run just the application, you can run:

```bash
python application.py
```

To run the streamlit app, you can run:

```bash
streamlit run streamlit_app.py
```

This will open a chrome window and print out the URL. The state machine this encapsulates takes the following form:

![State Machine](statemachine.png)

Note: if you are looking for an example of the class based action API, then
take a look at `application_classbased.py`.
