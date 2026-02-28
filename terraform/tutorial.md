# Apache Burr AWS Tracking Infrastructure Tutorial

This tutorial explains how to deploy Apache Burr tracking infrastructure on AWS using Terraform. All Terraform code lives in the `terraform/` folder. It covers deployment with S3 only (polling mode), with S3 and SQS (event-driven mode), and local development without AWS.

## Overview

The Terraform configuration provisions:

- **S3 bucket**: Stores Burr application logs and database snapshots (always created for AWS deployment)
- **SQS queue** (optional): Receives S3 event notifications for real-time tracking; controlled by `enable_sqs`
- **IAM role**: Least-privilege permissions for the Burr server

## Directory Structure

All code is in `terraform/`:

```
terraform/
├── main.tf           # Root module wiring S3, SQS, IAM
├── variables.tf      # Input variables
├── outputs.tf        # Output values
├── dev.tfvars       # Development: S3 only (enable_sqs = false)
├── prod.tfvars      # Production: S3 + SQS (enable_sqs = true)
├── tutorial.md      # This file
└── modules/
    ├── s3/          # S3 bucket with versioning, encryption, lifecycle
    ├── sqs/         # SQS queue with DLQ and redrive policy
    └── iam/         # IAM role with least-privilege policies
```

## Prerequisites

- Terraform >= 1.0
- AWS CLI configured with credentials
- AWS account ID (for unique S3 bucket names)

Get your AWS account ID:

```bash
aws sts get-caller-identity --query Account --output text
```

## Using tfvars Files

| File        | Mode              | enable_sqs | Resources created        |
|-------------|-------------------|------------|--------------------------|
| dev.tfvars  | S3 only (polling) | false      | S3 bucket, IAM role      |
| prod.tfvars | S3 + SQS (event)  | true       | S3 bucket, SQS queue, IAM |

### Development (dev.tfvars) - S3 Only

Uses S3 polling mode (no SQS). Edit and replace `ACCOUNT_ID` in `s3_bucket_name`:

```
s3_bucket_name = "burr-tracking-logs-dev-123456789012"
```

Deploy:

```bash
cd terraform
terraform init
terraform plan -var-file=dev.tfvars
terraform apply -var-file=dev.tfvars
```

### Production (prod.tfvars) - S3 + SQS

Uses event-driven mode with SQS. Edit and replace `ACCOUNT_ID`:

```
s3_bucket_name = "burr-tracking-logs-prod-123456789012"
```

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
- BURR_TRACKING_MODE=SQS
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
| s3_bucket_name | S3 bucket name (must be globally unique) | (required) |
| enable_sqs | Create SQS for event-driven tracking | true |
| log_retention_days | Days to retain logs in S3 | 90 |
| snapshot_retention_days | Days to retain DB snapshots | 30 |
| enable_bedrock | Add Bedrock IAM permissions | false |

## Outputs

After apply, useful outputs:

```bash
terraform output s3_bucket_name
terraform output sqs_queue_url
terraform output burr_environment_variables
```

## IAM Least Privilege

The IAM role grants only:

- **S3**: ListBucket, GetBucketLocation, GetObject, PutObject, DeleteObject, HeadObject on the specific bucket
- **SQS** (when enabled): ReceiveMessage, DeleteMessage, GetQueueAttributes on the specific queue
- **Bedrock** (when enabled): InvokeModel, InvokeModelWithResponseStream on specified model ARNs

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

**S3 bucket name already exists**: S3 bucket names are globally unique. Use your account ID or a random suffix.

**SQS policy errors**: Ensure the S3 bucket notification depends on the queue policy. The Terraform handles this with `depends_on`.

**Burr server not receiving events**: Verify BURR_SQS_QUEUE_URL is set and the IAM role has sqs:ReceiveMessage. Check CloudWatch for the SQS consumer.
