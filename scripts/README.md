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
| Tests (integration and unit) | ✓ | ✗ | ✗ | Tests ship in the full source archive (`-src.tar.gz`) for voters to build, test, and validate the release. They are not included in the sdist or wheel. |
| READMEs | ✓ | ✓ | ✓ | Standard project metadata files (README.md, LICENSE, NOTICE, DISCLAIMER) are included in all three distributions: tar.gz, sdist, and whl. |
| Documentation | ✓ | ✗ | ✗ | Documentation source is included in the tar.gz for voters to review, but not in the sdist or whl as it is not needed for building or using the package. |
| Deployment templates | ✓ | ✓ | ✓ | Convenience deployment templates are included in tar.gz, sdist, and whl as they are referred to by specific utility commands for deploying that are included in source. |
| Built artifacts (UI, etc...) | ✗ | ✗ | ✓ | These are not source code and are only included in the whl. They are created through a build process from the UI source. Notable examples include the built npm packages. |
| Examples (by default required for demo server) | ✓ | ✓ | ✓ | We have four examples (see pyproject.toml) required by the demo server which can be run by a single command. These are included in tar.gz, sdist, and whl as they are needed for the demo functionality. |
| Other examples | ✓ | ✗ | ✗ | These are included in the tar.gz for voters to review but not included in the sdist or whl as they are not needed to build or run the package. They serve more as documentation. |

## Artifact naming and licence decisions

- **Keep wheel filenames without `incubating`.** Wheels use names such as
  `apache_burr-0.43.0-py3-none-any.whl`, without the proposed `1incubating` build tag.
  They are convenience binaries; the source archive is the voting artifact.
  We retain the exact wheel in Apache dist for provenance and verification against
  the package published to PyPI. This is the project's chosen approach from the
  [dev-list discussion](https://lists.apache.org/thread/7t31297fhwqp9sqo6nvopgf0qw10zy4y);
  it does not clear the Clutch filename warning.
- **Keep `LICENSE-wheel` in the sdist.** Rebuilding a wheel from the sdist builds
  the tracking UI and bundles its JavaScript dependencies. `LICENSE-wheel` supplies
  the acknowledgements for those dependencies and is packaged in the rebuilt wheel
  as `LICENSE`. The sdist's own `LICENSE` describes the source files it ships;
  retaining `LICENSE-wheel` supports the subsequent wheel build.
- **Keep `incubating` in the Apache sdist filename.** The release helper continues
  to produce names such as `apache-burr-0.43.0-incubating-sdist.tar.gz`. This naming
  can interfere with pip inferring the package name and version when installing
  directly from an archive URL. We accept that limitation during incubation rather
  than introduce a temporary naming change, and will revisit it on graduation.
  Install the wheel or the package from PyPI for normal use; extract the source
  archive for the build and verification workflow below.

# Release Process

**Note:** This is a work in progress and subject to change.

## Environment Setup


Prerequisites:
- Python 3.10+
- Release tools (`pip install -e ".[release]"`): Flit for building and Twine for validation.
- GPG key configured for signing
- Node.js + npm for UI builds
- Apache RAT jar for license checking (optional)

```bash
# Install build dependencies
pip install -e ".[release]"
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

# Promote a voted RC from dist/dev to dist/release
python scripts/apache_release.py promote 0.41.0-RC0 your_apache_id
python scripts/apache_release.py promote 0.41.0-RC0 your_apache_id --dry-run
python scripts/apache_release.py promote 0.41.0-RC0 your_apache_id --release-svn-root https://dist.apache.org/repos/dist/release/burr  # TLP path override

# Verify artifacts locally
python scripts/apache_release.py verify 0.41.0 0

# Skip upload step in 'all' command
python scripts/apache_release.py all 0.41.0 0 your_apache_id --no-upload

# Generate release emails from templates
python scripts/apache_release.py vote-email --version 0.41.0 --rc 0
python scripts/apache_release.py result-email --version 0.41.0 --rc 0 --binding-yes 3 --non-binding-yes 2 --binding-no 0 --non-binding-no 1
python scripts/apache_release.py announce-email --version 0.41.0
```

Release wheel filenames follow the [artifact naming decisions](#artifact-naming-and-licence-decisions)
above (for example, `apache_burr-0.43.0-py3-none-any.whl`).
The wheel build temporarily stages `LICENSE-wheel` as `LICENSE` and updates Flit's
licence-file setting, restoring the source files afterward. The verifier checks
the packaged `LICENSE` against `LICENSE-wheel`.

Output: `dist/` directory with tar.gz (archive + sdist), whl, plus .asc and .sha512 files. The wheel is validated with `twine check` to ensure metadata correctness before signing. Install from the whl file to test it out after running the `wheel` subcommand.

## Promoting a voted RC

After an RC vote passes, promote the exact voted artifacts from Apache SVN `dist/dev` into
`dist/release` with:

```bash
python scripts/apache_release.py promote 0.41.0-RC0 your_apache_id
```

What it does:
- checks out the RC directory from `dist/dev` to validate the expected source archive,
  sdist, wheel, and matching `.asc` / `.sha512` files
- refuses to continue if the target release directory already exists
- copies the voted RC directory server-side into a new per-version release directory
  (e.g. `dist/release/incubator/burr/0.41.0`) with a single atomic `svn cp` commit
- leaves any existing release directories and the shared `KEYS` file untouched (additive)
- prints the final PyPI upload command for the sdist and wheel

Use `--dry-run` to preview the actions without committing:

```bash
python scripts/apache_release.py promote 0.41.0-RC0 your_apache_id --dry-run
```

For post-incubation path changes, override the default SVN roots:

```bash
python scripts/apache_release.py promote 0.41.0-RC0 your_apache_id \
  --dev-svn-root https://dist.apache.org/repos/dist/dev/burr \
  --release-svn-root https://dist.apache.org/repos/dist/release/burr
```

## Cleaning up superseded releases

After publishing a new release, remove superseded versions from the active
`dist/release` area. Keep the latest release for each maintained branch and the
shared `KEYS` file. This is separate from promoting an approved RC out of `dist/dev`.

Before removing a version, check its directory at
`https://archive.apache.org/dist/incubator/burr/<version>/` and confirm that all
release artifacts and their `.asc` and `.sha512` files are present. Apache archives
releases automatically, generally within a day of publication; wait until the
archive is complete before proceeding. See the
[Apache release distribution policy](https://infra.apache.org/release-distribution.html#releases-are-archived).

Remove only the superseded version directory using SVN (no checkout required):

```bash
# Replace with the superseded version whose archive you have checked.
OLD_VERSION="<superseded-version>"
svn delete \
  "https://dist.apache.org/repos/dist/release/incubator/burr/${OLD_VERSION}" \
  --username your_apache_id \
  -m "Remove superseded Burr ${OLD_VERSION}; retained in archive.apache.org"

# Verify the current releases and KEYS remain.
svn ls https://dist.apache.org/repos/dist/release/incubator/burr/
```

The URL-based `svn delete` commits immediately. It removes the version from active
distribution while preserving its archived copy; it does not remove the PyPI release.
Update any website links for the retired version to point to its archive location.

## For Voters: Verifying a Release

If you're voting on a release, follow these steps to verify the release candidate:

### Complete Verification Workflow

```bash
# Set version and RC number (example: 0.41.0 RC3)
export VERSION=0.41.0
export RC=3

# 1. Download all artifacts from SVN
svn export https://dist.apache.org/repos/dist/dev/incubator/burr/${VERSION}-incubating-RC${RC}/ burr-rc${RC}
cd burr-rc${RC}

# 2. Import KEYS file and verify all GPG signatures
wget https://downloads.apache.org/incubator/burr/KEYS
gpg --import KEYS

# Verify git archive signature
gpg --verify apache-burr-${VERSION}-incubating-src.tar.gz.asc apache-burr-${VERSION}-incubating-src.tar.gz

# Verify sdist signature
gpg --verify apache-burr-${VERSION}-incubating-sdist.tar.gz.asc apache-burr-${VERSION}-incubating-sdist.tar.gz

# Verify wheel signature
gpg --verify apache_burr-${VERSION}-py3-none-any.whl.asc apache_burr-${VERSION}-py3-none-any.whl

# 3. Verify all SHA512 checksums
sha512sum -c apache-burr-${VERSION}-incubating-src.tar.gz.sha512
sha512sum -c apache-burr-${VERSION}-incubating-sdist.tar.gz.sha512
sha512sum -c apache_burr-${VERSION}-py3-none-any.whl.sha512

# 4. Extract the source archive
tar -xzf apache-burr-${VERSION}-incubating-src.tar.gz
cd apache-burr-${VERSION}-incubating-src/

# 5. Install build dependencies
pip install -e ".[release]"

# 6. Build the wheel from source (this also builds the UI)
python scripts/apache_release.py wheel ${VERSION} ${RC}

# 7. Install and test the wheel in a fresh environment outside the source tree.
# This ensures the editable build-tools installation cannot mask wheel defects.
WHEEL_PATH="$PWD/dist/apache_burr-${VERSION}-py3-none-any.whl"
WHEEL_TEST_DIR=$(mktemp -d)
python -m venv "$WHEEL_TEST_DIR/venv"
source "$WHEEL_TEST_DIR/venv/bin/activate"
cd "$WHEEL_TEST_DIR"
python -m pip install "${WHEEL_PATH}[learn]"
burr

```

The release script signs its output. To build an unsigned wheel manually, start
from the repository root of a clean checkout or an extracted source archive, with
the release tools installed (`python -m pip install -e ".[release]"`). This follows
the same UI, example, licence, and file-exclusion steps as the release helper.
Use the same `SOURCE_DATE_EPOCH` for both builds when comparing them. In a Git
checkout, obtain it with `git show -s --format=%ct HEAD`; for an extracted archive,
set it to the timestamp of the release's source commit before running these steps.

```bash
# Run in a subshell so build settings and the cleanup trap stay local.
(
set -eu
export FLIT_USE_VCS=0
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git show -s --format=%ct HEAD)}"

# 1. Build and copy the UI, replacing any previous output.
npm install --prefix telemetry/ui
npm run build --prefix telemetry/ui
rm -rf burr/tracking/server/build
mkdir -p burr/tracking/server/build
cp -a telemetry/ui/build/. burr/tracking/server/build/

# 2. Back up files that must be restored, even if the build fails.
WHEEL_BACKUP=$(mktemp -d)
cp LICENSE "$WHEEL_BACKUP/LICENSE"
cp pyproject.toml "$WHEEL_BACKUP/pyproject.toml"
mv burr/examples "$WHEEL_BACKUP/examples"
restore_wheel_sources() {
    cp "$WHEEL_BACKUP/LICENSE" LICENSE
    cp "$WHEEL_BACKUP/pyproject.toml" pyproject.toml
    rm -rf burr/examples
    mv "$WHEEL_BACKUP/examples" burr/examples
    if [ -f "$WHEEL_BACKUP/terraform.gitignore" ]; then
        mv "$WHEEL_BACKUP/terraform.gitignore" burr/tracking/server/s3/deployment/terraform/.gitignore
    fi
    rm -rf "$WHEEL_BACKUP"
}
trap restore_wheel_sources EXIT

# 3. Include exactly the examples used by the release helper.
mkdir burr/examples
cp examples/__init__.py burr/examples/
for example in email-assistant multi-modal-chatbot streaming-fastapi deep-researcher hello-world-counter; do
    cp -R "examples/$example" burr/examples/
done

# Match the sdist's exclusion of this VCS file.
if [ -f burr/tracking/server/s3/deployment/terraform/.gitignore ]; then
    mv burr/tracking/server/s3/deployment/terraform/.gitignore "$WHEEL_BACKUP/terraform.gitignore"
fi

# 4. Stage the wheel licence under LICENSE before Flit generates metadata/RECORD.
python - <<'PYTHON'
from pathlib import Path

config = Path("pyproject.toml")
source = config.read_bytes()
wheel = source.replace(
    b'license-files = ["LICENSE-wheel", "NOTICE", "DISCLAIMER"]',
    b'license-files = ["LICENSE", "NOTICE", "DISCLAIMER"]',
)
if wheel == source:
    raise SystemExit("Expected license-files setting not found in pyproject.toml")
config.write_bytes(wheel)
Path("LICENSE").write_bytes(Path("LICENSE-wheel").read_bytes())
PYTHON

# 5. Build; the exit trap restores the source files and examples afterwards.
flit build --format wheel
)
```

The wheel is written to `dist/apache_burr-<version>-py3-none-any.whl`. Validate it
with `python -m twine check <wheel-path>` and test it in a fresh environment
outside the source tree, as shown above. To compare it with the automated build:

```bash
python scripts/verify_apache_artifacts.py compare-wheels <automated-wheel> <manual-wheel>
```

See the "Verification" section below for more detailed verification steps including license checking.

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
python scripts/verify_apache_artifacts.py list-contents dist/apache-burr-0.41.0-incubating-src.tar.gz
python scripts/verify_apache_artifacts.py list-contents dist/apache_burr-0.41.0-py3-none-any.whl
```

## Local Development

Simpler workflow for building wheels during development without signing or creating full release artifacts. Useful for testing packaging changes or building wheels to install locally.

For local wheel building/testing (simpler, no signing):

```bash
python scripts/build_artifacts.py build-ui    # Build UI only
python scripts/build_artifacts.py wheel       # Build wheel with UI
```

## Milestone Management

Merged PRs are tracked against release milestones so changelog generation can tell which changes shipped in which release.

- Milestone titles use the `X.Y.Z` naming convention, for example `0.43.0`
- PRs merged to `main` are assigned the earliest open `X.Y.Z` milestone
- PRs merged to release/test branches use the milestone implied by the branch name, including:
  - `release-X.Y.Z`
  - `apache-burr-X.Y.Z-release`
  - `vX.Y-test` or `vX.Y.Z-test`

The `.github/workflows/milestone-management.yml` workflow also supports manual milestone creation via `workflow_dispatch`. Provide one or more comma- or newline-separated `X.Y.Z` versions in the `versions` input to create or re-open upcoming release milestones.
