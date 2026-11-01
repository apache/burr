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

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

locals {
  common_tags = {
    Project     = "burr-ui-server"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

module "networking" {
  source = "./modules/networking"

  environment = var.environment
  vpc_cidr    = var.vpc_cidr
  aws_region  = var.aws_region
}

module "iam" {
  source = "./modules/iam"

  environment    = var.environment
  s3_bucket_name = var.s3_bucket_name
}

module "compute" {
  source = "./modules/compute"

  environment          = var.environment
  instance_type        = var.instance_type
  root_volume_size     = var.root_volume_size
  s3_bucket_name       = var.s3_bucket_name
  subnet_id            = module.networking.private_subnet_id
  security_group_id    = module.networking.security_group_id
  instance_profile_arn = module.iam.instance_profile_arn
}
