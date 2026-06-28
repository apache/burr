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

"""Tests for the EC2 + Docker deployment example.

These validate the example is well-formed and the app runs locally.
They do NOT provision real AWS infrastructure.
"""

import sys
from pathlib import Path

import pytest

EXAMPLE_DIR = Path(__file__).parents[2] / "examples" / "deployment" / "aws" / "ec2-docker"


class TestExampleStructure:
    """Validate the example has all required files."""

    def test_readme_exists(self):
        assert (EXAMPLE_DIR / "README.md").is_file()

    def test_dockerfile_exists(self):
        assert (EXAMPLE_DIR / "Dockerfile").is_file()

    def test_requirements_exists(self):
        assert (EXAMPLE_DIR / "requirements.txt").is_file()

    def test_docker_compose_exists(self):
        assert (EXAMPLE_DIR / "docker-compose.yml").is_file()

    def test_counter_app_exists(self):
        assert (EXAMPLE_DIR / "app" / "counter_app.py").is_file()

    def test_server_exists(self):
        assert (EXAMPLE_DIR / "app" / "server.py").is_file()

    def test_terraform_main_exists(self):
        assert (EXAMPLE_DIR / "terraform" / "main.tf").is_file()

    def test_terraform_versions_exists(self):
        assert (EXAMPLE_DIR / "terraform" / "versions.tf").is_file()

    def test_terraform_variables_exists(self):
        assert (EXAMPLE_DIR / "terraform" / "variables.tf").is_file()

    def test_terraform_outputs_exists(self):
        assert (EXAMPLE_DIR / "terraform" / "outputs.tf").is_file()

    def test_networking_module_exists(self):
        assert (EXAMPLE_DIR / "terraform" / "modules" / "networking" / "main.tf").is_file()
        assert (EXAMPLE_DIR / "terraform" / "modules" / "networking" / "variables.tf").is_file()
        assert (EXAMPLE_DIR / "terraform" / "modules" / "networking" / "outputs.tf").is_file()

    def test_compute_module_exists(self):
        assert (EXAMPLE_DIR / "terraform" / "modules" / "compute" / "main.tf").is_file()
        assert (EXAMPLE_DIR / "terraform" / "modules" / "compute" / "variables.tf").is_file()
        assert (EXAMPLE_DIR / "terraform" / "modules" / "compute" / "outputs.tf").is_file()

    def test_user_data_template_exists(self):
        assert (EXAMPLE_DIR / "terraform" / "modules" / "compute" / "templates" / "user_data.sh.tpl").is_file()

    def test_environment_tfvars_exist(self):
        assert (EXAMPLE_DIR / "terraform" / "environments" / "dev.tfvars").is_file()
        assert (EXAMPLE_DIR / "terraform" / "environments" / "prod.tfvars").is_file()


class TestApacheLicenseHeaders:
    """Every file must have the Apache license header."""

    @pytest.mark.parametrize(
        "filename",
        [
            "README.md",
            "Dockerfile",
            "requirements.txt",
            "docker-compose.yml",
            "app/__init__.py",
            "app/counter_app.py",
            "app/server.py",
            "terraform/main.tf",
            "terraform/versions.tf",
            "terraform/variables.tf",
            "terraform/outputs.tf",
            "terraform/environments/dev.tfvars",
            "terraform/environments/prod.tfvars",
            "terraform/modules/networking/main.tf",
            "terraform/modules/networking/variables.tf",
            "terraform/modules/networking/outputs.tf",
            "terraform/modules/compute/main.tf",
            "terraform/modules/compute/variables.tf",
            "terraform/modules/compute/outputs.tf",
            "terraform/modules/compute/templates/user_data.sh.tpl",
        ],
    )
    def test_file_has_license_header(self, filename):
        path = EXAMPLE_DIR / filename
        if path.exists():
            content = path.read_text()
            assert "Licensed to the Apache Software Foundation" in content, (
                f"{filename} is missing the Apache license header"
            )


class TestAppRunsLocally:
    """The counter app logic works without infrastructure."""

    def test_counter_app_import_and_run(self):
        sys.path.insert(0, str(EXAMPLE_DIR))
        try:
            from app.counter_app import application

            app = application(3)
            _, _, state = app.run(halt_after=["result"])
            assert state["counter"] == 3
        finally:
            sys.path.pop(0)

    def test_counter_app_default(self):
        sys.path.insert(0, str(EXAMPLE_DIR))
        try:
            from app.counter_app import application

            app = application()
            _, _, state = app.run(halt_after=["result"])
            assert state["counter"] == 10
        finally:
            sys.path.pop(0)


class TestSecurityGroup:
    """Terraform does not open ingress to 0.0.0.0/0."""

    def test_no_open_cidr_in_ingress_rules(self):
        """Networking module must not have 0.0.0.0/0 in ingress rules."""
        net_main = (EXAMPLE_DIR / "terraform" / "modules" / "networking" / "main.tf").read_text()
        # Only the egress rule should reference 0.0.0.0/0
        for line in net_main.splitlines():
            if "0.0.0.0/0" in line:
                # Verify it's in the egress resource, not ingress
                assert "egress" in line or "egress_all" in net_main[
                    max(0, net_main.index(line.strip()) - 200):net_main.index(line.strip())
                ], f"Found 0.0.0.0/0 in non-egress context: {line.strip()}"

    def test_allowed_cidr_validation_exists(self):
        """Root variables.tf must validate that allowed_cidr is not 0.0.0.0/0."""
        vars_tf = (EXAMPLE_DIR / "terraform" / "variables.tf").read_text()
        assert '!= "0.0.0.0/0"' in vars_tf, (
            "variables.tf must have a validation preventing 0.0.0.0/0"
        )

    def test_imdsv2_enforced(self):
        """Compute module must enforce IMDSv2 (http_tokens = required)."""
        compute_main = (EXAMPLE_DIR / "terraform" / "modules" / "compute" / "main.tf").read_text()
        assert 'http_tokens' in compute_main and 'required' in compute_main, (
            "Compute module must enforce IMDSv2 with http_tokens = required"
        )

    def test_ebs_encryption_enabled(self):
        """Root volume must be encrypted."""
        compute_main = (EXAMPLE_DIR / "terraform" / "modules" / "compute" / "main.tf").read_text()
        assert "encrypted" in compute_main and "true" in compute_main, (
            "Root EBS volume must have encrypted = true"
        )
