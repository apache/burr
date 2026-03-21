export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || "";

export const GITHUB_REPO = "https://github.com/apache/burr";
export const DOCS_URL = "/docs";
export const DISCORD_URL = "https://discord.gg/6Zy2DwP4f3";
export const TWITTER_URL = "https://x.com/buraborr";

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
    name: "Alex Johnson",
    title: "ML Engineer",
    company: "Acme Corp",
    quote:
      "Burr completely changed how we build AI agents. The state management and observability are game-changers for production systems.",
  },
  {
    name: "Sarah Chen",
    title: "Staff Engineer",
    company: "TechFlow",
    quote:
      "We moved from a tangled mess of LangChain callbacks to clean, testable Burr actions. Our team velocity doubled.",
  },
  {
    name: "Marcus Rivera",
    title: "CTO",
    company: "DataPilot",
    quote:
      "The Burr UI alone is worth it. Being able to replay and debug agent runs saved us countless hours of debugging.",
  },
  {
    name: "Priya Patel",
    title: "AI Engineer",
    company: "NeuralWorks",
    quote:
      "Human-in-the-loop was trivial to add with Burr. We went from prototype to production approval workflow in a day.",
  },
  {
    name: "David Kim",
    title: "Senior Developer",
    company: "CloudScale",
    quote:
      "Pure Python, no magic, no hidden abstractions. Burr lets us build exactly what we need without fighting the framework.",
  },
  {
    name: "Emma Wilson",
    title: "Tech Lead",
    company: "Subreddit",
    quote:
      "Persistence and replay are incredible for debugging complex multi-step agents. Burr makes the hard parts easy.",
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
