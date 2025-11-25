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

resource "aws_alb" "main" {
    name        = "burr-load-balancer"
    subnets         = aws_subnet.public.*.id
    security_groups = [aws_security_group.lb.id]
}

resource "aws_alb_target_group" "app" {
    name        = "burr-target-group"
    port        = 80
    protocol    = "HTTP"
    vpc_id      = aws_vpc.main.id
    target_type = "ip"

    health_check {
        healthy_threshold   = "3"
        interval            = "30"
        protocol            = "HTTP"
        matcher             = "200"
        timeout             = "3"
        path                = var.health_check_path
        unhealthy_threshold = "2"
    }
}

# Redirect all traffic from the ALB to the target group
resource "aws_alb_listener" "front_end" {
  load_balancer_arn = aws_alb.main.id
  port              = var.app_port
  protocol          = "HTTP"

  default_action {
    target_group_arn = aws_alb_target_group.app.id
    type             = "forward"
  }
}
