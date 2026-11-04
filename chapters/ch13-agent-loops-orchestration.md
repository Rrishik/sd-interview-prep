# Chapter 13: Agent Loop Architectures (ReAct, Plan-and-Execute & Multi-Agent DAGs)

*Part III · AI & LLM Engineering Systems · 8 min read*

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

---

### 2) Multi-Agent Specialization, Handoffs & Conflict Resolution

Why not give one giant agent **80+ tools** across billing, diagnostics, and logistics?
Because once a single agent's tool registry crosses **`15–20 tools`**, overlapping descriptions degrade function-calling accuracy and burn `10,000+` schema tokens per turn [2].

Instead, split work across **specialist agents** (`5–8` domain tools each) using three coordination patterns:
- **Supervisor Router:** A lightweight triage agent decomposes the request, dispatches sub-tasks to specialist workers, and merges their structured outputs.
- **Peer Handoffs:** A specialist invokes an explicit transfer tool (`transfer_to_billing(compacted_state)`), handing control directly to the next specialist without an extra supervisor round-trip.
- **Blackboard Arbiter (Conflict Resolution):** Parallel sub-agents never execute external writes directly. They post **typed action proposals** to a shared `AgentState` blackboard, and a deterministic **Policy Arbiter** resolves conflicts by priority (`FraudHold > Compliance > CreditGrant`) before any mutation runs.

---

### 3) Loop Termination & Precision vs. Recall Trade-Offs

- **Hard Loop Ceilings:** Enforce strict caps on `max_steps` (e.g., `6`), `max_token_budget`, and `wall_clock_timeout_ms`, plus duplicate call detection (`hash(tool_name + canonical_args)`) to break retry loops immediately.
- **Precision First on Write Actions:** When an agent can mutate user settings or production records, a **False Positive** breaks state (high blast radius), while a **False Negative** safely falls back to standard search. Tune thresholds for **`>90%` precision** first, then expand tool coverage to raise recall.

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **ReAct** is a detective opening one door at a time with no floor plan. **Plan-and-Execute** is an architect handing a dependency blueprint (DAG) to an electrician, plumber, and painter so they work on independent rooms in parallel and only call the architect back if they hit an unexpected steel beam.
- **Where the analogy breaks:** Human tradespeople use common sense if a pipe is an inch off. A DAG executor will pass `null` into Step 3 if Step 1's output schema shifts—requiring a **JSON Schema validator + conditional re-planner** between waves.
- **Real production system:** **Anthropic Claude Code** and **LLM Compiler** combine upfront task decomposition with parallel read-tool waves and confirmation-gated writes [2, 3].

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

---

### Sources & References
- **[1]** Shunyu Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models* (ICLR 2023) — [arxiv.org/abs/2210.03629](https://arxiv.org/abs/2210.03629)
- **[2]** Anthropic Engineering, *Building Effective Agents* (2024) — [anthropic.com/research/building-effective-agents](https://www.anthropic.com/research/building-effective-agents)
- **[3]** Sehoon Kim et al., *An LLM Compiler for Parallel Function Calling* (ICML 2024) — [arxiv.org/abs/2312.04511](https://arxiv.org/abs/2312.04511)
