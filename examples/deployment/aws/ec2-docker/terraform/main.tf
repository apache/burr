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
    Project     = "burr-ec2-docker"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

module "networking" {
  source = "./modules/networking"

  environment  = var.environment
  app_port     = var.app_port
  allowed_cidr = var.allowed_cidr
}

module "compute" {
  source = "./modules/compute"

  environment       = var.environment
  instance_type     = var.instance_type
  key_name          = var.key_name
  app_port          = var.app_port
  security_group_id = module.networking.security_group_id
  enable_monitoring = var.enable_monitoring
  root_volume_size  = var.root_volume_size
}
