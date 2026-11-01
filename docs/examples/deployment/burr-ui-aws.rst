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


.. _burr-ui-aws-deployment:

==============================
Burr UI on AWS (Private VPC)
==============================

Deploy the Burr tracking UI server in a private VPC, reading from an existing S3 tracking bucket.
Access is via AWS SSM Session Manager port forwarding.

See the full example:

* Source: `GitHub <https://github.com/apache/burr/tree/main/examples/deployment/aws/burr-ui>`_
* ``examples/deployment/aws/burr-ui/README.md``

-----------
Quick Start
-----------

.. code-block:: bash

    cd examples/deployment/aws/burr-ui/terraform
    terraform init
    terraform apply -var="s3_bucket_name=my-tracking-bucket"

--------------------------
Access the Private UI
--------------------------

.. code-block:: bash

    INSTANCE_ID=$(terraform output -raw instance_id)
    aws ssm start-session --target $INSTANCE_ID \
      --document-name AWS-StartPortForwardingSession \
      --parameters '{"portNumber":["7241"],"localPortNumber":["7241"]}'

Then open http://localhost:7241.

--------------
Related Guides
--------------

* :ref:`S3 Tracking on AWS <s3-tracking-aws>`
* :ref:`AWS Deployment overview <aws-deployment-example>`
