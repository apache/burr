#!/usr/bin/env python3
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
"""Generate the third-party section of LICENSE-wheel.

The wheel ships one piece of content that is not Burr source: the compiled
tracking UI at ``burr/tracking/server/build/assets/index-*.js``. That bundle
contains code from a large number of npm packages, and ASF policy requires
the binary distribution's LICENSE to reflect what the binary actually
contains.

Rather than maintain that list by hand (it drifts silently on every
dependency bump), this script derives it from the build itself: it asks vite
for a sourcemap, reads the ``sources`` array to find every ``node_modules``
file that was compiled into the bundle, resolves each one to its owning
package, and emits a license section listing each package with its license
and copyright.

Everything in LICENSE-wheel above the generated marker is hand-maintained and
left untouched; everything from the marker to end-of-file is regenerated.

Usage::

    # regenerate LICENSE-wheel in place (requires telemetry/ui/node_modules)
    python scripts/generate_wheel_license.py

    # fail if LICENSE-wheel is out of date -- for CI
    python scripts/generate_wheel_license.py --check

    # reuse a sourcemap from an earlier build instead of rebuilding
    python scripts/generate_wheel_license.py --sourcemap path/to/index-XXXX.js.map
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(REPO_ROOT, "telemetry", "ui")
LICENSE_WHEEL = os.path.join(REPO_ROOT, "LICENSE-wheel")

MARKER = "THIRD-PARTY COMPONENTS BUNDLED IN THIS BINARY DISTRIBUTION"
RULE = "=" * 70
SEPARATOR = "-" * 70

COPYRIGHT_RE = re.compile(r"^.*copyright.*$", re.IGNORECASE | re.MULTILINE)


def build_sourcemap(out_dir: str) -> str:
    """Run a sourcemap build of the UI and return the path to the JS map."""
    if not os.path.isdir(os.path.join(UI_DIR, "node_modules")):
        sys.exit(
            f"error: {UI_DIR}/node_modules is missing.\n"
            "Run `npm ci` in telemetry/ui first, or pass --sourcemap."
        )
    subprocess.run(
        ["npx", "vite", "build", "--sourcemap", "--outDir", out_dir],
        cwd=UI_DIR,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    maps = glob.glob(os.path.join(out_dir, "assets", "*.js.map"))
    if not maps:
        sys.exit(f"error: no .js.map produced under {out_dir}/assets")
    return max(maps, key=os.path.getsize)


def bundled_packages(sourcemap_path: str) -> dict[str, str]:
    """Map package name -> package root for everything compiled into the bundle."""
    sourcemap = json.load(open(sourcemap_path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(sourcemap_path))
    found: dict[str, str] = {}
    for source in sourcemap.get("sources", []):
        if "node_modules/" not in source:
            continue
        directory = os.path.dirname(os.path.normpath(os.path.join(base, source)))
        # Climb to the package root. Some packages ship stub package.json files
        # in subdirectories (@babel/runtime/helpers/esm, react-icons/fa) that
        # carry no "name" -- keep climbing until a named one turns up.
        while "node_modules" in directory:
            manifest = os.path.join(directory, "package.json")
            if os.path.exists(manifest):
                try:
                    name = json.load(open(manifest, encoding="utf-8")).get("name")
                except (OSError, ValueError):
                    name = None
                if name:
                    found.setdefault(name, directory)
                    break
            directory = os.path.dirname(directory)
    return found


def read_package(name: str, directory: str) -> dict:
    manifest = json.load(open(os.path.join(directory, "package.json"), encoding="utf-8"))
    license_id = manifest.get("license") or manifest.get("licenses") or "UNKNOWN"
    if isinstance(license_id, list):
        license_id = ",".join(
            entry.get("type", str(entry)) if isinstance(entry, dict) else str(entry)
            for entry in license_id
        )
    if isinstance(license_id, dict):
        license_id = license_id.get("type", "UNKNOWN")

    text = None
    for filename in sorted(os.listdir(directory)):
        if filename.upper().split(".")[0] in ("LICENSE", "LICENCE", "COPYING"):
            try:
                text = open(
                    os.path.join(directory, filename), encoding="utf-8", errors="replace"
                ).read()
            except OSError:
                text = None
            break

    return {
        "name": name,
        "version": manifest.get("version", ""),
        "license": str(license_id),
        "text": text,
    }


def copyright_lines(text: str | None) -> list[str]:
    if not text:
        return []
    out = []
    for line in COPYRIGHT_RE.findall(text):
        line = line.strip().strip("*").strip()
        # Skip all-caps fragments of the warranty disclaimer, which also
        # contain the word COPYRIGHT ("...COPYRIGHT HOLDERS BE LIABLE...").
        if not line or line.isupper() or "copyright ownership" in line.lower():
            continue
        if line.lower().startswith(("copyright", "(c)", "©")):
            out.append(line)
    seen: set[str] = set()
    return [line for line in out if not (line in seen or seen.add(line))]


def canonical_text(text: str | None) -> str:
    """License body with copyright lines stripped, so identical bodies collapse."""
    if not text:
        return ""
    body = " ".join(line for line in text.splitlines() if not COPYRIGHT_RE.match(line))
    return re.sub(r"\s+", " ", body).strip()


def render(packages: list[dict]) -> str:
    by_license: dict[str, list[dict]] = collections.defaultdict(list)
    for package in packages:
        by_license[package["license"]].append(package)

    lines: list[str] = []
    emit = lines.append
    emit(RULE)
    emit(MARKER)
    emit("(generated by scripts/generate_wheel_license.py -- do not edit by hand)")
    emit(RULE)
    emit("")
    emit("The file burr/tracking/server/build/assets/index-*.js in this wheel is")
    emit("a compiled bundle produced from telemetry/ui. In addition to Apache")
    emit("Burr's own source, it contains code from the third-party packages")
    emit("listed below, under the licenses shown. None of these packages ships")
    emit("a NOTICE file, so no NOTICE content is carried over from them.")
    emit("")

    for license_id in sorted(by_license):
        group = sorted(by_license[license_id], key=lambda p: p["name"])
        emit(SEPARATOR)
        emit(f"The following components are licensed under the {license_id} license:")
        emit("")
        for package in group:
            if package["text"]:
                emit(f"  {package['name']}@{package['version']}")
            else:
                emit(f"  {package['name']}@{package['version']}")
                emit(f"      [no license file shipped; declared as {license_id} in package.json]")
            for line in copyright_lines(package["text"])[:3]:
                emit(f"      {line}")
        emit("")

        bodies: dict[str, str] = {}
        for package in group:
            if package["text"]:
                bodies.setdefault(canonical_text(package["text"]), package["text"])
        for index, body in enumerate(bodies.values(), 1):
            label = f"{license_id} license text"
            if len(bodies) > 1:
                label += f" (variant {index})"
            emit(f"  --- {label} ---")
            emit("")
            for line in body.rstrip().splitlines():
                emit(f"  {line}" if line.strip() else "")
            emit("")

    return "\n".join(lines).rstrip() + "\n"


def splice(existing: str, generated: str) -> str:
    """Replace everything from the generated marker onward."""
    index = existing.find(RULE + "\n" + MARKER)
    head = existing if index == -1 else existing[:index]
    return head.rstrip() + "\n\n" + generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if LICENSE-wheel is out of date instead of rewriting it",
    )
    parser.add_argument(
        "--sourcemap",
        help="use an existing *.js.map instead of running a fresh vite build",
    )
    args = parser.parse_args()

    temp_dir = None
    try:
        if args.sourcemap:
            sourcemap_path = args.sourcemap
        else:
            temp_dir = tempfile.mkdtemp(prefix="burr-license-build-")
            sourcemap_path = build_sourcemap(temp_dir)

        found = bundled_packages(sourcemap_path)
        if not found:
            sys.exit("error: no node_modules sources found in the sourcemap")
        packages = [read_package(name, path) for name, path in sorted(found.items())]
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    generated = render(packages)
    existing = open(LICENSE_WHEEL, encoding="utf-8").read()
    updated = splice(existing, generated)

    unknown = [p["name"] for p in packages if p["license"] in ("UNKNOWN", "")]
    print(f"bundled npm packages: {len(packages)}")
    counts = collections.Counter(p["license"] for p in packages)
    for license_id, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {license_id}")
    if unknown:
        print(f"warning: no license declared for: {', '.join(unknown)}", file=sys.stderr)

    if args.check:
        if updated != existing:
            print(
                "\nLICENSE-wheel is out of date. Run:\n"
                "  python scripts/generate_wheel_license.py",
                file=sys.stderr,
            )
            return 1
        print("\nLICENSE-wheel is up to date.")
        return 0

    if updated == existing:
        print("\nLICENSE-wheel already up to date.")
        return 0
    open(LICENSE_WHEEL, "w", encoding="utf-8").write(updated)
    print(f"\nwrote {LICENSE_WHEEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
