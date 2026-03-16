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

# Production environment configuration
# Bucket name is auto-generated: burr-tracking-{env}-{region}-{account_id}-{random}
# account_id: leave empty to auto-fetch from AWS credentials, or set explicitly

aws_region  = "us-east-1"
environment = "prod"

# account_id = ""   # Optional. Empty = auto-fetch. Or set: account_id = "123456789012"

sqs_queue_name = "burr-s3-events-prod"

enable_sqs = true

log_retention_days      = 90
snapshot_retention_days = 30

sqs_message_retention_seconds  = 1209600
sqs_visibility_timeout_seconds = 300
sqs_receive_wait_time_seconds   = 20
sqs_max_receive_count           = 3

# Optional: receive email when messages land in DLQ
# dlq_alarm_notification_emails = ["ops@example.com"]
