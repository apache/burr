# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements. See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership. The ASF licenses this file
# to you under the Apache License, Version 2.0.

from fastapi import FastAPI
import uvicorn

from burr.tracking.server.run import mount_burr_ui

app = FastAPI()

# Mount Burr UI
mount_burr_ui(app, path="/burr")


@app.get("/")
def root():
    return {"message": "Main FastAPI app with Burr UI mounted"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
