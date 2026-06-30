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

exec > >(tee /var/log/burr-ui-setup.log) 2>&1
echo "=== Burr UI server setup started at $(date) ==="

# Install Python and pip
yum update -y
yum install -y python3.11 python3.11-pip

# Install the Burr tracking server with S3 backend
python3.11 -m pip install "apache-burr[tracking-server-s3,cli]"

# Create a systemd service for the Burr UI
cat > /etc/systemd/system/burr-ui.service <<EOF
[Unit]
Description=Burr Tracking UI Server
After=network.target

[Service]
Type=simple
Environment=BURR_S3_BUCKET=${s3_bucket_name}
ExecStart=/usr/local/bin/burr --no-open --host 0.0.0.0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable burr-ui
systemctl start burr-ui

echo "=== Burr UI server setup completed at $(date) ==="
echo "=== Server listening on port 7241, reading from s3://${s3_bucket_name} ==="
