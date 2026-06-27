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

.. _s3-tracking-aws:

=============================
S3 Tracking on AWS (Concepts)
=============================

This guide explains how Burr tracking works with S3-backed storage, and how to
choose between local, hybrid, and production deployment modes.

Use the S3 client in your app:

.. code-block:: bash

   pip install "burr[tracking-client-s3]"

and run the S3-backed tracking server/UI:

.. code-block:: bash

   pip install "burr[tracking-server-s3,cli]"

-----------------
Deployment Models
-----------------

Local
^^^^^

Use ``LocalTrackingClient`` and local filesystem storage (default ``~/.burr``).
This is the simplest setup for development and debugging.

Hybrid
^^^^^^

Use ``S3TrackingClient`` from applications while running the tracking server in
one environment (for example a shared development server). Applications can run
from local machines, jobs, or services as long as they can write to the bucket.

Production
^^^^^^^^^^

Use ``S3TrackingClient`` for all application writes and a dedicated S3-backed
tracking server for indexing and visualization. For near-real-time updates, pair
S3 object events with SQS event-driven mode.

----------------
SQS Event-Driven
----------------

S3 tracking server supports two modes:

* ``POLLING``: periodic S3 scans (simpler infra)
* ``EVENT_DRIVEN``: SQS-backed event consumption for lower latency

To use event-driven mode, configure these environment variables on the tracking server:

* ``BURR_TRACKING_MODE=EVENT_DRIVEN``
* ``BURR_SQS_QUEUE_URL=<queue-url>``
* ``BURR_SQS_REGION=<aws-region>``
* ``BURR_SQS_WAIT_TIME_SECONDS=20`` (default long-poll value)

----------------
Stream Buffering
----------------

S3 reads are buffered to improve reliability and large-object handling in the
tracking server. Tune buffering memory with:

* ``BURR_S3_BUFFER_SIZE_MB`` (default: ``10``)

The S3 tracking client also batches writes before flushes (default flush interval
is 5 seconds), reducing object churn for high event volume.

-----------------------
Configuration Reference
-----------------------

Common S3 server environment variables:

* ``BURR_S3_BUCKET`` (required)
* ``BURR_UPDATE_INTERVAL_MILLISECONDS`` (default ``120000``)
* ``BURR_AWS_MAX_CONCURRENCY`` (default ``100``)
* ``BURR_SNAPSHOT_INTERVAL_MILLISECONDS`` (default ``3600000``)
* ``BURR_LOAD_SNAPSHOT_ON_START`` (default ``True``)
* ``BURR_PRIOR_SNAPSHOTS_TO_KEEP`` (default ``5``)
* ``BURR_TRACKING_MODE`` (``POLLING`` or ``EVENT_DRIVEN``)
* ``BURR_SQS_QUEUE_URL`` / ``BURR_SQS_REGION`` / ``BURR_SQS_WAIT_TIME_SECONDS``
* ``BURR_S3_BUFFER_SIZE_MB``

---------------
Terraform Setup
---------------

Use the included AWS Terraform example to provision S3-only or S3+SQS tracking
infrastructure:

* ``examples/deployment/aws/terraform``
* :ref:`AWS deployment example <aws-deployment-example>`

---------------
Migration Guide
---------------

From local tracking to S3 tracking:

#. Keep your existing Burr graph logic unchanged.
#. Replace ``LocalTrackingClient`` with ``S3TrackingClient`` in
   ``ApplicationBuilder.with_tracker(...)``.
#. Provision bucket/IAM (and optionally SQS) in AWS.
#. Configure tracking server environment variables.
#. Validate with one test project before enabling for all workloads.

Example client wiring:

.. code-block:: python

   from burr.tracking.s3client import S3TrackingClient

   tracker = S3TrackingClient(
       project="my_project",
       bucket="my-burr-tracking-bucket",
       region="us-east-1",
   )
