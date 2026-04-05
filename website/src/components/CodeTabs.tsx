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

import { useState, useEffect } from "react";
import { CODE_SNIPPETS } from "@/lib/constants";
import { Check, Copy, Terminal } from "lucide-react";
import { BorderBeam } from "@/components/ui/border-beam";
import { BlurFade } from "@/components/ui/blur-fade";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "chatbot" as const, label: "Chatbot", file: "chatbot.py" },
  { key: "agent" as const, label: "Multi-Agent", file: "agents.py" },
  { key: "statemachine" as const, label: "State Machine", file: "counter.py" },
];

export default function CodeTabs() {
  const [active, setActive] = useState<keyof typeof CODE_SNIPPETS>("chatbot");
  const [copied, setCopied] = useState(false);
  const [highlighted, setHighlighted] = useState<Record<string, string>>({});

  useEffect(() => {
    import("shiki").then(async ({ createHighlighter }) => {
      const highlighter = await createHighlighter({
        themes: ["github-dark"],
        langs: ["python"],
      });

      const result: Record<string, string> = {};
      for (const [key, code] of Object.entries(CODE_SNIPPETS)) {
        result[key] = highlighter.codeToHtml(code, {
          lang: "python",
          theme: "github-dark",
        });
      }
      setHighlighted(result);
    });
  }, []);

  const handleCopy = () => {
    navigator.clipboard.writeText(CODE_SNIPPETS[active]);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const activeTab = TABS.find((t) => t.key === active)!;

  return (
    <section className="py-20 sm:py-28">
      <div className="mx-auto max-w-4xl px-4">
        <BlurFade delay={0.1} inView>
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold sm:text-4xl">
              Simple, powerful Python API
            </h2>
            <p className="mt-3 text-[var(--muted)] text-lg">
              Build anything from chatbots to multi-agent systems with a clean,
              composable interface.
            </p>
          </div>
        </BlurFade>

        <BlurFade delay={0.2} inView>
          {/* Terminal window */}
          <div className="relative rounded-2xl overflow-hidden shadow-2xl shadow-[#7B2FBE]/10">
            <BorderBeam
              size={250}
              duration={10}
              colorFrom="#7B2FBE"
              colorTo="#F5A623"
              borderWidth={1.5}
            />

            {/* Title bar */}
            <div className="flex items-center gap-3 bg-[#1a1a2e] px-4 py-3 border-b border-white/5">
              {/* Traffic lights */}
              <div className="flex items-center gap-1.5">
                <div className="h-3 w-3 rounded-full bg-[#ff5f57]" />
                <div className="h-3 w-3 rounded-full bg-[#febc2e]" />
                <div className="h-3 w-3 rounded-full bg-[#28c840]" />
              </div>

              {/* Terminal title */}
              <div className="flex-1 flex items-center justify-center gap-1.5 text-xs text-white/40">
                <Terminal className="h-3 w-3" />
                <span>{activeTab.file}</span>
              </div>

              {/* Copy button */}
              <button
                onClick={handleCopy}
                className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs text-white/40 hover:text-white hover:bg-white/10 transition-colors"
              >
                {copied ? (
                  <>
                    <Check className="h-3 w-3" /> Copied
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3" /> Copy
                  </>
                )}
              </button>
            </div>

            {/* Tab bar */}
            <div className="flex bg-[#12121f] border-b border-white/5">
              {TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActive(tab.key)}
                  className={cn(
                    "relative px-5 py-2.5 text-xs font-medium transition-all",
                    active === tab.key
                      ? "bg-[var(--code-bg)] text-white"
                      : "text-white/35 hover:text-white/60 hover:bg-white/[0.03]"
                  )}
                >
                  <span className="flex items-center gap-2">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        active === tab.key ? "bg-[#7B2FBE]" : "bg-white/20"
                      )}
                    />
                    {tab.label}
                  </span>
                  {active === tab.key && (
                    <span className="absolute bottom-0 left-0 right-0 h-[2px] bg-gradient-to-r from-[#7B2FBE] to-[#F5A623]" />
                  )}
                </button>
              ))}
            </div>

            {/* Code content */}
            <div className="bg-[var(--code-bg)] overflow-x-auto max-h-[500px] overflow-y-auto">
              {highlighted[active] ? (
                <div
                  dangerouslySetInnerHTML={{ __html: highlighted[active] }}
                  className="[&>pre]:!bg-transparent [&>pre]:px-5 [&>pre]:py-4 [&>pre]:text-[13px] [&>pre]:leading-[1.8]"
                />
              ) : (
                <pre className="px-5 py-4 text-[13px] leading-[1.8] text-white/70">
                  <code>{CODE_SNIPPETS[active]}</code>
                </pre>
              )}
            </div>

            {/* Bottom bar */}
            <div className="flex items-center justify-between bg-[#12121f] px-4 py-2 border-t border-white/5 text-[10px] text-white/25">
              <span>Python 3.12</span>
              <span>UTF-8</span>
              <span>burr &gt;= 0.30</span>
            </div>
          </div>
        </BlurFade>
      </div>
    </section>
  );
}
