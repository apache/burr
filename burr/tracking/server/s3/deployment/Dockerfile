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

# Use an official Python runtime as a parent image
FROM python:3.11-slim


# Set environment variables
ENV PYTHONUNBUFFERED 1

# Set working directory
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install dependencies and git
RUN apt-get update && apt-get install -y \
    git \
    nginx \
    gcc \
    && apt-get clean

# Install the dependencies
# TODO -- use the right version
#RUN pip install "git+https://github.com/apache/burr.git@tracker-s3#egg=apache-burr[tracking-server-s3]"
RUN pip install "apache-burr[tracking-server-s3]>=0.29.0"

# Copy the nginx config file
COPY nginx.conf /etc/nginx/nginx.conf

# Expose the port FastAPI will run on and the port NGINX will listen to
EXPOSE 8000
EXPOSE 80

ENV BURR_S3_BUCKET burr-prod-test
ENV BURR_load_snapshot_on_start True
ENV BURR_snapshot_interval_milliseconds 3_600_000
ENV BURR_update_interval_milliseconds 150_000
ENV BURR_BACKEND_IMPL s3
ENV ENV DEBIAN_FRONTEND noninteractive
ENV BURR_BACKEND_IMPL burr.tracking.server.s3.backend.SQLiteS3Backend


# Command to run FastAPI server and NGINX
CMD ["sh", "-c", "uvicorn burr.tracking.server.run:app --host 0.0.0.0 --port 8000 & nginx -g 'daemon off;'"]
