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

"""Tests for the Burr UI on AWS deployment example.

Validate structure and security without provisioning real infrastructure.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

EXAMPLE_DIR = Path(__file__).parents[2] / "examples" / "deployment" / "aws" / "burr-ui"


class TestExampleStructure:
    @pytest.mark.parametrize(
        "rel",
        [
            "README.md",
            "Dockerfile",
            "requirements.txt",
            "terraform/main.tf",
            "terraform/variables.tf",
            "terraform/outputs.tf",
            "terraform/versions.tf",
            "terraform/modules/networking/main.tf",
            "terraform/modules/networking/variables.tf",
            "terraform/modules/networking/outputs.tf",
            "terraform/modules/compute/main.tf",
            "terraform/modules/compute/variables.tf",
            "terraform/modules/compute/outputs.tf",
            "terraform/modules/compute/templates/user_data.sh.tpl",
            "terraform/modules/iam/main.tf",
            "terraform/modules/iam/variables.tf",
            "terraform/modules/iam/outputs.tf",
        ],
    )
    def test_required_file_exists(self, rel):
        assert (EXAMPLE_DIR / rel).is_file(), f"missing {rel}"


class TestApacheLicenseHeaders:
    @pytest.mark.parametrize(
        "rel",
        [
            "README.md",
            "Dockerfile",
            "requirements.txt",
            "terraform/main.tf",
            "terraform/variables.tf",
            "terraform/outputs.tf",
            "terraform/versions.tf",
            "terraform/environments/dev.tfvars",
            "terraform/environments/prod.tfvars",
            "terraform/modules/networking/main.tf",
            "terraform/modules/networking/variables.tf",
            "terraform/modules/networking/outputs.tf",
            "terraform/modules/compute/main.tf",
            "terraform/modules/compute/variables.tf",
            "terraform/modules/compute/outputs.tf",
            "terraform/modules/compute/templates/user_data.sh.tpl",
            "terraform/modules/iam/main.tf",
            "terraform/modules/iam/variables.tf",
            "terraform/modules/iam/outputs.tf",
        ],
    )
    def test_has_header(self, rel):
        p = EXAMPLE_DIR / rel
        if p.exists():
            assert "Licensed to the Apache Software Foundation" in p.read_text(
                encoding="utf-8"
            ), f"{rel} is missing the Apache license header"


class TestBucketParameterization:
    def test_s3_bucket_variable_declared(self):
        v = (EXAMPLE_DIR / "terraform" / "variables.tf").read_text()
        assert "s3_bucket_name" in v

    def test_user_data_sets_bucket_env(self):
        ud = (
            EXAMPLE_DIR
            / "terraform"
            / "modules"
            / "compute"
            / "templates"
            / "user_data.sh.tpl"
        ).read_text()
        assert "BURR_S3_BUCKET" in ud
        assert "burr" in ud


class TestSecurity:
    def test_imdsv2_enforced(self):
        c = (EXAMPLE_DIR / "terraform" / "modules" / "compute" / "main.tf").read_text()
        assert "http_tokens" in c and "required" in c

    def test_ebs_encrypted(self):
        c = (EXAMPLE_DIR / "terraform" / "modules" / "compute" / "main.tf").read_text()
        assert "encrypted" in c and "true" in c

    def test_no_ingress_rules(self):
        """With SSM access, the security group should have NO ingress rules."""
        net_main = (
            EXAMPLE_DIR / "terraform" / "modules" / "networking" / "main.tf"
        ).read_text()
        # There should be no aws_security_group_rule with type = "ingress"
        assert (
            'type              = "ingress"' not in net_main
        ), "Security group should have no ingress rules (SSM access only)"

    def test_iam_read_only(self):
        """IAM policy should only have read actions, no write/delete."""
        iam_main = (
            EXAMPLE_DIR / "terraform" / "modules" / "iam" / "main.tf"
        ).read_text()
        assert "s3:GetObject" in iam_main
        assert "s3:PutObject" not in iam_main
        assert "s3:DeleteObject" not in iam_main

    def test_ssm_core_policy_attached(self):
        """Instance must have AmazonSSMManagedInstanceCore for SSM access."""
        iam_main = (
            EXAMPLE_DIR / "terraform" / "modules" / "iam" / "main.tf"
        ).read_text()
        assert "AmazonSSMManagedInstanceCore" in iam_main


class TestTerraformValidate:
    @pytest.fixture(autouse=True)
    def _skip_if_no_terraform(self):
        if shutil.which("terraform") is None:
            pytest.skip("terraform not installed")
        try:
            result = subprocess.run(["terraform", "version"], capture_output=True)
        except FileNotFoundError:
            pytest.skip("terraform not installed")
        if result.returncode != 0:
            pytest.skip("terraform not installed")

    def test_fmt(self):
        r = subprocess.run(
            ["terraform", "fmt", "-check", "-recursive"],
            cwd=EXAMPLE_DIR / "terraform",
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, f"terraform fmt failed:\n{r.stdout}"

    def test_validate(self):
        subprocess.run(
            ["terraform", "init", "-backend=false"],
            cwd=EXAMPLE_DIR / "terraform",
            capture_output=True,
        )
        r = subprocess.run(
            ["terraform", "validate"],
            cwd=EXAMPLE_DIR / "terraform",
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, f"terraform validate failed:\n{r.stderr}"
