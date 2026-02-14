<!--
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
-->

# ML Training

This is a WIP! Please contribute back if you have ideas. You can track the associated issue [here](https://github.com/apache/burr/issues/138).

A machine learning training system can easily be modeled as a state machine.

While often, this is more of a DAG (E.G. `query_data` -> `feature_engineer` -> `train_model` -> `evaluate_model`), there
are some interesting reasons this as a state machine.

## More granular training routines

If, rather than treating `train` as a action, you treat `train_epoch` as an action, you can utilize the abstractions
burr represents to get the following benefits:

#### Checkpointing

You can store the current params + best model (or pointers to them). Then go back to the failure point. This allows you
to recover from failure in a generic way.

#### Decoupling training logic from termination condition

You can have a condition that checks training completeness based on metric history, which is different from the training logic itself.
This allows you to easily swap in and out termination conditions (testing them against each other or running different ones in different scenarios),
as well as easy reuse.

#### Visibility into lower-level training

Similar to [hooks](https://lightning.ai/docs/pytorch/stable//extensions/callbacks.html) in pytorch lightning,
you can use Burr hooks to log metrics, visualize, etc... at each step. This allows you to have a more granular view of training that updates live
(obviuosly depending on the UI/model-monitoring you're using.)

## Human in the loop

While some models are trained in a single-shot and shipped to production, many require human input.
Burr can be used to express training, then checkpoint/pause the state while a human is evaluating it,
and have their input (e.g. go/no-go) passed in as an [input parameter](https://burr.apache.org/concepts/actions/#runtime-inputs).

Note that this still requires a scheduling tool (say a task executor that runs until the next human input is needed),
but that task executor does not need to be complicated (all it needs to do is run a job when prompted, and possibly on a chron schedule).

## Hyperparameter training

Similar to epoch training, hyperparameter training can be modeled as a state machine. The system makes a decision about what
to look for next based on the prior results. Furthermore, one can model a step that handles multiple jobs, keeping them alive/
launching new ones as they complete (based on state).

For a sketch of the latter see [application.py](./application.py) & ![diagram](./statemachine.png).
