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

variable "role_name" {
  description = "Name of the IAM role for Burr server"
  type        = string
}

variable "trusted_services" {
  description = "List of AWS services that can assume this role"
  type        = list(string)
  default     = ["ecs-tasks.amazonaws.com", "ec2.amazonaws.com", "lambda.amazonaws.com"]
}

variable "s3_bucket_arn" {
  description = "ARN of the S3 bucket for least privilege access"
  type        = string
}

variable "enable_sqs" {
  description = "Enable SQS IAM permissions"
  type        = bool
  default     = true
}

variable "sqs_queue_arn" {
  description = "ARN of the SQS queue for least privilege access"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
