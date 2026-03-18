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
Telemetry has been removed from Burr per ASF policy.

This module is kept as a backwards-compatible no-op stub so that
any external code that imports from it (e.g. ``telemetry.disable_telemetry()``)
will continue to work without error.
"""

import warnings


def disable_telemetry():
    """No-op. Telemetry has been removed."""
    warnings.warn(
        "disable_telemetry() is deprecated and will be removed in a future release. "
        "Telemetry has been removed from Burr per ASF policy.",
        DeprecationWarning,
        stacklevel=2,
    )


def is_telemetry_enabled() -> bool:
    """Always returns False. Telemetry has been removed."""
    warnings.warn(
        "is_telemetry_enabled() is deprecated and will be removed in a future release. "
        "Telemetry has been removed from Burr per ASF policy.",
        DeprecationWarning,
        stacklevel=2,
    )
    return False
