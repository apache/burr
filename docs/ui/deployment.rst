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


.. _ui-deployment:

==========
Deployment
==========

The Burr tracking server can be run locally for development or deployed alongside your
production stack for ongoing observability.

--------------------------
Embed in a FastAPI App
--------------------------

Mount the Burr UI inside an existing FastAPI application using the ``mount_burr_ui`` helper:

.. code-block:: python

    from fastapi import FastAPI
    from burr.tracking.server.run import mount_burr_ui

    app = FastAPI()
    mount_burr_ui(app, path="/burr")

The tracking UI will then be available at ``/burr`` on your existing server.

--------------------
Production Options
--------------------

For production deployments, Burr supports two tracking backends:

1. **Local filesystem** (default) — suitable for development or lower-scale production
   with a distributed filesystem. See :ref:`tracking` for configuration details.

2. **S3-backed tracking** — designed for higher-scale production workloads.
   See :ref:`s3-tracking-aws` for setup instructions.

For full deployment examples including Docker Compose and nginx, see
:doc:`../examples/deployment/monitoring`.
