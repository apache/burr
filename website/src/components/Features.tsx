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

import { FEATURES } from "@/lib/constants";
import {
  Database,
  Eye,
  UserCheck,
  Zap,
  GitBranch,
  FlaskConical,
} from "lucide-react";
import { BlurFade } from "@/components/ui/blur-fade";

const iconMap: Record<string, React.ElementType> = {
  Database,
  Eye,
  UserCheck,
  Zap,
  GitBranch,
  FlaskConical,
};

export default function Features() {
  return (
    <section id="features" className="py-20 sm:py-28">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <BlurFade delay={0.1} inView>
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold sm:text-4xl">
              Everything you need to build AI applications
            </h2>
            <p className="mt-3 text-[var(--muted)] text-lg max-w-2xl mx-auto">
              Burr provides the building blocks for reliable, observable, and
              testable AI-powered applications.
            </p>
          </div>
        </BlurFade>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {FEATURES.map((feature, i) => {
            const Icon = iconMap[feature.icon];
            return (
              <BlurFade key={feature.title} delay={0.15 + i * 0.05} inView>
                <div className="group rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-8 hover:border-[#7B2FBE]/30 hover:shadow-xl hover:shadow-[#7B2FBE]/5 transition-all duration-300">
                  <div className="mb-5 inline-flex items-center justify-center rounded-xl bg-[#7B2FBE]/10 p-3.5 text-[#7B2FBE] group-hover:bg-[#7B2FBE]/15 transition-colors">
                    <Icon className="h-7 w-7" />
                  </div>
                  <h3 className="text-xl font-semibold mb-3">
                    {feature.title}
                  </h3>
                  <p className="text-[15px] text-[var(--muted)] leading-relaxed">
                    {feature.description}
                  </p>
                </div>
              </BlurFade>
            );
          })}
        </div>
      </div>
    </section>
  );
}
