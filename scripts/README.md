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

# Policy on source versus distribution

Apache Burr is an apache-incubating project. As such, we intend to follow all Apache guidelines to
both the spirit (and when applicable) the letter.

That said, there is occasional ambiguity. Thus we aim to clarify with a reasonable and consistently maintained
approach. The question that we found most ambiguous when determining our release process is
1. What counts as source code, and should thus be included in the "sdist" (the source-only distribution)
2. What should be included in the build?

Specifically, we set the following guidelines:

| | source (to vote on) -- tar.gz | sdist -- source used to build | whl file | Reasoning |
|---|---|---|---|---|
| Build Scripts | ✓ | ✓ | ✗ | Included in tar.gz and sdist as they are needed to reproduce the build, but not in the whl. These are only meant to be consumed by developers/pod members. |
| Library Source code | ✓ | ✓ | ✓ | Core library source code is included in all three distributions: tar.gz, sdist, and whl. |
| Tests (integration and unit) | ✓ | ✓ | ✗ | We expect users/PMC to download the source distribution, build from source, run the tests, and validate. Thus we include in the tar.gz and sdist, but not in the whl. |
| READMEs | ✓ | ✓ | ✓ | Standard project metadata files (README.md, LICENSE, NOTICE, DISCLAIMER) are included in all three distributions: tar.gz, sdist, and whl. |
| Documentation | ✓ | ✗ | ✗ | Documentation source is included in the tar.gz for voters to review, but not in the sdist or whl as it is not needed for building or using the package. |
| Deployment templates | ✓ | ✓ | ✓ | Convenience deployment templates are included in tar.gz, sdist, and whl as they are referred to by specific utility commands for deploying that are included in source. |
| Built artifacts (UI, etc...) | ✗ | ✗ | ✓ | These are not source code and are only included in the whl. They are created through a build process from the UI source. Notable examples include the built npm packages. |
| Examples (by default required for demo server) | ✓ | ✓ | ✓ | We have four examples (see pyproject.toml) required by the demo server which can be run by a single command. These are included in tar.gz, sdist, and whl as they are needed for the demo functionality. |
| Other examples | ✓ | ✗ | ✗ | These are included in the tar.gz for voters to review but not included in the sdist or whl as they are not needed to build or run the package. They serve more as documentation. |




# Release Process

**Note:** This is a work in progress and subject to change.

## Environment Setup


Prerequisites:
- Python 3.9+
- `flit` for building (`pip install flit`)
- GPG key configured for signing
- Node.js + npm for UI builds
- Apache RAT jar for license checking (optional)

```bash
# Install build dependencies
pip install flit
pip install -e ".[cli]"  # Installs burr-admin-build-ui command

# Verify GPG setup
gpg --list-secret-keys

# Build UI assets (one-time or when UI changes)
cd telemetry/ui && npm install && npm run build && cd ../..
```

## Building Artifacts

Creates the three required distributions: git archive (voting artifact), sdist (source distribution), and wheel (binary distribution). All artifacts are automatically signed with GPG and checksummed with SHA512. The `all` command is the typical workflow - it builds everything in sequence.

Main release script: `scripts/apache_release.py`

```bash
# Full release build (creates all artifacts, signs, checksums, and generates vote email)
# Note: version, rc_num, and apache_id are POSITIONAL arguments
python scripts/apache_release.py all 0.41.0 0 your_apache_id

# Individual steps
python scripts/apache_release.py archive 0.41.0 0      # Git archive
python scripts/apache_release.py sdist 0.41.0 0        # Source dist
python scripts/apache_release.py wheel 0.41.0 0        # Wheel dist

# Upload to SVN
python scripts/apache_release.py upload 0.41.0 0 your_apache_id
python scripts/apache_release.py upload 0.41.0 0 your_apache_id --dry-run  # Test first

# Verify artifacts locally
python scripts/apache_release.py verify 0.41.0 0

# Skip upload step in 'all' command
python scripts/apache_release.py all 0.41.0 0 your_apache_id --no-upload
```

Output: `dist/` directory with tar.gz (archive + sdist), whl, plus .asc and .sha512 files. Install from the whl file to test it out after runnig the `wheel` subcommand.

## Verification

Validate artifacts before uploading or voting. Checks GPG signatures, SHA512 checksums, archive integrity, and license compliance with Apache RAT. The `list-contents` command is useful for inspecting what's actually packaged in each artifact.

Verification script: `scripts/verify_apache_artifacts.py`

### Prerequisites

For license verification, you'll need Apache RAT. Download it from:

```bash
# Download Apache RAT jar
curl -O https://repo1.maven.org/maven2/org/apache/rat/apache-rat/0.15/apache-rat-0.15.jar
```

Or download manually from: https://repo1.maven.org/maven2/org/apache/rat/apache-rat/0.15/

### Running Verification

```bash
# Verify signatures and checksums
python scripts/verify_apache_artifacts.py signatures

# Verify licenses (requires Apache RAT)
python scripts/verify_apache_artifacts.py licenses --rat-jar apache-rat-0.15.jar

# Verify everything
python scripts/verify_apache_artifacts.py all --rat-jar apache-rat-0.15.jar

# Inspect artifact contents
python scripts/verify_apache_artifacts.py list-contents dist/apache-burr-0.41.0.tar.gz
python scripts/verify_apache_artifacts.py list-contents dist/apache_burr-0.41.0-py3-none-any.whl
```

## Local Development

Simpler workflow for building wheels during development without signing or creating full release artifacts. Useful for testing packaging changes or building wheels to install locally.

For local wheel building/testing (simpler, no signing):

```bash
python scripts/build_artifacts.py build-ui    # Build UI only
python scripts/build_artifacts.py wheel       # Build wheel with UI
```
