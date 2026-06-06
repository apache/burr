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

   pip install "apache-burr[bedrock]"

-----------------
Available Actions
-----------------

``BedrockAction`` is a single-step action for standard request/response flows.
``BedrockStreamingAction`` is a streaming action that emits chunks during execution
and applies final state updates when complete.

Both actions accept:

* ``model_id``: Bedrock model identifier (for example Claude models on Bedrock)
* ``input_mapper``: maps Burr state to Bedrock ``messages`` (and optional ``system``)
* ``reads`` / ``writes``: standard Burr state wiring
* Optional AWS settings: ``region``, ``max_retries``, optional injected ``client``
* Optional guardrails: ``guardrail_id`` + required ``guardrail_version``
* Optional ``inference_config`` passed through to Bedrock

.. note::

   If ``guardrail_id`` is set, ``guardrail_version`` is required.

----------------
Supported Models
----------------

Burr passes ``model_id`` directly to Bedrock Runtime. Any model that supports
the Bedrock **Converse** / **ConverseStream** API in your account and region can be
used. See AWS model availability by region and account entitlement:

* `Supported foundation models in Amazon Bedrock <https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html>`_
* `Converse API reference <https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html>`_
* `ConverseStream API reference <https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseStream.html>`_

---------------
IAM Permissions
---------------

At minimum, the runtime identity used by Burr should have permission to invoke
the specific Bedrock model(s) you choose:

* ``bedrock:InvokeModel``
* ``bedrock:InvokeModelWithResponseStream`` (for streaming)

Depending on your setup, you may also need permissions for guardrails and
cross-account resource access. Restrict resources to specific model ARNs whenever possible.

-------------
Quick Example
-------------

.. code-block:: python

   from burr.integrations.bedrock import BedrockAction

   def map_state_to_prompt(state):
       return {
           "messages": [{"role": "user", "content": [{"text": state["question"]}]}],
           "system": [{"text": "You are a concise assistant."}],
       }

   ask_model = BedrockAction(
       name="ask_model",
       model_id="anthropic.claude-3-haiku-20240307-v1:0",
       input_mapper=map_state_to_prompt,
       reads=["question"],
       writes=["response", "usage", "stop_reason"],
       region="us-east-1",
   )

See the runnable integration example in the repository:
`examples/integrations/bedrock <https://github.com/apache/burr/tree/main/examples/integrations/bedrock>`_.

.. autoclass:: burr.integrations.bedrock.BedrockAction
   :members: run_and_update
   :show-inheritance:

.. autoclass:: burr.integrations.bedrock.BedrockStreamingAction
   :members: stream_run, update
   :show-inheritance:
