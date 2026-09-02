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

"""HTTP server for the Burr counter application.

Exposes:
- POST /run  -- run the counter app with a given target number
- GET /health -- health check endpoint for load balancers and monitoring
"""

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.counter_app import application

app = FastAPI(title="Burr EC2 Docker Example")


class RunRequest(BaseModel):
    number: int = 5


@app.post("/run")
def run_counter(req: RunRequest):
    """Run the counter application up to the requested number."""
    burr_app = application(req.number)
    _, _, state = burr_app.run(halt_after=["result"])
    return state.serialize()


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("app.server:app", host="0.0.0.0", port=8000)
