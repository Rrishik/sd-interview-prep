# Chapter 13: Agent Loop Architectures (ReAct, Plan-and-Execute & Multi-Agent DAGs)

*Part IV · Autonomous Agent Systems · 8 min core · 22 min with deep dives*

When people first hear **"AI Agent,"** they often picture something mystical—a digital coworker improvising freely inside a GPU.

Strip away the hype, and an AI Agent is a concrete control loop: **an LLM that can inspect state, call external tools, read the results, and decide what to do next** [1, 2].

Yet the *shape* of that loop dictates whether a user waits `2.3 seconds` or `12 seconds`, whether a request costs `$0.004` or `$0.40`, and whether a failed API call recovers cleanly or traps the model in an infinite retry spiral [1, 2, 3].

{{diagram:05-agent-loops-memory.excalidraw}}

---

### 1) Pure ReAct vs. Plan-and-Execute DAGs

In a classic **ReAct (Reason + Act)** loop, the model alternates `Thought -> Action -> Observation` one step at a time [1]. That works well when Step 2 is unknowable until Step 1 returns, but it hits three walls on longer workflows:
1. **Serial Latency:** Four `300 ms` tools plus five `1.0s` LLM turns take **`5 × 1.0s + 4 × 0.3s = 6.2 seconds`** end-to-end.
2. **Quadratic Tokens (`O(N^2)`):** Every turn re-sends the entire prior trajectory plus new tool outputs.
3. **Local Myopia:** One noisy error trace on Step 2 can derail the model from the original goal.

To cut latency without losing adaptability, production orchestrators separate **Planning** from **Execution** [2, 3]:

| Loop Architecture | How It Executes `K` Tool Steps | LLM Calls | Best Fit | Main Failure Mode |
| :--- | :--- | :--- | :--- | :--- |
| **1. ReAct Loop** | Picks 1 tool (or 1 batch) per turn after reading the prior observation. | **`K + 1` serial calls** | Open-ended debugging where each step depends on the last. | High latency (`6s+`) and `O(N^2)` token growth. |
| **2. Plan-and-Execute DAG** | **Planner** emits a dependency DAG upfront; **Executor** runs independent waves in parallel; **Re-Planner** wakes up only on failure. | **2 calls** on happy path | Multi-source workflows (`get_profile`, `get_orders`, `get_policy` in parallel -> `2.3s` total). | Stale plan if Step 1 invalidates Step 3 without a Re-Planner. |
| **3. Two-Pass Guarded Flow** | **Pass 1** classifies intent and runs read-only probes in parallel; **Pass 2** reasons over sanitized state to propose a verified action. | **Strictly 2 calls** | Diagnostics & system settings where false-positive writes are unacceptable. | Lower recall (`~70%`) if Pass 1 misses an edge-case probe. |

:::deepdive When NOT to Use an Agent: Single LLM vs. Workflow vs. Evaluator-Optimizer vs. Agent | +5 min

Autonomous agents trade away predictability, cost, and latency in exchange for dynamic path discovery. **Always start with the simplest architecture that solves the task [2, 4]:**

| Pattern | Who Owns Control Flow? | Latency & Cost | Choose When... | Avoid When... |
| :--- | :--- | :--- | :--- | :--- |
| **1. Single LLM Call (+ RAG)** | Application code (`1` turn) | **`~0.8s`**, `$` | Summarization, extraction, classification, single-shot Q&A. | Answering requires conditional multi-system actions. |
| **2. Deterministic Workflow (Pipeline / Router)** | Application code (`if/else` DAG of fixed prompts/APIs) | **`1.2–2.5s`**, `$` | Known steps: *Classify ticket -> Fetch order -> Apply refund table -> Draft reply*. | You cannot enumerate the needed steps ahead of time. |
| **3. Evaluator-Optimizer Loop** | Code loop between **Generator** & **Critic/Compiler** (`max 3` retries) | **`2–5s`**, `$$` | Clear verification signal exists: SQL/code generation checked by compiler, or translation checked by rubric. | There is no reliable automated grader (critic just adds latency). |
| **4. Autonomous Agent** | **The LLM** chooses tools, sequence, and stopping point | **`3–30s+`**, `$$$` | Unpredictable trajectories: investigating a novel prod outage or multi-file bug fix. | Regulatory/financial flows where deterministic code handles `95%` of cases. |

**Interview Rule of Thumb:** In a customer-support system, use a **Deterministic Router + Workflow** for the `80%` structured intents (password reset, shipping status, standard return), and escalate only the `20%` ambiguous multi-policy exceptions to a **Bounded Agent** [2, 4].

:::

---

### 2) Multi-Agent Specialization, Handoffs & Conflict Resolution

Why not give one giant agent **80+ tools** across billing, diagnostics, and logistics?
Because once a single agent's tool registry crosses **`15–20 tools`**, overlapping descriptions degrade function-calling accuracy and burn `10,000+` schema tokens per turn [2].

Instead, split work across **specialist agents** (`5–8` domain tools each) using three coordination patterns:
- **Supervisor Router:** A lightweight triage agent decomposes the request, dispatches sub-tasks to specialist workers, and merges their structured outputs.
- **Peer Handoffs:** A specialist invokes an explicit transfer tool (`transfer_to_billing(compacted_state)`), handing control directly to the next specialist without an extra supervisor round-trip.
- **Blackboard Arbiter (Conflict Resolution):** Parallel sub-agents never execute external writes directly. They post **typed action proposals** to a shared `AgentState` blackboard, and a deterministic **Policy Arbiter** resolves conflicts by priority (`FraudHold > Compliance > CreditGrant`) before any mutation runs.

:::deepdive Agents-as-Tools vs. Handoffs (Centralized vs. Decentralized Reply Ownership) | +5 min

When orchestrating multiple agents, the first architectural decision is **who owns the user-facing conversation** [5]:

| Dimension | `Agents-as-Tools` *(Manager-Worker)* | `Handoffs` *(Decentralized Transfer)* |
| :--- | :--- | :--- |
| **Mechanics** | Manager agent stays active and invokes `ask_tax_specialist(query)` like a regular function call, receiving structured JSON back. | Triage agent calls `transfer_to_billing()`, exiting the loop so `BillingAgent` talks directly to the user on subsequent turns. |
| **Reply Ownership** | **Centralized:** One manager enforces consistent tone, guardrails, and cross-domain synthesis. | **Decentralized:** Active specialist owns both tool execution and the user reply until another handoff occurs. |
| **Latency & Cost** | Higher (`Manager -> Worker -> Manager -> User` adds an extra synthesis LLM hop). | Lower (`Specialist -> User` directly; avoids double-summarizing follow-up turns). |
| **Best Use Case** | One question spanning **multiple domains** (*"Compare my AWS spend, open Jira blockers, and Q4 hiring budget"*). | Sequential **multi-turn domain takeover** (*"I want to dispute a charge"* -> 4 back-and-forth turns inside Billing). |

**Preventing Handoff Ping-Pong:** Pass a structured `handoff_context` summary (goal, verified entities, visited agents) and cap `max_handoffs_per_turn = 2` so `BillingAgent` and `TechSupportAgent` can never bounce a user back and forth infinitely [5].

:::

---

### 3) Loop Termination & Precision vs. Recall Trade-Offs

- **Hard Loop Ceilings:** Enforce strict caps on `max_steps` (e.g., `6`), `max_token_budget`, and `wall_clock_timeout_ms`, plus duplicate call detection (`hash(tool_name + canonical_args)`) to break retry loops immediately.
- **Precision First on Write Actions:** When an agent can mutate user settings or production records, a **False Positive** breaks state (high blast radius), while a **False Negative** safely falls back to standard search. Tune thresholds for **`>90%` precision** first, then expand tool coverage to raise recall.

:::deepdive Native Reasoning Channels, ReWOO, CRITIC, Reflexion & LATS Search | +4 min

1. **From Prompt `Thought:` Strings to Native Reasoning Channels [1, 11]:**
   - Early 2022 ReAct prompted models to print literal `"Thought: ..."` strings inside the visible assistant reply [1]. Modern reasoning APIs (`Responses API`, `Extended Thinking`) move internal reasoning onto a **dedicated reasoning channel** passed (often encrypted) across tool turns—preserving multi-step latent plans without leaking raw chain-of-thought into user replies [11].
2. **Advanced Reasoning & Search Loops (`ReWOO`, `CRITIC`, `Reflexion`, `LATS`):**

| Pattern | Core Mechanism | Token & Latency Profile | Best Production Use Case |
| :--- | :--- | :--- | :--- |
| **`ReWOO`** *(Xu et al.)* [6] | **Planner** emits full step graph with `#E1`, `#E2` placeholders; **Workers** run tools without chat history; **Solver** answers once. | **`~5×` fewer tokens** than ReAct; enables distilling Planner into a `7B–8B` model. | Known-tool research & multi-API lookups where observations don't alter topology. |
| **`CRITIC`** *(Gou et al.)* [7, 8] | Replaces ungrounded `Self-Refine` [7] with **external verifier feedback** (compiler, unit tests, SQL `EXPLAIN`, calculator) on each critique loop. | `2–4` turns; high precision because feedback is deterministic truth. | Code/SQL synthesis, schema repair, and factual claim verification. |
| **`Reflexion`** *(Shinn et al.)* [9] | On trial failure, a **Self-Reflector** writes a short verbal postmortem into an episodic buffer prepended to the next attempt (*Verbal RL*). | `2–3` full episode retries, zero weight updates. | Iterative test-fixing and multi-step debugging tasks. |
| **`ToT` / `LATS`** *(Yao; Zhou et al.)* [10] | **Monte Carlo Tree Search (`MCTS`)** over reasoning/action branches (`Select -> Expand -> Simulate -> Backpropagate`). | **`10–30×` token multiplier** (never run over non-idempotent write tools!). | High-stakes offline code synthesis, theorem proving, or complex planning. |

3. **State Graphs vs. Actor Mailboxes [11]:** Use **Checkpointed State Graphs** (typed shared state + deterministic node reducers) for auditable single-workflow orchestration, and **Async Actor Runtimes** (isolated per-agent message mailboxes with independent crash supervision) for event-driven multi-agent concurrency.

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **ReAct** is a detective opening one door at a time with no floor plan. **Plan-and-Execute** is an architect handing a dependency blueprint (DAG) to an electrician, plumber, and painter so they work on independent rooms in parallel and only call the architect back if they hit an unexpected steel beam.
- **Where the analogy breaks:** Human tradespeople use common sense if a pipe is an inch off. A DAG executor will pass `null` into Step 3 if Step 1's output schema shifts—requiring a **JSON Schema validator + conditional re-planner** between waves.
- **Real production system:** **Anthropic Claude Code**, **OpenAI Agents SDK**, and **LLM Compiler** combine upfront task decomposition with parallel read-tool waves and confirmation-gated writes [2, 3, 5].

---

### Quick Self-Check

<details>
<summary><strong>Q1: An agent must call 4 independent read APIs (300 ms each) and synthesize an answer. If each LLM call takes 1.0s, how much faster is a parallel DAG planner than sequential single-tool ReAct?</strong></summary>
<p><strong>Answer:</strong> Sequential ReAct takes <code>4 × (1.0s LLM + 0.3s tool) + 1.0s synthesis = 6.2s</code>. A parallel DAG planner takes <code>1.0s Planner + 0.3s (4 tools in parallel) + 1.0s Synthesizer = 2.3s</code> (nearly <strong>3× faster</strong>).</p>
</details>

<details>
<summary><strong>Q2: Why does tool-calling accuracy drop when one agent is given 80+ tools, and how do specialist agents fix it?</strong></summary>
<p><strong>Answer:</strong> Above <code>15–20 tools</code>, overlapping descriptions and large JSON schemas bloat the prompt and confuse attention selection. Scoping each specialist agent to <code>5–10</code> domain tools plus explicit handoff functions keeps prompts lean and tool selection precision above 90%.</p>
</details>

<details>
<summary><strong>Q3: Two parallel sub-agents inspect an account: <code>RetentionAgent</code> proposes a $50 credit while <code>FraudAgent</code> flags the account for suspension. How do you prevent conflicting side effects?</strong></summary>
<p><strong>Answer:</strong> Parallel sub-agents emit <strong>typed action proposals</strong> to a shared state blackboard rather than calling write APIs directly; a deterministic <strong>Policy Arbiter</strong> resolves conflicts by priority (<code>FraudHold &gt; CreditGrant</code>) before committing any mutation.</p>
</details>

<details>
<summary><strong>Q4: When should you choose <code>Agents-as-Tools</code> over <code>Handoffs</code> in a multi-agent system?</strong></summary>
<p><strong>Answer:</strong> Choose <strong><code>Agents-as-Tools</code></strong> when a single user request requires synthesizing outputs from multiple specialists under one unified persona and policy gate. Choose <strong><code>Handoffs</code></strong> when a specialist should take over a multi-turn conversation directly without paying extra manager round-trip latency.</p>
</details>

---

### Sources & References
- **[1]** Shunyu Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models* (ICLR 2023) — [arxiv.org/abs/2210.03629](https://arxiv.org/abs/2210.03629)
- **[2]** Anthropic Engineering, *Building Effective Agents* (2024) — [anthropic.com/research/building-effective-agents](https://www.anthropic.com/research/building-effective-agents)
- **[3]** Sehoon Kim et al., *An LLM Compiler for Parallel Function Calling* (ICML 2024) — [arxiv.org/abs/2312.04511](https://arxiv.org/abs/2312.04511)
- **[4]** Anthropic Engineering, *How We Built Our Multi-Agent Research System* (2025) — [anthropic.com/research/multi-agent-research-system](https://www.anthropic.com/research/multi-agent-research-system)
- **[5]** OpenAI Developers, *Orchestrating Multiple Agents: Handoffs vs. Agents-as-Tools* (2025–2026) — [developers.openai.com/api/docs/guides/agents/orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration)
- **[6]** Binfeng Xu et al., *ReWOO: Decoupling Reasoning from Observations for Efficient Augmented Language Models* (2023) — [arxiv.org/abs/2305.18323](https://arxiv.org/abs/2305.18323)
- **[7]** Aman Madaan et al., *Self-Refine: Iterative Refinement with Self-Feedback* (NeurIPS 2023) — [arxiv.org/abs/2303.17651](https://arxiv.org/abs/2303.17651)
- **[8]** Zhibin Gou et al., *CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing* (ICLR 2024) — [arxiv.org/abs/2305.11738](https://arxiv.org/abs/2305.11738)
- **[9]** Noah Shinn et al., *Reflexion: Language Agents with Verbal Reinforcement Learning* (NeurIPS 2023) — [arxiv.org/abs/2303.11366](https://arxiv.org/abs/2303.11366)
- **[10]** Andy Zhou et al., *Language Agent Tree Search (LATS)* (ICML 2024) — [arxiv.org/abs/2310.04406](https://arxiv.org/abs/2310.04406)
- **[11]** Rohit Ghumare et al., *AI Engineering from Scratch — Phase 14: The Agent Loop, ReWOO, CRITIC & Actor Runtimes* — [aiengineeringfromscratch.com/learn/agent-engineering/the-agent-loop](https://aiengineeringfromscratch.com/learn/agent-engineering/the-agent-loop)
