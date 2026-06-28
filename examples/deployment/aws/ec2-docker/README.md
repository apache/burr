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

# Deploy Burr on AWS EC2 with Docker

Deploy a containerized Burr application on an AWS EC2 instance, provisioned with Terraform.

## Overview

This example deploys:
- A FastAPI server wrapping a simple Burr counter application
- Running inside a Docker container on an EC2 instance
- Infrastructure provisioned via Terraform (VPC default, security group, EC2)

## Prerequisites

- AWS CLI configured with credentials
- Terraform >= 1.5 installed
- Docker installed (for local testing)
- An EC2 key pair created in your target region

## Quick Start (Local)

Build and run locally without any AWS resources:

```bash
cd examples/deployment/aws/ec2-docker

docker build -t burr-ec2-example .
docker run -p 8000:8000 burr-ec2-example
```

Test the endpoints:

```bash
# Health check
curl http://localhost:8000/health

# Run the counter app (counts up to 5)
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"number": 5}'
```

Alternatively, use Docker Compose:

```bash
docker compose up --build
```

## Deploy to AWS

1. Navigate to the Terraform directory:

```bash
cd terraform
```

2. Copy `dev.tfvars` and set your values:

```bash
cp dev.tfvars my.tfvars
```

Edit `my.tfvars` and set:
- `key_name` — your EC2 key pair name
- `allowed_cidr` — your IP address in CIDR notation (e.g. `203.0.113.50/32`)

3. Initialize and apply:

```bash
terraform init
terraform apply -var-file=my.tfvars
```

4. Wait approximately 2-3 minutes for the instance to boot, install Docker, and start the container.

5. Access the application:

```bash
# Get the URL
terraform output app_url

# Test it
curl http://<public_ip>:8000/health
curl -X POST http://<public_ip>:8000/run -H "Content-Type: application/json" -d '{"number": 3}'
```

## How it Works

- Terraform provisions a security group and EC2 instance
- The `user_data.sh` script runs on first boot:
  - Installs Docker and Docker Compose
  - Clones the repository
  - Builds the Docker image
  - Runs the container with `--restart=unless-stopped`
- The app exposes port 8000 (configurable via `app_port` variable)

## Verify the Deployment

```bash
# Health check
curl http://<public_ip>:8000/health
# Expected: {"status": "ok"}

# Run counter
curl -X POST http://<public_ip>:8000/run \
  -H "Content-Type: application/json" \
  -d '{"number": 3}'
# Expected: {"counter": 3, "counter_limit": 3}
```

## Teardown

```bash
terraform destroy -var-file=my.tfvars
```

## Security

- Ingress rules use `var.allowed_cidr` — you must set this to your IP. Do not use `0.0.0.0/0`.
- The Burr tracking UI is **not exposed** in this example. If you add it, place it behind
  authentication (e.g. ALB with Cognito) or restrict access to a VPN/private subnet.
- For production, use HTTPS via ACM + Application Load Balancer.
- Do not commit `.tfstate` files — they are gitignored.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Instance not reachable | Check that `allowed_cidr` matches your current IP |
| App not starting | SSH in and check `docker logs burr-app` |
| Terraform state conflicts | Do not share `.tfstate` between developers |

## Production Notes

- For persistent state across container restarts, add a volume mount or use
  [S3 tracking](https://burr.apache.org/concepts/aws-tracking/)
- Consider an Auto Scaling Group for high availability
- Use a private subnet + NAT gateway for instances that don't need direct public access
