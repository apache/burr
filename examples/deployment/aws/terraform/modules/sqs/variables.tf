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

variable "queue_name" {
  description = "Name of the SQS queue"
  type        = string
}

variable "message_retention_seconds" {
  description = "Message retention period in seconds"
  type        = number
  default     = 1209600
}

variable "visibility_timeout_seconds" {
  description = "Visibility timeout for messages in seconds"
  type        = number
  default     = 300
}

variable "receive_wait_time_seconds" {
  description = "Long polling wait time in seconds"
  type        = number
  default     = 20
}

variable "dlq_message_retention_seconds" {
  description = "DLQ message retention period in seconds"
  type        = number
  default     = 1209600
}

variable "max_receive_count" {
  description = "Max receive count before message moves to DLQ"
  type        = number
  default     = 3
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
