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

"use client";

import { GITHUB_REPO, DISCORD_URL, TWITTER_URL } from "@/lib/constants";
import { Github, MessageCircle, Twitter } from "lucide-react";
import { MagicCard } from "@/components/ui/magic-card";
import { BlurFade } from "@/components/ui/blur-fade";

const LINKS = [
  {
    icon: MessageCircle,
    label: "Discord",
    description: "Chat with maintainers and the community",
    href: DISCORD_URL,
    gradientFrom: "#5865F2",
    gradientTo: "#7B2FBE",
  },
  {
    icon: Github,
    label: "GitHub",
    description: "Star the repo, file issues, contribute",
    href: GITHUB_REPO,
    gradientFrom: "#6e7681",
    gradientTo: "#30363d",
  },
  {
    icon: Twitter,
    label: "Twitter / X",
    description: "Follow for updates and announcements",
    href: TWITTER_URL,
    gradientFrom: "#1DA1F2",
    gradientTo: "#7B2FBE",
  },
];

export default function Community() {
  return (
    <section id="community" className="py-20 sm:py-28 bg-[var(--card-bg)]">
      <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 text-center">
        <BlurFade delay={0.1} inView>
          <h2 className="text-3xl font-bold sm:text-4xl">
            Join the community
          </h2>
          <p className="mt-3 text-[var(--muted)] text-lg max-w-xl mx-auto">
            Get help, share your projects, and contribute to the future of Burr.
          </p>
        </BlurFade>

        <div className="mt-12 grid grid-cols-1 sm:grid-cols-3 gap-5">
          {LINKS.map((link, i) => {
            const Icon = link.icon;
            return (
              <BlurFade key={link.label} delay={0.2 + i * 0.1} inView>
                <a
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block"
                >
                  <MagicCard
                    gradientSize={200}
                    gradientFrom={link.gradientFrom}
                    gradientTo={link.gradientTo}
                    gradientOpacity={0.12}
                    className="h-full rounded-2xl"
                  >
                    <div className="flex flex-col items-center gap-3 p-6 min-h-[160px]">
                      <div className="inline-flex items-center justify-center rounded-xl p-3 bg-[var(--card-border)]/30">
                        <Icon className="h-6 w-6" />
                      </div>
                      <h3 className="font-semibold">{link.label}</h3>
                      <p className="text-sm text-[var(--muted)]">
                        {link.description}
                      </p>
                    </div>
                  </MagicCard>
                </a>
              </BlurFade>
            );
          })}
        </div>
      </div>
    </section>
  );
}
