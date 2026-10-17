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

# docs:start:manipulate-state
from burr.core import State

state = State({"count": 1, "messages": ["hello"], "status": "draft"})

updated = state.update(status="ready")  # set the key "status" to "ready"
appended = updated.append(messages="goodbye")  # append "goodbye" to the list at "messages"
incremented = appended.increment(count=1)  # increment the value at "count" by 1

kept = incremented.wipe(keep=["count", "messages"])  # remove all keys except these two
deleted = incremented.wipe(delete=["status"])  # remove "status" from the state
# docs:end:manipulate-state


# docs:start:read-state
message_state = incremented.subset("messages", "status")  # new state with only these keys
all_values = incremented.get_all()  # dictionary with every key/value of the state
# docs:end:read-state


assert state.get_all() == {
    "count": 1,
    "messages": ["hello"],
    "status": "draft",
}
assert incremented.get_all() == {
    "count": 2,
    "messages": ["hello", "goodbye"],
    "status": "ready",
}
assert kept.get_all() == {"count": 2, "messages": ["hello", "goodbye"]}
assert deleted.get_all() == kept.get_all()
assert message_state.get_all() == {
    "messages": ["hello", "goodbye"],
    "status": "ready",
}
assert all_values == incremented.get_all()
