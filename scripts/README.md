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

# Burr Release Scripts

This directory contains helper scripts to automate the Apache release workflow.

## Overview

The release process has two phases:

1. **Source-only release** (for Apache voting): Contains source code, build scripts, and UI source—but NO pre-built artifacts
2. **Wheel build** (for PyPI): Built from the source release, includes pre-built UI assets

All packaging configuration lives in `pyproject.toml`:
- `[build-system]` uses `flit_core` as the build backend
- `[tool.flit.sdist]` controls what goes in the source tarball
- Wheel contents are controlled by what exists in `burr/` when `flit build --format wheel` runs

## 1. Create the Source Release Candidate

From the repo root:

```bash
python scripts/release_helper.py <version> <rc-num> <apache-id> [--dry-run] [--build-wheel]
```

Example:

```bash
# Dry run (no git tag or SVN upload)
python scripts/release_helper.py 0.41.0 0 myid --dry-run

# Real release
python scripts/release_helper.py 0.41.0 0 myid

# With optional wheel
python scripts/release_helper.py 0.41.0 0 myid --build-wheel
```

**What it does:**
1. Reads version from `pyproject.toml`
2. Cleans `dist/` directory
3. **Removes `burr/tracking/server/build/`** to ensure no pre-built UI in source tarball
4. Runs `flit build --format sdist`
   - Includes files specified in `[tool.flit.sdist] include`
   - Excludes files specified in `[tool.flit.sdist] exclude`
5. Creates Apache-branded tarball with GPG signatures and SHA512 checksums
6. Tags git as `v{version}-incubating-RC{num}` (unless `--dry-run`)
7. Uploads to Apache SVN (unless `--dry-run`)

**Output:**
- `dist/apache-burr-<version>-incubating.tar.gz` — ASF-branded source tarball
- `dist/apache-burr-<version>-incubating.tar.gz.asc` — GPG signature
- `dist/apache-burr-<version>-incubating.tar.gz.sha512` — SHA512 checksum

## 2. Test the Source Release (Voter Simulation)

This simulates what Apache voters and release managers will do when validating the release.

**Automated testing:**

```bash
bash scripts/simulate_release.sh
```

This script:
1. Cleans `/tmp/burr-release-test/`
2. Extracts the Apache tarball
3. Creates a fresh virtual environment
4. Builds UI artifacts and wheel (next step)
5. Verifies both packages and prints their locations

**Manual testing:**

```bash
cd /tmp
tar -xzf /path/to/dist/apache-burr-<version>-incubating.tar.gz
cd apache-burr-<version>-incubating

# Verify source contents
ls scripts/          # Build scripts should be present
ls telemetry/ui/     # UI source should be present
ls examples/         # Example directories should be present
ls burr/tracking/server/build/  # Should NOT exist (no pre-built UI)

# Create clean environment
python -m venv venv && source venv/bin/activate
pip install -e ".[cli]"
pip install flit

# Build artifacts and wheel (see step 3)
python scripts/build_artifacts.py all --clean
ls dist/*.whl
deactivate
```

Alternatively, instead of manually creating the `venv` and installing burr with `pip install`, you can use
`uv` and use simplified development workflow of uv you can  run the command directly:

```bash
uv run scripts/build_artifacts.py all --clean
ls dist/*.whl
```

This will automatically:

* download the right python version if you do not have python installed
* create virtual environment in local `.venv` directory
* activates the venv
* installs `burr` in editable mode with `dev` dependency group (that contains `cli` extra, `developer` extra
  and `flit` package.
* deactivates the venv

Next time when you run `uv run` it will also automatically sync the environment with latest `pyproject.toml`

## 3. Build Artifacts and Wheel

The `build_artifacts.py` script has three subcommands:

### Build everything (recommended):

```bash
python scripts/build_artifacts.py all --clean
```

This runs both `artifacts` and `wheel` subcommands in sequence.

### Build UI artifacts only:

```bash
python scripts/build_artifacts.py artifacts [--skip-install]
```

**What it does:**
1. Checks for Node.js and npm
2. **Cleans `burr/tracking/server/build/`** to ensure fresh UI build
3. Installs burr from source: `pip install -e .` (unless `--skip-install`)
4. Runs `burr-admin-build-ui`:
   - `npm install --prefix telemetry/ui`
   - `npm run build --prefix telemetry/ui`
   - **Creates `burr/tracking/server/build/`** and copies built UI into it
5. Verifies UI assets exist in `burr/tracking/server/build/`

### Build wheel only (assumes artifacts exist):

```bash
python scripts/build_artifacts.py wheel [--clean]
```

**What it does:**
1. Checks for `flit`
2. Verifies `burr/tracking/server/build/` contains UI assets
3. Optionally cleans `dist/` (with `--clean`)
4. Runs `flit build --format wheel`
   - **Packages all files in `burr/` directory, including `burr/tracking/server/build/`**
   - Does NOT include files outside `burr/` (e.g., `telemetry/ui/`, `scripts/`, `examples/`)
5. Verifies `.whl` file was created

**Output:** `dist/apache_burr-<version>-py3-none-any.whl` (includes bundled UI)

**Note:** Flit normalizes the package name `apache-burr` to `apache_burr` (underscore) in the filename.

## 4. Upload to PyPI

After building the wheel:

```bash
twine upload dist/apache_burr-<version>-py3-none-any.whl
```

**Note:** For PyPI, you may want to publish as `burr` instead of `apache-burr`. See the dual distribution strategy documentation.

## Package Contents Reference

Understanding what goes in each package type:

### Source tarball (`apache-burr-{version}-incubating.tar.gz`)

**Controlled by:** `[tool.flit.sdist]` in `pyproject.toml` + `release_helper.py` cleanup

**Includes:**
- ✅ `burr/` — Full package source code
- ✅ `scripts/` — Build helper scripts (this directory!)
- ✅ `telemetry/ui/` — UI source code (package.json, src/, public/, etc.)
- ✅ `examples/email-assistant/`, `examples/multi-modal-chatbot/`, etc. — Selected example directories
- ✅ `LICENSE`, `NOTICE`, `DISCLAIMER` — Apache license files

**Excludes:**
- ❌ `burr/tracking/server/build/` — Deleted by `release_helper.py` before build
- ❌ `telemetry/ui/node_modules/` — Excluded by `[tool.flit.sdist]`
- ❌ `telemetry/ui/build/`, `telemetry/ui/dist/` — Excluded by `[tool.flit.sdist]`
- ❌ `docs/`, `.git/`, `.github/` — Excluded by `[tool.flit.sdist]`

**How it's built:**
```bash
rm -rf burr/tracking/server/build  # Ensure no pre-built UI
flit build --format sdist           # Build from [tool.flit.sdist] config
```

---

### Wheel (`apache_burr-{version}-py3-none-any.whl`)

**Controlled by:** What exists in `burr/` directory when `flit build --format wheel` runs

**Includes:**
- ✅ `burr/` — Complete package (all `.py` files, `py.typed`, etc.)
- ✅ `burr/tracking/server/build/` — **Pre-built UI assets** (created by `build_artifacts.py`)
- ✅ `burr/tracking/server/demo_data/` — Demo data files

**Excludes:**
- ❌ `telemetry/ui/` — Not in `burr/` package
- ❌ `examples/` — Not in `burr/` package (sdist-only)
- ❌ `scripts/` — Not in `burr/` package (sdist-only)
- ❌ `LICENSE`, `NOTICE`, `DISCLAIMER` — Not needed in wheel (sdist-only)

**How it's built:**
```bash
burr-admin-build-ui                # Creates burr/tracking/server/build/
flit build --format wheel          # Packages everything in burr/
```

---

### Key Insight

The **same `burr/` source directory** produces different outputs based on **when you build** and **what format**:

1. **sdist (source tarball):** Includes external files (`scripts/`, `telemetry/ui/`, `examples/`) via `[tool.flit.sdist]` config, but excludes `burr/tracking/server/build/` because we delete it first.

2. **wheel (binary distribution):** Only packages `burr/` directory contents, but includes `burr/tracking/server/build/` because we create it before building the wheel.
