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

url = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"

# Load the data
import requests
import json

response = requests.get(url, timeout=30)
response.raise_for_status()
data = response.json()

keys_wanted = ["input_cost_per_token", "output_cost_per_token", "max_tokens", "max_input_tokens", "max_output_tokens"]

del data["sample_spec"]
# Extract the keys we want
for model_entry in data:
    for key in list(data[model_entry].keys()):
        if key not in keys_wanted:
            del data[model_entry][key]

# save the data
with open("model_costs.json", "w", encoding="utf-8") as f:
    json.dump(data, f)
