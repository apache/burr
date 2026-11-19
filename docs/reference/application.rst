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


============
Applications
============

Use this to build and manage a state Machine. You should only ever instantiate the ``ApplicationBuilder`` class,
and not the ``Application`` class directly.


.. autoclass:: burr.core.application.ApplicationBuilder
   :members:

.. _applicationref:

.. autoclass:: burr.core.application.Application
   :members:

   .. automethod:: __init__

.. autoclass:: burr.core.application.ApplicationGraph
   :members:

.. autoclass:: burr.core.application.ApplicationContext
   :members:

.. autoclass:: burr.core.application.ApplicationExecutionLimitError
   :members:

==========
Graph APIs
==========

You can, optionally, use the graph API along with the :py:meth:`burr.core.application.ApplicationBuilder.with_graph`
method. While this is a little more verbose, it helps decouple application logic from graph logic, and is useful in a host
of situations.

The ``GraphBuilder`` class is used to build a graph, and the ``Graph`` class can be passed to the application builder.

.. autoclass:: burr.core.graph.GraphBuilder
   :members:

.. autoclass:: burr.core.graph.Graph
   :members:
