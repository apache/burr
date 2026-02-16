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

import datetime
import os
import sys

IS_WINDOWS = os.name == "nt"

if sys.version_info >= (3, 11):
    utc = datetime.UTC
else:
    utc = datetime.timezone.utc


def now():
    return datetime.datetime.now(utc)


# Added support for multiple LLMs and frameworks
class LLMFrameworkConfig:
    def __init__(self, llm_name, framework_name):
        self.llm_name = llm_name
        self.framework_name = framework_name

    def get_llm_name(self):
        return self.llm_name

    def get_framework_name(self):
        return self.framework_name


# Example usage of LLMFrameworkConfig
llm_config = LLMFrameworkConfig("OpenAI GPT-3", "PyTorch")
print(f"LLM: {llm_config.get_llm_name()}, Framework: {llm_config.get_framework_name()}")