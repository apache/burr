# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements. See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership. The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the License for the
# specific language governing permissions and limitations
# under the License.

"""HTTP entrypoint for the Burr counter example in Python Workers."""

import json
from urllib.parse import urlparse

from app.counter_app import application
from workers import Response, WorkerEntrypoint


def respond(data, status=200):
    """Return JSON ``data`` with HTTP ``status``."""
    return Response(json.dumps(data), status=status, headers={"Content-Type": "application/json"})


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        """Run the counter for a POST ``request`` and return its serialized Burr State."""
        if urlparse(request.url).path != "/api/counter":
            return respond({"error": "Not found"}, 404)
        if request.method != "POST":
            return respond({"error": "Only POST method is allowed"}, 405)
        try:
            data = json.loads(await request.text())
            if not isinstance(data, dict):
                return respond({"error": "JSON object required"}, 400)
            count_up_to = int(data.get("number", 0))
            if count_up_to <= 0:
                return respond({"error": "number must be greater than 0"}, 400)
        except (TypeError, ValueError):
            return respond({"error": "Invalid JSON or number"}, 400)
        app = application(count_up_to)
        _, _, state = app.run(halt_after=["result"])
        return respond(state.serialize())
