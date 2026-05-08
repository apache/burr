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

.. _aws-deployment-example:

======================
AWS Deployment Example
======================

This example covers deploying Burr tracking infrastructure on AWS with S3, and
optionally SQS for event-driven updates.

The Terraform module lives in:

* ``examples/deployment/aws/terraform``

------------
Architecture
------------

S3-only (polling mode):

* Burr applications write tracking data to S3.
* Tracking server polls/indexes S3 and serves the UI.

S3+SQS (event-driven mode):

* S3 object notifications are delivered to SQS.
* Tracking server consumes SQS and ingests updates with lower latency.

-----------
Quick Start
-----------

.. code-block:: bash

   cd examples/deployment/aws/terraform
   terraform init
   terraform apply -var-file=dev.tfvars   # S3 polling mode
   # or
   terraform apply -var-file=prod.tfvars  # S3 + SQS event-driven mode

After apply, inspect outputs:

.. code-block:: bash

   terraform output burr_environment_variables

Set these environment variables in the runtime where you launch ``burr``.

-----------------------------
Terraform Variables and Modes
-----------------------------

Key variables:

* ``aws_region`` (default ``us-east-1``)
* ``environment`` (for example ``dev`` / ``prod``)
* ``s3_bucket_name`` (optional custom name)
* ``enable_sqs`` (``true`` for event-driven mode)
* ``sqs_queue_name``
* ``log_retention_days``
* ``snapshot_retention_days``
* ``dlq_alarm_notification_emails``

Mode mapping:

* ``dev.tfvars``: S3-only (polling)
* ``prod.tfvars``: S3 + SQS (event-driven)

-----------------
Terraform Outputs
-----------------

Useful outputs include:

* ``s3_bucket_name``
* ``sqs_queue_url``
* ``sqs_dlq_url``
* ``dlq_alarm_arn``
* ``dlq_alarm_sns_topic_arn``
* ``burr_environment_variables``

--------------
Related Guides
--------------

* :ref:`S3 tracking concepts <s3-tracking-aws>`
* :ref:`Amazon Bedrock integration <bedrock-integration>`
