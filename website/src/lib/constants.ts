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

export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || "";

export const GITHUB_REPO = "https://github.com/apache/burr";
export const DOCS_URL = "/docs";
export const DISCORD_URL = "https://discord.gg/6Zy2DwP4f3";
export const TWITTER_URL = "https://x.com/burr_framework";

export const NAV_LINKS = [
  { label: "Features", href: "#features" },
  { label: "Integrations", href: "#integrations" },
  { label: "Community", href: "#community" },
  { label: "Docs", href: DOCS_URL, external: true },
];

export const FEATURES = [
  {
    icon: "Zap",
    title: "Simple Python API",
    description:
      "Define your application as a set of actions and transitions. No DSL, no YAML — just Python functions and decorators.",
  },
  {
    icon: "Eye",
    title: "Built-in Observability",
    description:
      "The Burr UI lets you monitor, debug, and trace every step of your application in real time. See state changes as they happen.",
  },
  {
    icon: "Database",
    title: "Persistence & State Management",
    description:
      "Automatically persist state to disk, databases, or custom backends. Resume applications from where they left off.",
  },
  {
    icon: "UserCheck",
    title: "Human-in-the-Loop",
    description:
      "Pause execution and wait for human input at any step. Perfect for approval workflows and interactive agents.",
  },
  {
    icon: "GitBranch",
    title: "Branching & Parallelism",
    description:
      "Run actions in parallel, fan out / fan in, and build complex DAGs. Compose sub-applications for modular design.",
  },
  {
    icon: "FlaskConical",
    title: "Testing & Replay",
    description:
      "Replay past runs, unit test individual actions, and validate state transitions. Build confidence in your AI systems.",
  },
];

export const INTEGRATIONS = [
  { name: "OpenAI", category: "LLM" },
  { name: "Anthropic", category: "LLM" },
  { name: "LangChain", category: "Framework" },
  { name: "Hamilton", category: "Framework" },
  { name: "Streamlit", category: "UI" },
  { name: "FastAPI", category: "Serving" },
  { name: "Haystack", category: "Framework" },
  { name: "Instructor", category: "LLM" },
  { name: "Pydantic", category: "Validation" },
  { name: "PostgreSQL", category: "Storage" },
];

export const TESTIMONIALS = [
  {
    name: "Ashish Ghosh",
    title: "CTO",
    company: "Peanut Robotics",
    logo: "https://www.google.com/s2/favicons?domain=peanutrobotics.com&sz=64",
    quote:
      "After evaluating several other obfuscating LLM frameworks, their elegant yet comprehensive state management solution proved to be the powerful answer to rolling out robots driven by AI decision making.",
  },
  {
    name: "Ishita",
    title: "Founder",
    company: "Watto.ai",
    logo: "https://www.google.com/s2/favicons?domain=watto.ai&sz=64",
    quote:
      "Using Burr is a no-brainer if you want to build a modular AI application. It is so easy to build with and I especially love their UI which makes debugging a piece of cake. And the always ready to help team is the cherry on top.",
  },
  {
    name: "Matthew Rideout",
    title: "Staff Software Engineer",
    company: "Paxton AI",
    logo: "https://www.google.com/s2/favicons?domain=paxton.ai&sz=64",
    quote:
      "I just came across Burr and I'm like WOW, this seems like you guys predicted this exact need when building this. No weird esoteric concepts just because it's AI.",
  },
  {
    name: "Rinat Gareev",
    title: "Senior Solutions Architect",
    company: "Provectus",
    logo: "https://www.google.com/s2/favicons?domain=provectus.com&sz=64",
    quote:
      "Burr's state management part is really helpful for creating state snapshots and build debugging, replaying and even building evaluation cases around that.",
  },
  {
    name: "Hadi Nayebi",
    title: "Co-founder",
    company: "CognitiveGraphs",
    logo: null,
    quote:
      "I have been using Burr over the past few months, and compared to many agentic LLM platforms out there (e.g. LangChain, CrewAi, AutoGen, Agency Swarm, etc), Burr provides a more robust framework for designing complex behaviors.",
  },
  {
    name: "Aditya K.",
    title: "DS Architect",
    company: "TaskHuman",
    logo: `${BASE_PATH}/logos/taskhuman.svg`,
    quote:
      "Moving from LangChain to Burr was a game-changer! It took me just a few hours to get started with Burr, compared to the days and weeks I spent trying to navigate LangChain. I pitched Burr to my teammates, and we pivoted our entire codebase to it.",
  },
  {
    name: "Reddit User",
    title: "Developer",
    company: "r/LocalLlama",
    logo: null,
    quote:
      "Of course, you can use it [LangChain], but whether it's really production-ready and improves the time from code-to-prod, we've been doing LLM apps for two years, and the answer is no. Honestly, take a look at Burr. Thank me later.",
  },
];

export const CODE_SNIPPETS: Record<"chatbot" | "agent" | "statemachine", string> = {
  chatbot: `from burr.core import action, State, ApplicationBuilder

@action(reads=["messages"], writes=["messages"])
def chat(state: State, llm_client) -> State:
    response = llm_client.chat(state["messages"])
    return state.update(
        messages=[*state["messages"], response]
    )

app = (
    ApplicationBuilder()
    .with_actions(chat)
    .with_transitions(("chat", "chat"))
    .with_state(messages=[])
    .with_tracker("local")
    .build()
)

app.run(halt_after=["chat"], inputs={"llm_client": client})`,

  agent: `from burr.core import action, State, ApplicationBuilder

@action(reads=["query", "tools"], writes=["result"])
def plan(state: State, llm) -> State:
    plan = llm.plan(state["query"], state["tools"])
    return state.update(result=plan)

@action(reads=["result"], writes=["output"])
def execute(state: State) -> State:
    output = run_tool(state["result"])
    return state.update(output=output)

@action(reads=["output", "query"], writes=["response"])
def synthesize(state: State, llm) -> State:
    response = llm.summarize(state["output"], state["query"])
    return state.update(response=response)

app = (
    ApplicationBuilder()
    .with_actions(plan, execute, synthesize)
    .with_transitions(
        ("plan", "execute"),
        ("execute", "synthesize"),
    )
    .with_tracker("local")
    .build()
)`,

  statemachine: `from burr.core import action, State, ApplicationBuilder

@action(reads=["counter"], writes=["counter"])
def increment(state: State) -> State:
    return state.update(counter=state["counter"] + 1)

@action(reads=["counter"], writes=["counter"])
def decrement(state: State) -> State:
    return state.update(counter=state["counter"] - 1)

def should_increment(state: State) -> bool:
    return state["counter"] < 10

def should_decrement(state: State) -> bool:
    return state["counter"] >= 10

app = (
    ApplicationBuilder()
    .with_actions(increment, decrement)
    .with_transitions(
        ("increment", "decrement", should_decrement),
        ("increment", "increment", should_increment),
        ("decrement", "increment"),
    )
    .with_state(counter=0)
    .with_tracker("local")
    .build()
)`,
};
