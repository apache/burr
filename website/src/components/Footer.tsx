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

import { GITHUB_REPO, DOCS_URL, DISCORD_URL, TWITTER_URL, BASE_PATH } from "@/lib/constants";

const COLUMNS = [
  {
    title: "Project",
    links: [
      { label: "Features", href: "#features" },
      { label: "Integrations", href: "#integrations" },
      { label: "Roadmap", href: `${GITHUB_REPO}/issues`, external: true },
      { label: "Changelog", href: `${GITHUB_REPO}/releases`, external: true },
    ],
  },
  {
    title: "Resources",
    links: [
      { label: "Documentation", href: DOCS_URL, external: true },
      { label: "Examples", href: `${GITHUB_REPO}/tree/main/examples`, external: true },
      { label: "YouTube", href: "https://www.youtube.com/@DAGWorks-Inc", external: true },
    ],
  },
  {
    title: "Community",
    links: [
      { label: "Discord", href: DISCORD_URL, external: true },
      { label: "GitHub", href: GITHUB_REPO, external: true },
      { label: "Twitter / X", href: TWITTER_URL, external: true },
      { label: "Contributing", href: `${GITHUB_REPO}/blob/main/CONTRIBUTING.rst`, external: true },
    ],
  },
  {
    title: "Apache",
    links: [
      { label: "Apache Homepage", href: "https://www.apache.org/", external: true },
      { label: "Incubator", href: "https://incubator.apache.org/", external: true },
      { label: "License", href: "https://www.apache.org/licenses/", external: true },
      { label: "Thanks", href: "https://www.apache.org/foundation/thanks.html", external: true },
      { label: "Security", href: "https://www.apache.org/security/", external: true },
      { label: "Sponsorship", href: "https://www.apache.org/foundation/sponsorship.html", external: true },
      { label: "Privacy Policy", href: "https://privacy.apache.org/policies/privacy-policy-public.html", external: true },
      { label: "Events", href: "https://www.apache.org/events/current-event.html", external: true },
    ],
  },
];

export default function Footer() {
  return (
    <footer className="border-t border-[var(--card-border)] py-16">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-8 mb-12">
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <h3 className="text-sm font-semibold mb-4">{col.title}</h3>
              <ul className="space-y-2.5">
                {col.links.map((link) => (
                  <li key={link.label}>
                    <a
                      href={link.href}
                      target={link.external ? "_blank" : undefined}
                      rel={link.external ? "noopener noreferrer" : undefined}
                      className="text-sm text-[var(--muted)] hover:text-[var(--text)] transition-colors"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Trademark attribution + disclaimer */}
        <div className="border-t border-[var(--card-border)] pt-8">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <img
                src={`${BASE_PATH}/burr_logo.svg`}
                alt="Apache Burr"
                className="h-6 w-6 opacity-60"
              />
              <span className="text-sm text-[var(--muted)]">
                &copy; {new Date().getFullYear()} The Apache Software Foundation
              </span>
            </div>
          </div>

          <p className="mt-4 text-xs text-[var(--muted)]/60 leading-relaxed max-w-3xl">
            Apache Burr (Incubating) is an effort undergoing incubation at{" "}
            <a
              href="https://www.apache.org/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-[var(--text)]"
            >
              The Apache Software Foundation
            </a>{" "}
            (ASF), sponsored by the{" "}
            <a
              href="https://incubator.apache.org/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-[var(--text)]"
            >
              Apache Incubator
            </a>
            . Incubation is required of all newly accepted projects until a
            further review indicates that the infrastructure, communications,
            and decision making process have stabilized in a manner consistent
            with other successful ASF projects. While incubation status is not
            necessarily a reflection of the completeness or stability of the
            code, it does indicate that the project has yet to be fully endorsed
            by the ASF.
          </p>

          <p className="mt-3 text-xs text-[var(--muted)]/60 leading-relaxed max-w-3xl">
            Apache Burr, Burr, Apache, the Apache feather logo, and the Apache
            Burr project logo are either registered trademarks or trademarks of
            The Apache Software Foundation in the United States and other
            countries. All other marks mentioned may be trademarks or registered
            trademarks of their respective owners.
          </p>
        </div>
      </div>
    </footer>
  );
}
