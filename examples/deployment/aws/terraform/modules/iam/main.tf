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

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = var.trusted_services
    }
  }
}

resource "aws_iam_role" "burr_server" {
  name               = var.role_name
  assume_role_policy = data.aws_iam_policy_document.assume_role.json

  tags = merge(var.tags, {
    Name = var.role_name
  })
}

data "aws_iam_policy_document" "s3_least_privilege" {
  statement {
    sid    = "S3ListBucket"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]
    resources = [var.s3_bucket_arn]
  }

  statement {
    sid    = "S3ObjectOperations"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:HeadObject"
    ]
    resources = ["${var.s3_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "s3" {
  name   = "${var.role_name}-s3"
  role   = aws_iam_role.burr_server.id
  policy = data.aws_iam_policy_document.s3_least_privilege.json
}

data "aws_iam_policy_document" "sqs_least_privilege" {
  count = var.enable_sqs ? 1 : 0

  statement {
    sid    = "SQSConsume"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes"
    ]
    resources = [var.sqs_queue_arn]
  }
}

resource "aws_iam_role_policy" "sqs" {
  count  = var.enable_sqs ? 1 : 0
  name   = "${var.role_name}-sqs"
  role   = aws_iam_role.burr_server.id
  policy = data.aws_iam_policy_document.sqs_least_privilege[0].json
}

