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

resource "aws_iam_role" "ecs_task_execution_role" {
  name = "burr-ecs"

  assume_role_policy = <<EOF
{
 "Version": "2012-10-17",
 "Statement": [
   {
     "Action": "sts:AssumeRole",
     "Principal": {
       "Service": "ecs-tasks.amazonaws.com"
     },
     "Effect": "Allow",
     "Sid": ""
   }
 ]
}
EOF
}
resource "aws_iam_role" "ecs_task_role" {
  name = "burr-ecs-task"

  assume_role_policy = <<EOF
{
 "Version": "2012-10-17",
 "Statement": [
   {
     "Action": "sts:AssumeRole",
     "Principal": {
       "Service": "ecs-tasks.amazonaws.com"
     },
     "Effect": "Allow",
     "Sid": ""
   }
 ]
}
EOF
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy_attachment" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy_attachment" "ecs_task_role_policy_attachment" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_policy" "custom_s3_policy" {
  name        = "custom-s3-policy"
  description = "Custom policy for read/write/metadata access to burr-prod-test S3 bucket"
  policy      = jsonencode({
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:DeleteObject",
          "s3:PutObjectTagging",
          "s3:GetObjectTagging",
          "s3:DeleteObjectTagging",
          "s3:GetObjectVersion",
          "s3:ListBucketVersions",
          "s3:ListBucketMultipartUploads",
          "s3:AbortMultipartUpload"
        ],
        "Resource": [
          "arn:aws:s3:::burr-prod-test",
          "arn:aws:s3:::burr-prod-test/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "task_s3" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.custom_s3_policy.arn
}

# resource "aws_iam_role_policy_attachment" "task_s3" {
#   role       = aws_iam_role.ecs_task_role.name
#   policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
# }

# resource "aws_iam_role_policy_attachment" "task_s3_execution_role" {
#   role       = "${aws_iam_role.ecs_task_execution_role.name}"
#   policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
# }

data "aws_iam_policy_document" "ecs_auto_scale_role" {
  version = "2012-10-17"
  statement {
    effect = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["application-autoscaling.amazonaws.com"]
    }
  }
}

# ECS auto scale role
resource "aws_iam_role" "ecs_auto_scale_role" {
  name               = var.ecs_auto_scale_role_name
  assume_role_policy = data.aws_iam_policy_document.ecs_auto_scale_role.json
}

# ECS auto scale role policy attachment
resource "aws_iam_role_policy_attachment" "ecs_auto_scale_role" {
  role       = aws_iam_role.ecs_auto_scale_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceAutoscaleRole"
}
