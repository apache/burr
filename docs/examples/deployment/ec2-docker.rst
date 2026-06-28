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


.. _ec2-docker-deployment:

==========================
AWS EC2 + Docker
==========================

Deploy a Burr application as a Docker container on an AWS EC2 instance, provisioned with Terraform.

See the full example and step-by-step guide:

* Source: `GitHub <https://github.com/apache/burr/tree/main/examples/deployment/aws/ec2-docker>`_
* ``examples/deployment/aws/ec2-docker/README.md``

-----------
Quick Start
-----------

.. code-block:: bash

    cd examples/deployment/aws/ec2-docker
    docker build -t burr-ec2-example .
    docker run -p 8000:8000 burr-ec2-example
    curl -X POST http://localhost:8000/run -H "Content-Type: application/json" -d '{"number": 5}'

-------------
Deploy to AWS
-------------

.. code-block:: bash

    cd terraform
    terraform init
    terraform apply -var-file=dev.tfvars

--------------
Related Guides
--------------

* :ref:`S3 Tracking on AWS <s3-tracking-aws>`
* :ref:`AWS Deployment overview <aws-deployment-example>`
