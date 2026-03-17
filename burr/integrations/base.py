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


def require_plugin(import_error: ImportError, plugin_name: str):
    raise ImportError(
        f"Missing plugin {plugin_name}! To use the {plugin_name} plugin, you must install the 'extras' target [{plugin_name}] with burr[{plugin_name}] "
        f"(replace with your package manager of choice). Note that, if you're using poetry, you cannot install burr with burr[start], so "
        f"you'll have to install the components individually. See https://burr.apache.org/getting_started/install/ "
        f"for more details."
    ) from import_error
