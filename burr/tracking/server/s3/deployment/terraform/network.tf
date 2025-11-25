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

# network.tf

# Fetch AZs in the current region
data "aws_availability_zones" "available" {
}

resource "aws_vpc" "main" {
    # cidr_block = "172.17.0.0/16"
    cidr_block = "172.31.16.0/20"
    # ipv4_netmask_length = 20
}

# Create var.az_count private subnets, each in a different AZ
resource "aws_subnet" "private" {
    count             = var.az_count
    cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
    availability_zone = data.aws_availability_zones.available.names[count.index]
    vpc_id            = aws_vpc.main.id
}

# Create var.az_count public subnets, each in a different AZ
resource "aws_subnet" "public" {
    count                   = var.az_count
    cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, var.az_count + count.index)
    availability_zone       = data.aws_availability_zones.available.names[count.index]
    vpc_id                  = aws_vpc.main.id
    map_public_ip_on_launch = true
}

# Internet Gateway for the public subnet
resource "aws_internet_gateway" "gw" {
    vpc_id = aws_vpc.main.id
}

# Route the public subnet traffic through the IGW
resource "aws_route" "internet_access" {
    route_table_id         = aws_vpc.main.main_route_table_id
    destination_cidr_block = "0.0.0.0/0"
    gateway_id             = aws_internet_gateway.gw.id
}

# Create a NAT gateway with an Elastic IP for each private subnet to get internet connectivity
resource "aws_eip" "gw" {
    count      = var.az_count
    domain = "vpc"
    depends_on = [aws_internet_gateway.gw]
}

resource "aws_nat_gateway" "gw" {
    count         = var.az_count
    subnet_id     = element(aws_subnet.public.*.id, count.index)
    allocation_id = element(aws_eip.gw.*.id, count.index)
}

# Create a new route table for the private subnets, make it route non-local traffic through the NAT gateway to the internet
resource "aws_route_table" "private" {
    count  = var.az_count
    vpc_id = aws_vpc.main.id

    route {
        cidr_block     = "0.0.0.0/0"
        nat_gateway_id = element(aws_nat_gateway.gw.*.id, count.index)
    }
}

# Explicitly associate the newly created route tables to the private subnets (so they don't default to the main route table)
resource "aws_route_table_association" "private" {
    count          = var.az_count
    subnet_id      = element(aws_subnet.private.*.id, count.index)
    route_table_id = element(aws_route_table.private.*.id, count.index)
}
