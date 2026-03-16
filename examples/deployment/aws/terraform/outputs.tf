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

output "s3_bucket_name" {
  description = "Name of the S3 bucket for Burr logs"
  value       = module.s3.bucket_id
}

output "s3_bucket_arn" {
  description = "ARN of the S3 bucket"
  value       = module.s3.bucket_arn
}

output "sqs_queue_url" {
  description = "URL of the SQS queue for S3 events"
  value       = var.enable_sqs ? module.sqs[0].queue_url : null
}

output "sqs_queue_arn" {
  description = "ARN of the SQS queue"
  value       = var.enable_sqs ? module.sqs[0].queue_arn : null
}

output "sqs_dlq_url" {
  description = "URL of the dead letter queue"
  value       = var.enable_sqs ? module.sqs[0].dlq_url : null
}

output "dlq_alarm_arn" {
  description = "ARN of the CloudWatch alarm for DLQ messages"
  value       = var.enable_sqs ? aws_cloudwatch_metric_alarm.dlq_messages[0].arn : null
}

output "dlq_alarm_sns_topic_arn" {
  description = "ARN of the SNS topic for DLQ alarm notifications"
  value       = var.enable_sqs ? aws_sns_topic.dlq_alarm[0].arn : null
}

output "iam_role_arn" {
  description = "ARN of the IAM role for Burr server"
  value       = module.iam.role_arn
}

output "iam_role_name" {
  description = "Name of the IAM role for Burr server"
  value       = module.iam.role_name
}

output "burr_environment_variables" {
  description = "Environment variables to configure Burr server"
  value = var.enable_sqs ? {
    BURR_S3_BUCKET             = module.s3.bucket_id
    BURR_TRACKING_MODE         = "EVENT_DRIVEN"
    BURR_SQS_QUEUE_URL         = module.sqs[0].queue_url
    BURR_SQS_REGION            = data.aws_region.current.name
    BURR_SQS_WAIT_TIME_SECONDS = "20"
    BURR_S3_BUFFER_SIZE_MB     = "10"
  } : {
    BURR_S3_BUCKET             = module.s3.bucket_id
    BURR_TRACKING_MODE         = "POLLING"
    BURR_SQS_QUEUE_URL         = ""
    BURR_SQS_REGION            = data.aws_region.current.name
    BURR_SQS_WAIT_TIME_SECONDS = "20"
    BURR_S3_BUFFER_SIZE_MB     = "10"
  }
}
