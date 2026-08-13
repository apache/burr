# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
Example of running the application
from another module to make sure the
SERDE classes are registered in a non __main__
module namespace.

e.g. python run.py
and then
burr-test-case create --project-name serde-example --app-id APP_ID --sequence-id 3 --serde-module application.py
"""

import pprint
import uuid

import application  # noqa
from application import build_application

from burr.core import State

# build
app = build_application("client-123", str(uuid.uuid4()))
app.visualize(
    output_file_path="statemachine", include_conditions=True, include_state=True, format="png"
)
# run
action, result, state = app.run(
    halt_after=["terminal_action"], inputs={"user_input": "hello world"}
)
# serialize
serialized_state = state.serialize()
pprint.pprint(serialized_state)
# deserialize
deserialized_state = State.deserialize(serialized_state)
# assert that the state is the same after serialization and deserialization
assert state.get_all() == deserialized_state.get_all()
