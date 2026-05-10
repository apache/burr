/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

import type { Metadata } from "next";
import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";

export const metadata: Metadata = {
  title: "Downloads — Apache Burr (Incubating)",
  description:
    "Download Apache Burr (Incubating) source releases, signatures, and checksums. Includes verification instructions per ASF release policy.",
};

// Apache mirror selection URL prefix (closer.lua) for tarball downloads.
// Per ASF release policy, signatures (.asc), checksums (.sha512), and the
// KEYS file MUST be served directly over HTTPS from downloads.apache.org
// rather than via mirrors.
const MIRROR_BASE = "https://www.apache.org/dyn/closer.lua/incubator/burr";
const DIST_BASE = "https://downloads.apache.org/incubator/burr";
const KEYS_URL = `${DIST_BASE}/KEYS`;
const ARCHIVE_URL = "https://archive.apache.org/dist/incubator/burr/";
const VERIFY_DOC_URL = "https://www.apache.org/info/verification.html";
const RELEASE_POLICY_URL =
  "https://www.apache.org/legal/release-policy.html#publication";

type Artifact = {
  filename: string;
  label: string;
  description: string;
};

type Release = {
  version: string; // e.g. "0.42.0"
  date: string; // human-readable
  artifacts: Artifact[];
};

const RELEASES: Release[] = [
  {
    version: "0.42.0",
    date: "May 9, 2026",
    artifacts: [
      {
        filename: "apache-burr-0.42.0-incubating-src.tar.gz",
        label: "Source release",
        description:
          "The official source release. This is the artifact voted on by the IPMC.",
      },
      {
        filename: "apache-burr-0.42.0-incubating-sdist.tar.gz",
        label: "Python sdist",
        description:
          "Python source distribution used by flit to build the wheel. Convenience artifact.",
      },
      {
        filename: "apache_burr-0.42.0-py3-none-any.whl",
        label: "Python wheel",
        description:
          "Pre-built Python wheel. Convenience binary, also published on PyPI as apache-burr 0.42.0.",
      },
    ],
  },
  {
    version: "0.41.0",
    date: "January 2026",
    artifacts: [
      {
        filename: "apache-burr-0.41.0-incubating-src.tar.gz",
        label: "Source release",
        description: "The official source release.",
      },
      {
        filename: "apache-burr-0.41.0-incubating-sdist.tar.gz",
        label: "Python sdist",
        description: "Python source distribution used by flit to build the wheel.",
      },
      {
        filename: "apache_burr-0.41.0-py3-none-any.whl",
        label: "Python wheel",
        description:
          "Pre-built Python wheel. Convenience binary, also published on PyPI as apache-burr 0.41.0.",
      },
    ],
  },
];

const LATEST = RELEASES[0];

function mirrorUrl(version: string, filename: string): string {
  return `${MIRROR_BASE}/${version}/${filename}?action=download`;
}

function directUrl(version: string, filename: string, ext: string): string {
  return `${DIST_BASE}/${version}/${filename}.${ext}`;
}

function ReleaseSection({
  release,
  isLatest,
}: {
  release: Release;
  isLatest: boolean;
}) {
  const headingId = `release-${release.version}`;
  return (
    <section
      id={headingId}
      className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6 sm:p-8"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-1">
        <h2 className="text-2xl font-bold">
          {release.version}-incubating
        </h2>
        {isLatest && (
          <span className="inline-flex items-center rounded-full border border-[#7B2FBE]/30 bg-[#7B2FBE]/10 px-2.5 py-0.5 text-xs font-semibold text-[#7B2FBE]">
            Latest
          </span>
        )}
        <span className="text-sm text-[var(--muted)]">
          Released {release.date}
        </span>
      </div>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left border-b border-[var(--card-border)] text-[var(--muted)]">
              <th className="py-2 pr-4 font-medium">Artifact</th>
              <th className="py-2 pr-4 font-medium">Download</th>
              <th className="py-2 pr-4 font-medium">Signature</th>
              <th className="py-2 font-medium">Checksum</th>
            </tr>
          </thead>
          <tbody>
            {release.artifacts.map((a) => (
              <tr
                key={a.filename}
                className="border-b border-[var(--card-border)]/50 last:border-b-0 align-top"
              >
                <td className="py-3 pr-4">
                  <div className="font-medium">{a.label}</div>
                  <div className="text-xs text-[var(--muted)] mt-0.5">
                    {a.description}
                  </div>
                </td>
                <td className="py-3 pr-4">
                  <a
                    href={mirrorUrl(release.version, a.filename)}
                    className="text-[#7B2FBE] hover:underline break-all font-mono text-xs"
                  >
                    {a.filename}
                  </a>
                </td>
                <td className="py-3 pr-4">
                  <a
                    href={directUrl(release.version, a.filename, "asc")}
                    className="text-[var(--muted)] hover:text-[var(--text)] hover:underline font-mono text-xs"
                  >
                    .asc
                  </a>
                </td>
                <td className="py-3">
                  <a
                    href={directUrl(release.version, a.filename, "sha512")}
                    className="text-[var(--muted)] hover:text-[var(--text)] hover:underline font-mono text-xs"
                  >
                    .sha512
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-[var(--muted)]">
        Tarball links use the{" "}
        <a
          href="https://www.apache.org/dyn/closer.cgi"
          target="_blank"
          rel="noopener noreferrer"
          className="underline hover:text-[var(--text)]"
        >
          ASF mirror selection service
        </a>{" "}
        to find the closest mirror. Signatures and checksums are served directly
        from <code className="font-mono">downloads.apache.org</code> over HTTPS.
      </p>
    </section>
  );
}

export default function DownloadsPage() {
  return (
    <>
      <Navbar />
      <main className="py-16 sm:py-20">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">
          {/* Header */}
          <header className="mb-12">
            <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">
              Downloads
            </h1>
            <p className="mt-3 text-lg text-[var(--muted)]">
              Apache Burr (Incubating) — official source releases, signatures,
              and checksums.
            </p>
            <p className="mt-4 text-sm text-[var(--muted)]">
              Apache Burr is currently undergoing incubation at the Apache
              Software Foundation. The source release is the official artifact;
              binary downloads are provided for convenience. Please see the{" "}
              <a
                href={RELEASE_POLICY_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-[var(--text)]"
              >
                ASF release policy
              </a>{" "}
              and the{" "}
              <a
                href="#disclaimer"
                className="underline hover:text-[var(--text)]"
              >
                incubator disclaimer
              </a>{" "}
              below.
            </p>
          </header>

          {/* Quick install */}
          <section className="mb-12 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6 sm:p-8">
            <h2 className="text-2xl font-bold mb-3">Quick install</h2>
            <p className="text-sm text-[var(--muted)] mb-4">
              The fastest way to get started is via PyPI. The convenience wheel
              published there matches the wheel artifact in the source release.
            </p>
            <pre className="overflow-x-auto rounded-lg border border-[var(--card-border)] bg-[var(--bg)] p-4 text-sm font-mono">
              <code>{`pip install apache-burr==${LATEST.version}`}</code>
            </pre>
            <p className="mt-4 text-xs text-[var(--muted)]">
              For projects that require building from source, download the
              source release tarball below and verify it before use.
            </p>
          </section>

          {/* Latest release */}
          <div className="mb-12">
            <h2 className="text-xl font-semibold mb-4 text-[var(--muted)] uppercase tracking-wide text-sm">
              Latest release
            </h2>
            <ReleaseSection release={LATEST} isLatest />
          </div>

          {/* Previous releases */}
          {RELEASES.length > 1 && (
            <div className="mb-12">
              <h2 className="text-xl font-semibold mb-4 text-[var(--muted)] uppercase tracking-wide text-sm">
                Previous releases
              </h2>
              <div className="space-y-6">
                {RELEASES.slice(1).map((r) => (
                  <ReleaseSection
                    key={r.version}
                    release={r}
                    isLatest={false}
                  />
                ))}
              </div>
              <p className="mt-4 text-xs text-[var(--muted)]">
                Older releases are kept in the{" "}
                <a
                  href={ARCHIVE_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-[var(--text)]"
                >
                  ASF archive
                </a>
                .
              </p>
            </div>
          )}

          {/* Verifying releases */}
          <section
            id="verify"
            className="mb-12 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6 sm:p-8"
          >
            <h2 className="text-2xl font-bold mb-3">Verifying releases</h2>
            <p className="text-sm text-[var(--muted)]">
              You <strong className="text-[var(--text)]">should</strong> verify
              the integrity of any downloaded release before using it. The PGP
              signature (
              <code className="font-mono text-xs">.asc</code>) proves the
              release was signed by an Apache Burr release manager; the SHA-512
              checksum (
              <code className="font-mono text-xs">.sha512</code>) detects
              transmission corruption.
            </p>

            <h3 className="mt-6 mb-2 font-semibold">1. Download the KEYS file</h3>
            <p className="text-sm text-[var(--muted)] mb-3">
              The KEYS file contains the public PGP keys of all Apache Burr
              release managers. It is served directly from{" "}
              <code className="font-mono text-xs">downloads.apache.org</code>{" "}
              over HTTPS:
            </p>
            <p className="text-sm">
              <a
                href={KEYS_URL}
                className="text-[#7B2FBE] hover:underline font-mono text-xs break-all"
              >
                {KEYS_URL}
              </a>
            </p>
            <pre className="mt-3 overflow-x-auto rounded-lg border border-[var(--card-border)] bg-[var(--bg)] p-4 text-sm font-mono">
              <code>{`curl -O ${KEYS_URL}
gpg --import KEYS`}</code>
            </pre>

            <h3 className="mt-6 mb-2 font-semibold">2. Verify the signature</h3>
            <p className="text-sm text-[var(--muted)] mb-3">
              Download the artifact and its{" "}
              <code className="font-mono text-xs">.asc</code> signature, then:
            </p>
            <pre className="overflow-x-auto rounded-lg border border-[var(--card-border)] bg-[var(--bg)] p-4 text-sm font-mono">
              <code>{`gpg --verify apache-burr-${LATEST.version}-incubating-src.tar.gz.asc \\
            apache-burr-${LATEST.version}-incubating-src.tar.gz`}</code>
            </pre>
            <p className="mt-3 text-sm text-[var(--muted)]">
              Look for &quot;Good signature from ...&quot; in the output. A
              warning about the key not being certified by a trusted signature
              is expected unless you have set up your trust web; what matters is
              the key fingerprint matches one in KEYS.
            </p>

            <h3 className="mt-6 mb-2 font-semibold">3. Verify the checksum</h3>
            <pre className="overflow-x-auto rounded-lg border border-[var(--card-border)] bg-[var(--bg)] p-4 text-sm font-mono">
              <code>{`sha512sum -c apache-burr-${LATEST.version}-incubating-src.tar.gz.sha512`}</code>
            </pre>
            <p className="mt-3 text-sm text-[var(--muted)]">
              On macOS, use{" "}
              <code className="font-mono text-xs">shasum -a 512 -c</code>{" "}
              instead of <code className="font-mono text-xs">sha512sum -c</code>
              .
            </p>

            <p className="mt-6 text-sm text-[var(--muted)]">
              For more detail on verifying ASF releases, see the{" "}
              <a
                href={VERIFY_DOC_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-[var(--text)]"
              >
                official ASF verification guide
              </a>
              .
            </p>
          </section>

          {/* License & disclaimer */}
          <section
            id="disclaimer"
            className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6 sm:p-8"
          >
            <h2 className="text-2xl font-bold mb-3">License &amp; disclaimer</h2>
            <p className="text-sm text-[var(--muted)]">
              Apache Burr is released under the{" "}
              <a
                href="https://www.apache.org/licenses/LICENSE-2.0"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-[var(--text)]"
              >
                Apache License, Version 2.0
              </a>
              . The full <code className="font-mono text-xs">LICENSE</code> and{" "}
              <code className="font-mono text-xs">NOTICE</code> files are
              included in every source release tarball.
            </p>
            <p className="mt-4 text-sm text-[var(--muted)]">
              Apache Burr (Incubating) is an effort undergoing incubation at The
              Apache Software Foundation (ASF), sponsored by the Apache
              Incubator. Incubation is required of all newly accepted projects
              until a further review indicates that the infrastructure,
              communications, and decision making process have stabilized in a
              manner consistent with other successful ASF projects. While
              incubation status is not necessarily a reflection of the
              completeness or stability of the code, it does indicate that the
              project has yet to be fully endorsed by the ASF.
            </p>
          </section>
        </div>
      </main>
      <Footer />
    </>
  );
}
