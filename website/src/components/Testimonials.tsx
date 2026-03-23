"use client";

import { TESTIMONIALS } from "@/lib/constants";
import { Quote } from "lucide-react";
import { Marquee } from "@/components/ui/marquee";
import { BlurFade } from "@/components/ui/blur-fade";

function TestimonialCard({
  name,
  title,
  company,
  quote,
  logo,
}: (typeof TESTIMONIALS)[0]) {
  return (
    <div className="w-[380px] shrink-0 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-6 overflow-visible">
      <Quote className="h-5 w-5 text-[#7B2FBE]/40 mb-3" />
      <p className="text-sm leading-relaxed text-[var(--muted)] mb-5">
        &ldquo;{quote}&rdquo;
      </p>
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#7B2FBE]/10 text-sm font-bold text-[#7B2FBE]">
          {name.charAt(0)}
        </div>
        <div>
          <div className="text-sm font-semibold">{name}</div>
          <div className="text-xs text-[var(--muted)]">
            {title}, {company}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Testimonials() {
  const companies = TESTIMONIALS.filter((t) => t.logo).reduce(
    (acc, t) => {
      if (!acc.find((c) => c.name === t.company)) {
        acc.push({ name: t.company, logo: t.logo! });
      }
      return acc;
    },
    [] as { name: string; logo: string }[]
  );

  return (
    <section className="py-20 sm:py-28 overflow-hidden">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <BlurFade delay={0.1} inView>
          <div className="text-center mb-10">
            <h2 className="text-3xl font-bold sm:text-4xl">
              Trusted by engineers worldwide
            </h2>
            <p className="mt-3 text-[var(--muted)] text-lg">
              See what developers and teams are saying about Burr.
            </p>
          </div>
        </BlurFade>

        {/* Trusted by companies */}
        <BlurFade delay={0.2} inView>
          <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-4 mb-14">
            {companies.map((company) => (
              <div
                key={company.name}
                className="flex items-center gap-2.5 px-4 py-2 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)]"
              >
                <img
                  src={company.logo}
                  alt={company.name}
                  className="h-7 w-7 rounded-md object-contain"
                  onError={(e) => {
                    const target = e.currentTarget;
                    target.style.display = "none";
                    const fallback = target.nextElementSibling as HTMLElement;
                    if (fallback) fallback.style.display = "flex";
                  }}
                />
                <div className="hidden h-7 w-7 items-center justify-center rounded-md bg-[#7B2FBE]/10 text-xs font-bold text-[#7B2FBE]">
                  {company.name.charAt(0)}
                </div>
                <span className="text-sm font-semibold">{company.name}</span>
              </div>
            ))}
          </div>
        </BlurFade>

        {/* Marquee carousel */}
        <div className="relative">
          {/* Fade edges */}
          <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-20 bg-gradient-to-r from-[var(--bg)] to-transparent" />
          <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-20 bg-gradient-to-l from-[var(--bg)] to-transparent" />

          <Marquee pauseOnHover className="[--duration:45s] [--gap:1.5rem]">
            {TESTIMONIALS.map((t) => (
              <TestimonialCard key={t.name} {...t} />
            ))}
          </Marquee>
        </div>
      </div>
    </section>
  );
}
