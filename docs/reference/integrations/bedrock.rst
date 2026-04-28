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


.. _bedrock-integration:

==============
Amazon Bedrock
==============

`Amazon Bedrock <https://aws.amazon.com/bedrock/>`_ models can be called through the
Bedrock Runtime **Converse** and **Converse Stream** APIs using the actions below.

Install the optional extra (pulls ``boto3``):

.. code-block:: bash

   pip install "burr[bedrock]"

IAM permissions must allow ``bedrock:InvokeModel`` / streaming equivalents for your
chosen models; see AWS documentation for your account and model IDs.

.. autoclass:: burr.integrations.bedrock.BedrockAction
   :members: run_and_update
   :show-inheritance:

.. autoclass:: burr.integrations.bedrock.BedrockStreamingAction
   :members: stream_run, update
   :show-inheritance:
