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
import { GITHUB_REPO, DOCS_URL } from "@/lib/constants";

export const metadata: Metadata = {
  title: "Download — Apache Burr (Incubating)",
  description:
    "Install Apache Burr from PyPI, or download the official Apache source releases with signatures and checksums.",
};

const PYPI_URL = "https://pypi.org/project/apache-burr/";
const EXAMPLES_URL = `${GITHUB_REPO}/tree/main/examples`;
const DISCORD_URL = "https://discord.gg/6Zy2DwP4f3";

const MIRROR_BASE = "https://www.apache.org/dyn/closer.lua/incubator/burr";
const DIST_BASE = "https://downloads.apache.org/incubator/burr";
const KEYS_URL = `${DIST_BASE}/KEYS`;
const ARCHIVE_URL = "https://archive.apache.org/dist/incubator/burr/";
const VERIFY_DOC_URL = "https://www.apache.org/info/verification.html";
const RELEASE_POLICY_URL =
  "https://www.apache.org/legal/release-policy.html#publication";

// Adding a new release: append a single entry to RELEASES below. The
// artifact filenames, labels, and descriptions are derived from the
// version via ARTIFACT_TEMPLATES, so no per-release boilerplate is
// needed beyond the version + date.

type Artifact = {
  filename: string;
  label: string;
  description: string;
};

type Release = {
  version: string; // e.g. "0.42.0"
  date: string; // human-readable
  note?: string; // optional caveat shown on the release card
};

type ArtifactTemplate = {
  label: string;
  filename: (version: string) => string;
  description: (version: string) => string;
};

const ARTIFACT_TEMPLATES: ArtifactTemplate[] = [
  {
    label: "Source release",
    filename: (v) => `apache-burr-${v}-incubating-src.tar.gz`,
    description: () =>
      "The official source release. This is the artifact voted on by the IPMC.",
  },
  {
    label: "Python sdist",
    filename: (v) => `apache-burr-${v}-incubating-sdist.tar.gz`,
    description: () =>
      "Python source distribution used by flit to build the wheel. Convenience artifact.",
  },
  {
    label: "Python wheel",
    filename: (v) => `apache_burr-${v}-py3-none-any.whl`,
    description: (v) =>
      `Pre-built Python wheel. Convenience binary, also published on PyPI as apache-burr ${v}.`,
  },
];

// To add a release, prepend an entry. The first entry is rendered as "Latest".
const RELEASES: Release[] = [
  { version: "0.42.0", date: "May 9, 2026" },
  {
    version: "0.41.0",
    date: "January 2026",
    note: "The PyPI wheel for 0.41.0 had packaging issues. Build from the source release if you need this version, or just use 0.42.0.",
  },
];

function artifactsFor(version: string): Artifact[] {
  return ARTIFACT_TEMPLATES.map((t) => ({
    filename: t.filename(version),
    label: t.label,
    description: t.description(version),
  }));
}

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
        <h3 className="text-xl font-bold">
          {release.version}{" "}
          <span className="font-normal text-[var(--muted)]">(incubating)</span>
        </h3>
        {isLatest && (
          <span className="inline-flex items-center rounded-full border border-[#7B2FBE]/30 bg-[#7B2FBE]/10 px-2.5 py-0.5 text-xs font-semibold text-[#7B2FBE]">
            Latest
          </span>
        )}
        <span className="text-sm text-[var(--muted)]">
          Released {release.date}
        </span>
      </div>

      {release.note && (
        <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-[var(--text)]">
          <span className="font-semibold text-amber-600 dark:text-amber-400">
            Note:
          </span>{" "}
          {release.note}
        </div>
      )}

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
            {artifactsFor(release.version).map((a) => (
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
        </a>
        . Signatures and checksums are served directly from{" "}
        <code className="font-mono">downloads.apache.org</code> over HTTPS.
      </p>
    </section>
  );
}

function LinkCard({
  href,
  title,
  description,
  external = true,
}: {
  href: string;
  title: string;
  description: string;
  external?: boolean;
}) {
  return (
    <a
      href={href}
      target={external ? "_blank" : undefined}
      rel={external ? "noopener noreferrer" : undefined}
      className="block rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 transition hover:border-[#7B2FBE]/50 hover:bg-[var(--card-bg)]/80"
    >
      <div className="font-semibold text-[var(--text)]">{title}</div>
      <div className="mt-1 text-xs text-[var(--muted)]">{description}</div>
    </a>
  );
}

export default function DownloadsPage() {
  return (
    <>
      <Navbar />
      <main className="py-16 sm:py-20">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">
          {/* Header */}
          <header className="mb-10">
            <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">
              Get Apache Burr{" "}
              <span className="font-bold text-[var(--muted)]">(incubating)</span>
            </h1>
            <p className="mt-3 text-lg text-[var(--muted)]">
              Install from PyPI, run the UI locally, or grab the official
              Apache source release.
            </p>
          </header>

          {/* Install */}
          <section className="mb-10">
            <h2 className="text-2xl font-bold mb-4">Install</h2>
            <div className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6 sm:p-8">
              <p className="text-sm text-[var(--muted)] mb-3">
                Burr is on PyPI. Install with pip:
              </p>
              <pre className="overflow-x-auto rounded-lg border border-[var(--card-border)] bg-[var(--bg)] p-4 text-sm font-mono">
                <code>pip install apache-burr</code>
              </pre>

              <p className="mt-6 text-sm text-[var(--muted)] mb-3">
                For the tracking UI, examples, and common LLM integrations,
                install the <code className="font-mono text-xs">[learn]</code>{" "}
                extras:
              </p>
              <pre className="overflow-x-auto rounded-lg border border-[var(--card-border)] bg-[var(--bg)] p-4 text-sm font-mono">
                <code>{`pip install "apache-burr[learn]"`}</code>
              </pre>

              <p className="mt-6 text-sm text-[var(--muted)] mb-3">
                To pin a specific version:
              </p>
              <pre className="overflow-x-auto rounded-lg border border-[var(--card-border)] bg-[var(--bg)] p-4 text-sm font-mono">
                <code>{`pip install "apache-burr==${LATEST.version}"`}</code>
              </pre>

              <p className="mt-4 text-xs text-[var(--muted)]">
                Requires Python 3.10+. Burr has no required runtime
                dependencies — extras are opt-in.
              </p>
            </div>
          </section>

          {/* Run the UI */}
          <section className="mb-10">
            <h2 className="text-2xl font-bold mb-4">Run the UI</h2>
            <div className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6 sm:p-8">
              <p className="text-sm text-[var(--muted)] mb-3">
                Once installed with the <code className="font-mono text-xs">[learn]</code>{" "}
                extras, launch the local tracking UI to inspect and debug
                your applications:
              </p>
              <pre className="overflow-x-auto rounded-lg border border-[var(--card-border)] bg-[var(--bg)] p-4 text-sm font-mono">
                <code>burr</code>
              </pre>
              <p className="mt-4 text-sm text-[var(--muted)]">
                Opens at{" "}
                <code className="font-mono text-xs">http://localhost:7241</code>
                . Apps that use{" "}
                <code className="font-mono text-xs">.with_tracker(&quot;local&quot;)</code>{" "}
                will show up automatically.
              </p>
            </div>
          </section>

          {/* Quick links */}
          <section className="mb-14">
            <h2 className="text-2xl font-bold mb-4">Where to next</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <LinkCard
                href={DOCS_URL}
                external={false}
                title="Documentation"
                description="Concepts, API reference, and guides."
              />
              <LinkCard
                href={`${GITHUB_REPO}#getting-started`}
                title="Getting started"
                description="A 5-minute tour of building your first Burr application."
              />
              <LinkCard
                href={EXAMPLES_URL}
                title="Examples"
                description="Chatbots, agents, multi-modal apps, and more on GitHub."
              />
              <LinkCard
                href={GITHUB_REPO}
                title="Source on GitHub"
                description="Browse the code, file issues, send PRs."
              />
              <LinkCard
                href={PYPI_URL}
                title="PyPI"
                description="apache-burr package page with version history."
              />
              <LinkCard
                href={DISCORD_URL}
                title="Discord"
                description="Ask questions, share what you're building."
              />
            </div>
          </section>

          {/* Apache source releases */}
          <section className="mb-12">
            <h2 className="text-2xl font-bold mb-2">Apache source releases</h2>
            <p className="text-sm text-[var(--muted)] mb-6">
              Burr is an Apache Software Foundation project. The source release
              is the official artifact voted on by the IPMC; per the{" "}
              <a
                href={RELEASE_POLICY_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-[var(--text)]"
              >
                ASF release policy
              </a>
              , the wheel and sdist below are the same bits published to PyPI.
              If you&apos;re packaging Burr for redistribution, or you simply
              prefer to build from source, start here.
            </p>

            <div className="mb-8">
              <h3 className="text-xs font-semibold mb-3 text-[var(--muted)] uppercase tracking-wide">
                Latest
              </h3>
              <ReleaseSection release={LATEST} isLatest />
            </div>

            {RELEASES.length > 1 && (
              <div>
                <h3 className="text-xs font-semibold mb-3 text-[var(--muted)] uppercase tracking-wide">
                  Previous
                </h3>
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
                  Older releases live in the{" "}
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
          </section>

          {/* Verifying releases */}
          <section
            id="verify"
            className="mb-12 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6 sm:p-8"
          >
            <h2 className="text-2xl font-bold mb-3">Verifying a release</h2>
            <p className="text-sm text-[var(--muted)]">
              If you&apos;re downloading source releases above, you{" "}
              <strong className="text-[var(--text)]">should</strong> verify
              them before use. The PGP signature (
              <code className="font-mono text-xs">.asc</code>) proves the
              release was signed by an Apache Burr release manager; the SHA-512
              checksum (<code className="font-mono text-xs">.sha512</code>)
              detects transmission corruption.
            </p>

            <h3 className="mt-6 mb-2 font-semibold">1. Import the KEYS file</h3>
            <p className="text-sm text-[var(--muted)] mb-3">
              The KEYS file holds the public PGP keys of all Apache Burr
              release managers, served from{" "}
              <code className="font-mono text-xs">downloads.apache.org</code>:
            </p>
            <pre className="overflow-x-auto rounded-lg border border-[var(--card-border)] bg-[var(--bg)] p-4 text-sm font-mono">
              <code>{`curl -O ${KEYS_URL}
gpg --import KEYS`}</code>
            </pre>

            <h3 className="mt-6 mb-2 font-semibold">2. Verify the signature</h3>
            <pre className="overflow-x-auto rounded-lg border border-[var(--card-border)] bg-[var(--bg)] p-4 text-sm font-mono">
              <code>{`gpg --verify apache-burr-${LATEST.version}-incubating-src.tar.gz.asc \\
            apache-burr-${LATEST.version}-incubating-src.tar.gz`}</code>
            </pre>
            <p className="mt-3 text-sm text-[var(--muted)]">
              Look for &quot;Good signature from ...&quot; in the output. A
              warning that the key is not certified by a trusted signature is
              expected unless you&apos;ve set up a web of trust — what matters
              is that the fingerprint matches one in KEYS.
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
              For more detail, see the{" "}
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
              included in every source release.
            </p>
            <p className="mt-4 text-sm text-[var(--muted)]">
              Apache Burr (Incubating) is an effort undergoing incubation at
              The Apache Software Foundation (ASF), sponsored by the Apache
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
