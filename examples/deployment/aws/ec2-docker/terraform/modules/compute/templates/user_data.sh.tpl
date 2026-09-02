#!/bin/bash
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

set -euo pipefail

exec > >(tee /var/log/user-data.log) 2>&1
echo "=== Burr EC2 Docker setup started at $(date) ==="

# Install Docker
yum update -y
yum install -y docker git
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user

# Install Docker Compose plugin
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Clone the repository and build
git clone --depth 1 https://github.com/apache/burr.git /opt/burr
cd /opt/burr/examples/deployment/aws/ec2-docker

docker build -t burr-ec2-app .

# Run the container with restart policy and resource limits
docker run -d \
  --restart=unless-stopped \
  --name burr-app \
  --memory=512m \
  --cpus=1.0 \
  -p ${app_port}:8000 \
  burr-ec2-app

echo "=== Burr EC2 Docker setup completed at $(date) ==="
