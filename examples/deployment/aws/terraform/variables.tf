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

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "account_id" {
  description = "AWS account ID for bucket name. Leave empty to auto-fetch from AWS credentials."
  type        = string
  default     = ""
}

variable "s3_bucket_name" {
  description = "Name of the S3 bucket for Burr logs. If empty, auto-generated from environment, region, and random suffix."
  type        = string
  default     = ""
}

variable "enable_sqs" {
  description = "Enable SQS for event-driven tracking. When false, Burr uses S3 polling mode."
  type        = bool
  default     = true
}

variable "sqs_queue_name" {
  description = "Name of the SQS queue for S3 events"
  type        = string
  default     = "burr-s3-events"
}

variable "log_retention_days" {
  description = "Days to retain log files in S3"
  type        = number
  default     = 90
}

variable "snapshot_retention_days" {
  description = "Days to retain database snapshots in S3"
  type        = number
  default     = 30
}

variable "sqs_message_retention_seconds" {
  description = "SQS message retention period in seconds"
  type        = number
  default     = 1209600
}

variable "sqs_visibility_timeout_seconds" {
  description = "SQS visibility timeout in seconds"
  type        = number
  default     = 300
}

variable "sqs_receive_wait_time_seconds" {
  description = "SQS long polling wait time in seconds"
  type        = number
  default     = 20
}

variable "sqs_max_receive_count" {
  description = "Max receive count before message moves to DLQ"
  type        = number
  default     = 3
}

variable "dlq_alarm_notification_emails" {
  description = "Email addresses to notify when messages land in the DLQ. Empty = no email subscriptions."
  type        = list(string)
  default     = []
}
