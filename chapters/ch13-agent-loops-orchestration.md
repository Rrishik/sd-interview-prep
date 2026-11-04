# Chapter 13: Agent Loop Architectures (ReAct, Plan-and-Execute & Multi-Agent DAGs)

*Part IV · Autonomous Agent Systems · 9 min read*

When people first hear the term **"AI Agent,"** they often picture something mystical—a digital coworker improvising freely inside a GPU.

Strip away the hype, and an AI Agent is a concrete piece of systems engineering: **an LLM running inside a control loop that can inspect state, invoke external tools, observe the results, and decide what to do next** [1, 2].

Yet the *shape* of that control loop determines everything about your production system: whether a user waits `1.8 seconds` or `25 seconds`, whether a single request costs `$0.004` or `$0.40`, and whether a failed API call gracefully recovers or sends the model into an infinite retry spiral.

Let us design the four production agent loop patterns shown in the upper half of the architecture diagram below [1, 2, 3].

{{diagram:05-agent-loops-memory.excalidraw}}

---

### 1) The Classic ReAct Loop (Reason + Act)

Before 2022, engineers either asked an LLM to reason silently in its head (**Chain-of-Thought**, which hallucinates facts it cannot look up) or asked it to emit a single function call (**Action-only**, which fails on multi-step problems).

Shunyu Yao et al. introduced **ReAct (Reason + Act)** [1], which interleaves verbal reasoning with real tool execution in an iterative `Thought -> Action -> Observation` loop:

1. **Thought:** The LLM writes down *why* it needs information (*"The user's audio is cutting out; I should check microphone permissions and exclusive-mode conflicts first"*).
2. **Action:** The LLM emits a structured tool call (`get_audio_diagnostics(include_permissions=true)`).
3. **Observation:** The runtime harness executes the tool against the real system and appends the JSON output (`{"mic_permission": "granted", "exclusive_mode_conflict": true}`) back into the prompt.
4. **Next Iteration:** The LLM reads the observation, emits a new `Thought`, and either calls another tool or returns the `Final Answer`.

**Where Pure ReAct Breaks in Production:**
- **Serial Latency Multiplication:** A 6-step workflow requires **6 sequential LLM round-trips**. At `1.2 seconds` per LLM turn plus `300 ms` per tool call, the user stares at a spinner for **`9+ seconds`**.
- **Quadratic Token Accumulation (`O(N^2)`):** Turn 1 sends `2,000` tokens; Turn 2 re-sends Turn 1's `2,000` tokens plus a `1,000`-token observation; by Turn 8, a single user query has billed `40,000+` input tokens.
- **Local Myopia:** Because ReAct only plans one step ahead, a noisy stack trace on Step 2 can derail the model from answering the user's original goal.

---

### 2) Plan-and-Execute, Adaptive DAGs & Two-Pass Guarded Flows

To eliminate serial LLM round-trips on multi-step workflows, production orchestrators separate **Planning** from **Execution** [2, 3]:

| Architecture Pattern | How It Works | LLM Calls (`K` tool steps) | Best Production Fit | Primary Failure Mode |
| :--- | :--- | :--- | :--- | :--- |
| **1. ReAct Loop** | Chooses 1 tool (or 1 parallel batch) per turn after inspecting the prior observation. | **`K + 1` sequential calls** | Open-ended debugging where Step 2 is unknowable until Step 1 returns. | High latency, token bloat, and wandering loops. |
| **2. Plan-and-Execute (DAG)** | **Planner LLM** emits a full dependency DAG upfront; **Executor** runs independent waves in parallel; **Re-Planner** wakes up only on failure. | **2 calls** in the happy path (Planner + Synthesizer). | Long structured workflows (order fulfillment, multi-source enterprise reports). | **Stale plan:** Step 1's output invalidates Step 3's assumptions if no Re-Planner exists. |
| **3. Two-Pass Guarded Flow** | **Pass 1** classifies intent and runs read-only diagnostic tools in parallel; **Pass 2** reasons over sanitized telemetry to propose a verified action. | **Strictly 2 calls** (bounded `p99` latency). | Client/OS diagnostics & system settings where false-positive writes are unacceptable. | Lower recall (`~70%`) if Pass 1 omits an edge-case diagnostic probe. |

**How the DAG Wave Executor Works Without Calling the LLM Between Steps:**
1. The Planner outputs a JSON Directed Acyclic Graph (DAG) of tool steps where each node lists its parent dependencies (`deps: ["step_1"]`).
2. The orchestrator finds all ready nodes with `in_degree == 0` (for example, `get_user_profile`, `get_recent_orders`, `search_refund_policy`) and dispatches them **concurrently** (`Mono.zip` in Java / `asyncio.gather` in Python / `Task.WhenAll` in C#).
3. As parent nodes finish, their structured outputs are substituted into child arguments (`$step_1.account_tier`), and the next wave executes immediately.
4. **Adaptive Re-Planning:** The heavy Re-Planner LLM is invoked **only** if a tool returns a non-retryable error, an empty result that blocks a downstream dependency, or a schema violation [3].

---

### 3) Multi-Agent Orchestration: Role Specialization, Handoffs & Conflict Resolution

Why split one agent into **multiple specialized agents**?

If you build a single "God Agent" and hand it **80+ tools** across billing, hardware diagnostics, logistics, and HR policies, two things fail immediately:
- **Tool Selection Degradation:** Once a single agent's tool registry exceeds **`15–20 tools`**, overlapping descriptions cause function-calling precision to drop sharply.
- **Prompt Context Bloat:** Sending 80 JSON Schema definitions on every turn burns `12,000+` tokens before the user even speaks.

**Three Patterns for Multi-Agent Collaboration [2]:**
1. **Supervisor / Router Pattern (Centralized):** A lightweight **Triage Supervisor** decomposes the request, delegates sub-tasks to specialist workers (`DiagnosticsAgent`, `BillingAgent`, `PolicyAgent`), and merges their structured responses.
2. **Peer Handoff / State-Graph Pattern (Decentralized):** Each specialist agent carries only its `5–8` domain tools plus explicit **Handoff Tools** (`transfer_to_billing_agent(summary)`). When `DiagnosticsAgent` finishes hardware checks and spots an invoice dispute, it transfers control and a **compacted state summary** directly to `BillingAgent` without paying for an extra supervisor round-trip.
3. **Blackboard Conflict Resolution:** When two specialist agents run in parallel and propose contradictory actions (for example, `RetentionAgent` proposes a `$50` credit while `FraudAgent` flags the account for suspension), sub-agents never execute external writes directly. They write **typed action proposals** to a shared `AgentState` blackboard, and a deterministic **Policy Arbiter** resolves conflicts using priority rules (`FraudHold > Compliance > CreditGrant`) and optimistic concurrency (`version` check).

---

### 4) Important Focus Areas for Interviews

- **Latency Math (`ReAct` vs `DAG`):** Always quantify wall-clock savings. Four independent `300 ms` tools plus `1.0s` per LLM call take `5 × 1.0s + 4 × 0.3s = 6.2s` in sequential ReAct, versus `1.0s (Planner) + 0.3s (4 parallel tools) + 1.0s (Synthesizer) = 2.3s` in a DAG orchestrator.
- **Precision vs. Recall Trade-Off in Action Agents:** In agents that mutate settings or production records, a **False Positive** breaks user state (high blast radius), whereas a **False Negative** safely falls back to standard UI search. Tune confidence thresholds and schema validators for **`>90%` precision** first, then expand tool coverage to improve recall.
- **Loop Termination Guarantees:** Every agent loop must enforce hard ceilings on `max_steps` (e.g., `6`), `max_token_budget`, and `wall_clock_timeout_ms`, plus duplicate tool-call detection (`hash(tool_name + canonical_args)`) to break infinite retry cycles immediately.

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **ReAct** is like a detective walking into a building with no blueprint: they open one door, look around, think, and pick the next door. **Plan-and-Execute** is an architect handing a dependency blueprint (DAG) to a crew: the electrician, plumber, and painter work on independent rooms in parallel and only call the architect back if they hit an unexpected steel beam behind a wall.
- **Where the analogy breaks:** Human crew members use common sense if a measurement is off by an inch. A deterministic DAG executor will pass `null` into Step 4 if Step 2's output schema shifts—which is why a **strict JSON Schema validator + conditional re-planner** between waves is mandatory.
- **Real production system:** **Anthropic Claude Code** and **Enterprise Customer Support Orchestrators** combine upfront task decomposition with bounded inner tool loops and strict separation between read-only inspection tools and confirmation-gated write tools [2].

---

### Quick Self-Check

<details>
<summary><strong>Q1: What are the three phases of a single ReAct turn, and why does pure ReAct struggle on a 10-step workflow?</strong></summary>
<p><strong>Answer:</strong> Each ReAct turn runs <strong>Thought</strong> (verbal reasoning), <strong>Action</strong> (tool call JSON), and <strong>Observation</strong> (tool result). On a 10-step workflow, pure ReAct makes 10 sequential LLM calls (multiplying tail latency) and re-sends the growing trajectory on every turn (<code>O(N^2)</code> token cost) while lacking a global multi-step plan.</p>
</details>

<details>
<summary><strong>Q2: When does a static Plan-and-Execute agent fail compared to ReAct, and how do production systems fix it?</strong></summary>
<p><strong>Answer:</strong> Static Plan-and-Execute fails when an early step returns unexpected data or an error that invalidates downstream steps in the upfront plan. Production systems fix this with <strong>Adaptive Re-Planning</strong>: independent DAG waves run automatically, and a Re-Planner LLM is triggered only when a step fails or violates expected post-conditions.</p>
</details>

<details>
<summary><strong>Q3: An agent needs to call 4 independent read APIs (300 ms each) and synthesize an answer. If each LLM call takes 1.0s, how much faster is a parallel DAG planner than sequential single-tool ReAct?</strong></summary>
<p><strong>Answer:</strong> Sequential ReAct takes <code>4 × (1.0s LLM + 0.3s tool) + 1.0s synthesis = 6.2 seconds</code>. A parallel DAG planner takes <code>1.0s Planner + max(0.3s across 4 parallel tools) + 1.0s Synthesizer = 2.3 seconds</code> (nearly <strong>3× faster</strong>).</p>
</details>

<details>
<summary><strong>Q4: Why does tool-calling accuracy drop when a single agent is given 80+ tools, and how do multi-agent handoffs solve this?</strong></summary>
<p><strong>Answer:</strong> Above <code>15–20 tools</code>, overlapping tool descriptions and huge JSON schemas bloat the prompt and confuse attention selection. Multi-agent architectures scope each specialist agent to <code>5–10</code> domain tools plus explicit handoff functions, keeping prompts compact and tool selection precision above 90%.</p>
</details>

<details>
<summary><strong>Q5: Two parallel sub-agents analyze a customer account: <code>RetentionAgent</code> proposes a $50 credit while <code>FraudAgent</code> flags the account for suspension. How do you prevent conflicting side effects?</strong></summary>
<p><strong>Answer:</strong> Sub-agents must never execute state-mutating write tools directly during parallel exploration; instead, they emit <strong>typed action proposals</strong> to a shared state blackboard, and a deterministic <strong>Policy Arbiter</strong> resolves conflicts by priority rules (<code>FraudHold &gt; CreditGrant</code>) before committing any side effect.</p>
</details>

---

### Sources & References
- **[1]** Shunyu Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models* (ICLR 2023) — [arxiv.org/abs/2210.03629](https://arxiv.org/abs/2210.03629)
- **[2]** Anthropic Engineering, *Building Effective Agents* (2024) — [anthropic.com/research/building-effective-agents](https://www.anthropic.com/research/building-effective-agents)
- **[3]** Sehoon Kim et al., *An LLM Compiler for Parallel Function Calling* (ICML 2024) — [arxiv.org/abs/2312.04511](https://arxiv.org/abs/2312.04511)
