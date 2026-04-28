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

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

locals {
  region_short   = replace(data.aws_region.current.name, "-", "")
  account_id     = var.account_id != "" ? var.account_id : data.aws_caller_identity.current.account_id
  auto_bucket    = "burr-tracking-${var.environment}-${local.region_short}-${local.account_id}-${random_id.bucket_suffix.hex}"
  bucket_name    = var.s3_bucket_name != "" ? var.s3_bucket_name : local.auto_bucket
}

module "s3" {
  source = "./modules/s3"

  bucket_name = local.bucket_name
  tags        = local.common_tags

  lifecycle_rules = [
    {
      id              = "expire-old-logs"
      prefix          = "data/"
      enabled         = true
      expiration_days = var.log_retention_days
      noncurrent_days = 7
    },
    {
      id              = "expire-old-snapshots"
      prefix          = "snapshots/"
      enabled         = true
      expiration_days = var.snapshot_retention_days
      noncurrent_days = null
    }
  ]
}

module "sqs" {
  source = "./modules/sqs"
  count  = var.enable_sqs ? 1 : 0

  queue_name                  = var.sqs_queue_name
  message_retention_seconds   = var.sqs_message_retention_seconds
  visibility_timeout_seconds  = var.sqs_visibility_timeout_seconds
  receive_wait_time_seconds   = var.sqs_receive_wait_time_seconds
  max_receive_count           = var.sqs_max_receive_count
  tags                        = local.common_tags
}

resource "aws_sqs_queue_policy" "s3_notifications" {
  count = var.enable_sqs ? 1 : 0

  queue_url = module.sqs[0].queue_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowS3Notifications"
        Effect = "Allow"
        Principal = {
          Service = "s3.amazonaws.com"
        }
        Action   = "sqs:SendMessage"
        Resource = module.sqs[0].queue_arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = module.s3.bucket_arn
          }
        }
      }
    ]
  })
}

resource "aws_s3_bucket_notification" "burr_logs" {
  count = var.enable_sqs ? 1 : 0

  bucket = module.s3.bucket_id

  queue {
    queue_arn     = module.sqs[0].queue_arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "data/"
    filter_suffix = ".jsonl"
  }

  depends_on = [aws_sqs_queue_policy.s3_notifications]
}

resource "aws_sns_topic" "dlq_alarm" {
  count = var.enable_sqs ? 1 : 0

  name              = "${var.environment}-burr-dlq-alarm"
  display_name     = "Burr DLQ Alarm - ${var.environment}"
  tags             = local.common_tags
}

resource "aws_sns_topic_subscription" "dlq_alarm_email" {
  count = var.enable_sqs && length(var.dlq_alarm_notification_emails) > 0 ? length(var.dlq_alarm_notification_emails) : 0

  topic_arn = aws_sns_topic.dlq_alarm[0].arn
  protocol  = "email"
  endpoint  = var.dlq_alarm_notification_emails[count.index]
}

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  count = var.enable_sqs ? 1 : 0

  alarm_name          = "${var.environment}-burr-dlq-messages"
  alarm_description   = "Alarm when messages appear in Burr SQS dead letter queue"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0

  alarm_actions = [aws_sns_topic.dlq_alarm[0].arn]
  ok_actions    = [aws_sns_topic.dlq_alarm[0].arn]

  dimensions = {
    QueueName = module.sqs[0].dlq_name
  }

  tags = local.common_tags
}

module "iam" {
  source = "./modules/iam"

  role_name     = "${var.environment}-burr-server-role"
  s3_bucket_arn = module.s3.bucket_arn
  sqs_queue_arn = var.enable_sqs ? module.sqs[0].queue_arn : ""
  enable_sqs    = var.enable_sqs
  tags          = local.common_tags
}

locals {
  common_tags = {
    Environment = var.environment
    Project     = "burr-tracking"
    ManagedBy   = "terraform"
  }
}
