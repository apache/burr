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


=================
Lifecycle API
=================


These are the available lifecycle hooks for Burr. Implement these classes
and add instances to the application builder to customize your state machines's execution.

.. _hooksref:
.. autoclass:: burr.lifecycle.base.PreRunStepHook
   :members:

.. autoclass:: burr.lifecycle.base.PreRunStepHookAsync
   :members:

.. autoclass:: burr.lifecycle.base.PostRunStepHook
   :members:

.. autoclass:: burr.lifecycle.base.PostRunStepHookAsync
    :members:

.. autoclass:: burr.lifecycle.base.PostApplicationCreateHook
    :members:

.. autoclass:: burr.lifecycle.base.PreStartSpanHook
    :members:

.. autoclass:: burr.lifecycle.base.PreStartSpanHookAsync
    :members:

.. autoclass:: burr.lifecycle.base.PostEndSpanHook
    :members:

.. autoclass:: burr.lifecycle.base.PostEndSpanHookAsync
    :members:

.. autoclass:: burr.lifecycle.base.ExecuteMethod
    :members:

.. autoclass:: burr.lifecycle.base.PreApplicationExecuteCallHook
    :members:

.. autoclass:: burr.lifecycle.base.PreApplicationExecuteCallHookAsync
    :members:

.. autoclass:: burr.lifecycle.base.PostApplicationExecuteCallHook
    :members:

.. autoclass:: burr.lifecycle.base.PostApplicationExecuteCallHookAsync
    :members:

These hooks are available for you to use:

.. autoclass:: burr.lifecycle.default.InMemoryExecutionRecorder
   :members:

.. autoclass:: burr.lifecycle.default.ExecutionRecord
   :members:

.. autoclass:: burr.lifecycle.default.StateChange
   :members:

.. autoclass:: burr.lifecycle.default.StateAndResultsFullLogger

   .. automethod:: __init__

.. autoclass:: burr.lifecycle.default.SlowDownHook

    .. automethod:: __init__
