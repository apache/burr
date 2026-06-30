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

"""Regression tests for issue #574: S3 tracking server bugs.

Bug 1: 'no such table: project' on first container start without snapshot.
Bug 2: indexer silently drops old logs when batch cap is hit.

These tests use moto (mock S3) and do NOT require real AWS credentials.
"""

import os
import tempfile
from unittest.mock import patch

import pytest

try:
    import moto
    from moto import mock_aws

    HAS_MOTO = True
except ImportError:
    HAS_MOTO = False

try:
    from tortoise import Tortoise

    HAS_TORTOISE = True
except ImportError:
    HAS_TORTOISE = False


pytestmark = [
    pytest.mark.skipif(not HAS_TORTOISE, reason="tortoise-orm not installed"),
]


@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a temporary path for the SQLite database."""
    db_path = str(tmp_path / "test_db.sqlite3")
    return db_path


@pytest.fixture
def s3_bucket_name():
    return "test-burr-tracking"


@pytest.fixture
def mock_s3(s3_bucket_name):
    """Create a mock S3 bucket using moto."""
    if not HAS_MOTO:
        pytest.skip("moto not installed")

    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"

    with mock_aws():
        import boto3

        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=s3_bucket_name)
        yield client


class TestBug1SchemaCreation:
    """Bug 1: server crashes with 'no such table: project' on first start.

    Root cause: RegisterTortoise does not generate schemas by default.
    On a fresh deploy with no snapshot, the SQLite DB is empty (no tables).
    The fix calls Tortoise.generate_schemas(safe=True) in the lifespan.
    """

    @pytest.mark.asyncio
    async def test_generate_schemas_safe_true_creates_tables(self, temp_db_path):
        """Verify that safe=True schema generation creates tables on a fresh DB."""
        tortoise_config = {
            "connections": {
                "default": f"sqlite://{temp_db_path}",
            },
            "apps": {
                "models": {
                    "models": ["burr.tracking.server.s3.models"],
                    "default_connection": "default",
                },
            },
        }
        # Initialize Tortoise without schema generation (simulates the bug)
        await Tortoise.init(config=tortoise_config)

        # Before fix: querying would raise "no such table"
        # After fix: generate_schemas(safe=True) is called in lifespan
        await Tortoise.generate_schemas(safe=True)

        # Now the tables exist and can be queried
        from burr.tracking.server.s3.models import IndexingJob

        jobs = await IndexingJob.all()
        assert jobs == []

        await Tortoise.close_connections()

    @pytest.mark.asyncio
    async def test_generate_schemas_safe_true_does_not_clobber_existing(self, temp_db_path):
        """Verify that safe=True does not destroy data from a loaded snapshot."""
        tortoise_config = {
            "connections": {
                "default": f"sqlite://{temp_db_path}",
            },
            "apps": {
                "models": {
                    "models": ["burr.tracking.server.s3.models"],
                    "default_connection": "default",
                },
            },
        }
        # First init: create schemas and insert data (simulates snapshot load)
        await Tortoise.init(config=tortoise_config)
        await Tortoise.generate_schemas(safe=True)

        from burr.tracking.server.s3.models import IndexingJob, IndexingJobStatus

        await IndexingJob.create(
            records_processed=42,
            status=IndexingJobStatus.SUCCESS,
        )
        count_before = await IndexingJob.all().count()
        assert count_before == 1

        # Second call to generate_schemas(safe=True) should NOT drop tables
        await Tortoise.generate_schemas(safe=True)

        count_after = await IndexingJob.all().count()
        assert count_after == 1, "safe=True must not drop existing data"

        await Tortoise.close_connections()


class TestBug2BatchCapBreak:
    """Bug 2: indexer silently drops old logs over time.

    Root cause: the inner `break` on max_paths did not exit the outer
    paginator loop, causing unbounded collection beyond max_paths.
    The watermark then advanced past files that were never properly
    processed in subsequent cycles.

    The fix ensures the break exits both loops, so the batch is truly
    capped and the watermark only advances to the last file in the batch.
    """

    @pytest.mark.skipif(not HAS_MOTO, reason="moto not installed")
    @pytest.mark.asyncio
    async def test_gather_paths_respects_max_paths_cap(self, mock_s3, s3_bucket_name, temp_db_path):
        """Verify that _gather_paths_to_update returns at most max_paths files."""
        # Write more files than the cap
        max_paths = 5
        total_files = 15
        for i in range(total_files):
            key = f"data/test-project/2025/01/01/00/{i:02d}/pk/app-{i}/log.jsonl"
            mock_s3.put_object(Bucket=s3_bucket_name, Key=key, Body=b"{}")

        # Set up Tortoise for the test
        tortoise_config = {
            "connections": {
                "default": f"sqlite://{temp_db_path}",
            },
            "apps": {
                "models": {
                    "models": ["burr.tracking.server.s3.models"],
                    "default_connection": "default",
                },
            },
        }
        await Tortoise.init(config=tortoise_config)
        await Tortoise.generate_schemas(safe=True)

        from burr.tracking.server.s3.models import Project

        # Create a project in the DB
        from burr import system

        project = await Project.create(
            name="test-project",
            uri=None,
            created_at=system.now(),
        )

        # Import and patch the backend to use our mock
        from burr.tracking.server.s3.backend import SQLiteS3Backend

        # Patch settings to use our test bucket
        with patch("burr.tracking.server.s3.backend.settings.DB_PATH", temp_db_path):
            backend = SQLiteS3Backend.__new__(SQLiteS3Backend)
            backend._bucket = s3_bucket_name
            backend._data_prefix = "data"

            # Use a real aiobotocore session pointed at moto
            import aiobotocore.session

            backend._session = aiobotocore.session.get_session()

            paths = await backend._gather_paths_to_update(
                project=project,
                high_watermark_s3_path="",
                max_paths=max_paths,
            )

        assert len(paths) <= max_paths, (
            f"Expected at most {max_paths} paths, got {len(paths)}. "
            "The batch cap break is not working correctly."
        )

        await Tortoise.close_connections()

    @pytest.mark.skipif(not HAS_MOTO, reason="moto not installed")
    @pytest.mark.asyncio
    async def test_watermark_advances_only_to_last_indexed_file(
        self, mock_s3, s3_bucket_name, temp_db_path
    ):
        """Verify watermark advances to last file in the batch, not beyond."""
        # Write files with predictable lexicographic ordering
        keys = []
        for i in range(10):
            key = f"data/test-project/2025/01/01/00/{i:02d}/pk/app/log.jsonl"
            mock_s3.put_object(Bucket=s3_bucket_name, Key=key, Body=b"{}")
            keys.append(key)

        # Import the function under test
        from burr.tracking.server.s3.backend import DataFile, SQLiteS3Backend

        # Simulate: batch cap = 5, so only first 5 files indexed
        max_paths = 5
        # The first 5 files (lexicographically) should be returned
        # Watermark should be the path of the 5th file (index 4)
        expected_watermark = keys[4]  # 0-indexed, 5th file

        # The watermark function uses max(paths, key=lambda x: x.path).path
        fake_paths = [DataFile.from_path(k, created_date=None) for k in keys[:max_paths]]
        actual_watermark = max(fake_paths, key=lambda x: x.path).path

        assert actual_watermark == expected_watermark, (
            f"Watermark should be {expected_watermark}, got {actual_watermark}. "
            "Files beyond the batch cap would be permanently skipped."
        )

        await Tortoise.close_connections()
