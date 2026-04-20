<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
-->

# Apache Burr AWS Tracking Infrastructure Tutorial

This tutorial explains how to deploy Apache Burr tracking infrastructure on AWS using Terraform. All Terraform code lives in `examples/deployment/aws/terraform/`. It covers deployment with S3 only (polling mode), with S3 and SQS (event-driven mode), and local development without AWS.

## Quick Start

```bash
cd examples/deployment/aws/terraform
terraform init
terraform apply -var-file=dev.tfvars    # S3 only, polling mode
# or
terraform apply -var-file=prod.tfvars   # S3 + SQS, event-driven + DLQ alarm
```

Bucket names are auto-generated. After apply, run `terraform output burr_environment_variables` and set those on your Burr server.

## Overview

The Terraform configuration provisions:

- **S3 bucket**: Stores Burr application logs and database snapshots. Name is auto-generated (`burr-tracking-{env}-{region}-{account_id}-{random}`) when not specified.
- **SQS queue** (optional): Receives S3 event notifications for real-time tracking; controlled by `enable_sqs`
- **CloudWatch alarm + SNS**: Alerts when messages land in the dead letter queue; optional email subscriptions
- **IAM role**: Least-privilege permissions for the Burr server

## Directory Structure

All code is in `examples/deployment/aws/terraform/`:

```
examples/deployment/aws/terraform/
├── main.tf           # Root module: S3, SQS, CloudWatch alarm, SNS, IAM
├── variables.tf      # Input variables
├── outputs.tf        # Output values
├── dev.tfvars       # Development: S3 only (enable_sqs = false)
├── prod.tfvars      # Production: S3 + SQS + DLQ alarm (enable_sqs = true)
├── tutorial.md      # This file
└── modules/
    ├── s3/          # S3 bucket with versioning, encryption, lifecycle
    ├── sqs/         # SQS queue with DLQ and redrive policy
    └── iam/         # IAM role with least-privilege policies
```

## Prerequisites

- Terraform >= 1.0
- AWS CLI configured with credentials

No manual bucket naming required; names are auto-generated. `account_id` is fetched from AWS credentials when not set. For a custom bucket name, set `s3_bucket_name` in your tfvars.

## Using tfvars Files

| File        | Mode              | enable_sqs | Resources created                                      |
|-------------|-------------------|------------|--------------------------------------------------------|
| dev.tfvars  | S3 only (polling) | false      | S3 bucket, IAM role                                    |
| prod.tfvars | S3 + SQS (event)  | true       | S3 bucket, SQS queue, DLQ, CloudWatch alarm, SNS, IAM |

### Development (dev.tfvars) - S3 Only

Uses S3 polling mode (no SQS). Bucket name is auto-generated (`burr-tracking-{env}-{region}-{account_id}-{random}`). Override with `s3_bucket_name = "my-bucket"` in tfvars if needed.

Deploy:

```bash
cd examples/deployment/aws/terraform
terraform init
terraform plan -var-file=dev.tfvars
terraform apply -var-file=dev.tfvars
```

### Production (prod.tfvars) - S3 + SQS

Uses event-driven mode with SQS. Bucket name is auto-generated (`burr-tracking-{env}-{region}-{account_id}-{random}`). A CloudWatch alarm fires when messages land in the DLQ.

Deploy:

```bash
terraform plan -var-file=prod.tfvars
terraform apply -var-file=prod.tfvars
```

### Override Mode in Any tfvars

To deploy with SQS using dev.tfvars, override: `terraform apply -var-file=dev.tfvars -var="enable_sqs=true"`. To deploy S3-only with prod.tfvars: `terraform apply -var-file=prod.tfvars -var="enable_sqs=false"`.

## Deployment Modes

### With S3 and SQS (Event-Driven Mode)

Default configuration. Provides near-instant telemetry updates (~200ms latency).

1. Set `enable_sqs = true` in your tfvars (e.g. prod.tfvars).
2. Deploy with `terraform apply -var-file=prod.tfvars`.
3. Configure the Burr server with the output environment variables:

```bash
terraform output burr_environment_variables
```

4. Set these on your Burr server (ECS task, EC2, etc.):

- BURR_S3_BUCKET
- BURR_TRACKING_MODE=EVENT_DRIVEN
- BURR_SQS_QUEUE_URL
- BURR_SQS_REGION
- BURR_SQS_WAIT_TIME_SECONDS
- BURR_S3_BUFFER_SIZE_MB

### With S3 Only (Polling Mode)

Use when you prefer simpler infrastructure or cannot use SQS. Burr polls S3 periodically (default 120 seconds).

1. Set `enable_sqs = false` in your tfvars.
2. Deploy:

```bash
terraform apply -var-file=dev.tfvars
```

3. Configure the Burr server:

- BURR_S3_BUCKET
- BURR_TRACKING_MODE=POLLING
- BURR_SQS_QUEUE_URL="" (leave empty)
- BURR_SQS_REGION
- BURR_S3_BUFFER_SIZE_MB

The Terraform will create only the S3 bucket and IAM role. No SQS queue or S3 event notifications.

### Without S3 and SQS (Local Mode)

For local development, no Terraform deployment is needed. Burr uses the local filesystem for tracking.

1. Run the Burr server locally:

```bash
burr --no-open
```

2. Use `LocalTrackingClient` in your application instead of `S3TrackingClient`.

3. Data is stored in `~/.burr` by default.

## Key Variables

| Variable | Description | Default |
|----------|-------------|---------|
| aws_region | AWS region | us-east-1 |
| environment | Environment name (dev, prod) | dev |
| account_id | AWS account ID. Empty = auto-fetch from credentials | "" |
| s3_bucket_name | S3 bucket name. Empty = auto-generated (env, region, account_id, random) | "" |
| enable_sqs | Create SQS for event-driven tracking | true |
| sqs_queue_name | Name of the SQS queue | burr-s3-events |
| log_retention_days | Days to retain logs in S3 | 90 |
| snapshot_retention_days | Days to retain DB snapshots | 30 |
| dlq_alarm_notification_emails | Emails to notify when DLQ has messages (confirm via AWS email) | [] |

## CloudWatch DLQ Alarm and SNS Notifications

When SQS is enabled, a CloudWatch alarm fires when messages appear in the dead letter queue. An SNS topic is created for notifications. To receive email alerts, add your addresses to `dlq_alarm_notification_emails` in your tfvars:

```
dlq_alarm_notification_emails = ["ops@example.com", "oncall@example.com"]
```

Each email will receive a confirmation request from AWS; you must confirm the subscription before alerts are delivered. To use Slack or other endpoints, subscribe them to the SNS topic ARN (see `terraform output dlq_alarm_sns_topic_arn`) after apply.

## Outputs

After apply, useful outputs:

```bash
terraform output s3_bucket_name
terraform output sqs_queue_url
terraform output sqs_dlq_url
terraform output dlq_alarm_arn
terraform output dlq_alarm_sns_topic_arn
terraform output burr_environment_variables
```

## IAM Least Privilege

The IAM role grants only:

- **S3**: ListBucket, GetBucketLocation, GetObject, PutObject, DeleteObject, HeadObject on the specific bucket
- **SQS** (when enabled): ReceiveMessage, DeleteMessage, GetQueueAttributes on the specific queue

## Cleanup

To destroy all resources:

```bash
terraform destroy -var-file=dev.tfvars
```

For S3 buckets with versioning, you may need to empty the bucket first:

```bash
aws s3api list-object-versions --bucket BUCKET_NAME --output json | jq -r '.Versions[],.DeleteMarkers[]|.Key+" "+.VersionId' | while read key vid; do aws s3api delete-object --bucket BUCKET_NAME --key "$key" --version-id "$vid"; done
```

## Troubleshooting

**S3 bucket name already exists**: S3 bucket names are globally unique. With auto-generation, each apply gets a new random suffix. For a fixed name, set `s3_bucket_name` explicitly.

**SQS policy errors**: Ensure the S3 bucket notification depends on the queue policy. The Terraform handles this with `depends_on`.

**Burr server not receiving events**: Verify BURR_SQS_QUEUE_URL is set and the IAM role has sqs:ReceiveMessage. Check CloudWatch for the SQS consumer.

**DLQ alarm firing**: Messages in the DLQ mean the Burr server failed to process S3 events (e.g. crashed, timeout). Check the DLQ in the AWS Console, inspect failed messages, and fix the root cause. Confirm SNS email subscriptions via the link AWS sends.

**No email from DLQ alarm**: Check your spam folder for the SNS confirmation email. Subscriptions are pending until confirmed.
