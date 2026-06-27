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


.. _ui:

=======
Burr UI
=======

Burr comes with an open-source telemetry UI for monitoring, debugging, and replaying
your application runs in real time. It works locally out of the box and can also be
deployed alongside your production stack.

.. image:: ../_static/chatbot.png
    :alt: Burr UI showing a chatbot application graph
    :align: center

----------
Data Model
----------

The UI is organized around three levels:

1. **Projects** — the top-level grouping, set via the ``project`` argument to ``with_tracker``.
2. **Applications** — individual runs logged to a project, similar to a "trace" in distributed tracing. Set via the ``app_id`` argument.
3. **Steps** — each action executed in the state machine. The UI shows the state, inputs, and results at every step.

.. toctree::
   :maxdepth: 1
   :hidden:

   getting-started
   notebook
   deployment
