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

# Development environment configuration
# Bucket name is auto-generated: burr-tracking-{env}-{region}-{account_id}-{random}
# account_id: leave empty to auto-fetch from AWS credentials, or set explicitly

aws_region  = "us-east-1"
environment = "dev"

# account_id = ""   # Optional. Empty = auto-fetch. Or set: account_id = "123456789012"

sqs_queue_name = "burr-s3-events-dev"

# S3 only (polling mode) - simpler for dev; set to true for event-driven
enable_sqs = false

log_retention_days      = 30
snapshot_retention_days = 14

sqs_message_retention_seconds  = 86400
sqs_visibility_timeout_seconds = 120
sqs_receive_wait_time_seconds  = 20
sqs_max_receive_count          = 3
