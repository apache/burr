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

import { useEffect, useState } from "react";
import { GITHUB_REPO, DOCS_URL } from "@/lib/constants";
import { ArrowRight, Github } from "lucide-react";
import { ShimmerButton } from "@/components/ui/shimmer-button";
import { NumberTicker } from "@/components/ui/number-ticker";
import { AnimatedShinyText } from "@/components/ui/animated-shiny-text";
import { DotPattern } from "@/components/ui/dot-pattern";
import { BlurFade } from "@/components/ui/blur-fade";
import { cn } from "@/lib/utils";

export default function Hero() {
  const [stars, setStars] = useState<number>(1500);

  useEffect(() => {
    fetch("https://api.github.com/repos/apache/burr")
      .then((r) => r.json())
      .then((d) => {
        if (d.stargazers_count) setStars(d.stargazers_count);
      })
      .catch(() => {});
  }, []);

  return (
    <section className="relative overflow-hidden pt-20 pb-28 sm:pt-28 sm:pb-36">
      {/* Dot pattern background */}
      <DotPattern
        className={cn(
          "absolute inset-0 -z-10 opacity-30",
          "[mask-image:radial-gradient(500px_circle_at_center,white,transparent)]"
        )}
      />

      {/* Gradient blobs */}
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 h-[600px] w-[900px] rounded-full bg-[#7B2FBE]/10 blur-[120px]" />
        <div className="absolute top-20 right-1/4 h-[400px] w-[400px] rounded-full bg-[#F5A623]/10 blur-[100px]" />
      </div>

      <div className="mx-auto max-w-4xl px-4 text-center">
        {/* Badge */}
        <BlurFade delay={0.1} inView>
          <div className="mb-6 inline-flex items-center justify-center">
            <div className="rounded-full border border-[#7B2FBE]/20 bg-[#7B2FBE]/5 px-4 py-1.5">
              <AnimatedShinyText className="text-sm font-medium text-[#7B2FBE]">
                <span className="relative flex items-center gap-2">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#7B2FBE] opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-[#7B2FBE]" />
                  </span>
                  Apache Incubating Project
                </span>
              </AnimatedShinyText>
            </div>
          </div>
        </BlurFade>

        <BlurFade delay={0.2} inView>
          <h1 className="text-4xl font-extrabold tracking-tight sm:text-6xl lg:text-7xl">
            Build reliable AI agents{" "}
            <span className="bg-gradient-to-r from-[#7B2FBE] via-[#E8446D] to-[#F5A623] bg-clip-text text-transparent">
              and applications
            </span>
          </h1>
        </BlurFade>

        <BlurFade delay={0.3} inView>
          <p className="mt-6 text-lg sm:text-xl text-[var(--muted)] max-w-2xl mx-auto leading-relaxed">
            Apache Burr (Incubating) makes it easy to develop applications
            that make decisions, from simple chatbots to complex multi-agent
            systems. Pure Python, no magic.
          </p>
        </BlurFade>

        {/* CTAs */}
        <BlurFade delay={0.4} inView>
          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
            <a href={DOCS_URL}>
              <ShimmerButton
                shimmerColor="#ffffff"
                shimmerSize="0.05em"
                background="rgba(123, 47, 190, 1)"
                borderRadius="12px"
                className="px-6 py-3 text-sm font-semibold"
              >
                <span className="flex items-center gap-2 text-white">
                  Get Started
                  <ArrowRight className="h-4 w-4" />
                </span>
              </ShimmerButton>
            </a>
            <a
              href={GITHUB_REPO}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-xl border border-[var(--card-border)] px-6 py-3 text-sm font-semibold hover:bg-[var(--card-bg)] transition-colors"
            >
              <Github className="h-4 w-4" />
              View on GitHub
            </a>
          </div>
        </BlurFade>

        {/* Stats with NumberTicker */}
        <BlurFade delay={0.5} inView>
          <div className="mt-14 flex items-center justify-center gap-8 sm:gap-12 text-sm text-[var(--muted)]">
            <div className="flex flex-col items-center gap-1">
              <span className="text-2xl font-bold text-[var(--text)]">
                <NumberTicker value={stars} delay={0.5} />
              </span>
              <span>GitHub Stars</span>
            </div>
            <div className="h-8 w-px bg-[var(--card-border)]" />
            <div className="flex flex-col items-center gap-1">
              <span className="text-2xl font-bold text-[var(--text)]">
                <NumberTicker value={500} delay={0.7} />
                k+
              </span>
              <span>PyPI Downloads</span>
            </div>
            <div className="h-8 w-px bg-[var(--card-border)]" />
            <div className="flex flex-col items-center gap-1">
              <span className="text-2xl font-bold text-[var(--text)]">
                <NumberTicker value={700} delay={0.9} />
                +
              </span>
              <span>Discord Members</span>
            </div>
          </div>
        </BlurFade>
      </div>
    </section>
  );
}
