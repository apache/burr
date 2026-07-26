..
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


--------------------
Burr in a web server
--------------------

We like `fastAPI <https://fastapi.tiangolo.com/>`_, but Burr can work with any python-friendly server framework
(`django <https://www.djangoproject.com>`_, `flask <https://flask.palletsprojects.com/>`_, etc...).

To run Burr in a FastAPI server, see the following examples:

- `Human in the loop FastAPI server <https://github.com/apache/burr/tree/main/examples/web-server>`_ (`TDS blog post <https://towardsdatascience.com/building-an-email-assistant-application-with-burr-324bc34c547d>`__ )
- `OpenAI-compatible agent with FastAPI <https://github.com/apache/burr/tree/main/examples/openai-compatible-agent>`_
- `Streaming server using SSE + FastAPI <https://github.com/apache/burr/tree/main/examples/streaming-fastapi>`_  (`TDS blog post <https://towardsdatascience.com/how-to-build-a-streaming-agent-with-burr-fastapi-and-react-e2459ef527a8>`__ )
- `Use typed state with Pydantic + FastAPI <https://github.com/apache/burr/tree/main/examples/typed-state>`_
- `Burr + FastAPI + docker <https://github.com/mdrideout/burr-fastapi-docker-compose>`_ by `Matthew Rideout <https://github.com/mdrideout>`_. This contains a sample web server API + UI + tracking server all bundled in one!
- `Docker compose + nginx proxy <https://github.com/apache/burr/tree/main/examples/email-assistant#running-the-ui-with-email-server-backend-in-a-docker-container>`_ by `Aditha Kaushik <https://github.com/97k>`_ for the email assistant example, demonstrates running the docker image with the tracking server.

Connecting to a database
------------------------

To connect Burr to a database, you can use one of the provided persisters, or build your own:

- :ref:`Documentation on persistence <state-persistence>`
- :ref:`Set of available persisters <persistersref>`
- `Simple chatbot intro with persistence to SQLLite <https://github.com/apache/burr/blob/main/examples/simple-chatbot-intro/notebook.ipynb>`_
