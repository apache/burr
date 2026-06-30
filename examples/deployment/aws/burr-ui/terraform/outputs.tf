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

output "instance_id" {
  description = "EC2 instance ID (use with SSM port-forward)"
  value       = module.compute.instance_id
}

output "private_ip" {
  description = "Private IP of the Burr UI server"
  value       = module.compute.private_ip
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.networking.vpc_id
}

output "ssm_port_forward_command" {
  description = "Command to access the Burr UI via SSM port forwarding"
  value       = "aws ssm start-session --target ${module.compute.instance_id} --document-name AWS-StartPortForwardingSession --parameters '{\"portNumber\":[\"7241\"],\"localPortNumber\":[\"7241\"]}'"
}

output "ui_url" {
  description = "URL to access the Burr UI after port forwarding"
  value       = "http://localhost:7241"
}
