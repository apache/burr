"use client";

import { INTEGRATIONS, DOCS_URL } from "@/lib/constants";
import { ArrowUpRight } from "lucide-react";
import { INTEGRATION_ICONS, INTEGRATION_COLORS } from "@/components/icons/IntegrationLogos";
import { BlurFade } from "@/components/ui/blur-fade";
import { Marquee } from "@/components/ui/marquee";

export default function Integrations() {
  const firstRow = INTEGRATIONS.slice(0, 5);
  const secondRow = INTEGRATIONS.slice(5);

  return (
    <section id="integrations" className="py-20 sm:py-28 bg-[var(--card-bg)] overflow-hidden">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <BlurFade delay={0.1} inView>
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold sm:text-4xl">
              Works with your stack
            </h2>
            <p className="mt-3 text-[var(--muted)] text-lg max-w-2xl mx-auto">
              Burr integrates with the tools and frameworks you already use. No
              lock-in, no wrappers.
            </p>
          </div>
        </BlurFade>

        {/* Marquee rows */}
        <div className="relative">
          <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-24 bg-gradient-to-r from-[var(--card-bg)] to-transparent" />
          <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-24 bg-gradient-to-l from-[var(--card-bg)] to-transparent" />

          <Marquee pauseOnHover className="[--duration:30s] [--gap:1.5rem] mb-4">
            {firstRow.map((integration) => (
              <IntegrationCard key={integration.name} integration={integration} />
            ))}
          </Marquee>

          <Marquee pauseOnHover reverse className="[--duration:30s] [--gap:1.5rem]">
            {secondRow.map((integration) => (
              <IntegrationCard key={integration.name} integration={integration} />
            ))}
          </Marquee>
        </div>

        <BlurFade delay={0.3} inView>
          <div className="mt-12 text-center">
            <a
              href={DOCS_URL}
              className="inline-flex items-center gap-1.5 text-sm font-medium text-[#7B2FBE] hover:text-[#9B5FDE] transition-colors"
            >
              View all integrations
              <ArrowUpRight className="h-4 w-4" />
            </a>
          </div>
        </BlurFade>
      </div>
    </section>
  );
}

function IntegrationCard({
  integration,
}: {
  integration: (typeof INTEGRATIONS)[number];
}) {
  const Icon = INTEGRATION_ICONS[integration.name];
  const color = INTEGRATION_COLORS[integration.name];

  return (
    <div className="flex items-center gap-4 rounded-2xl border border-[var(--card-border)] bg-[var(--bg)] px-6 py-5 w-[260px] shrink-0 hover:border-[#7B2FBE]/20 hover:shadow-lg transition-all duration-300">
      <div
        className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl"
        style={{ backgroundColor: `${color}15` }}
      >
        {Icon && <Icon className="h-6 w-6" style={{ color }} />}
      </div>
      <div>
        <h3 className="font-semibold">{integration.name}</h3>
        <span className="text-xs text-[var(--muted)]">
          {integration.category}
        </span>
      </div>
    </div>
  );
}
