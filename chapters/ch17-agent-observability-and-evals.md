# Chapter 17: Agent Observability (OpenTelemetry), Deterministic Replay Harnesses & Canary Rollouts

*Part IV · Autonomous Agent Systems · 9 min read*

When a standard REST microservice fails, debugging takes two minutes: you filter logs for `HTTP 500`, read the stack trace, and write a unit test.

When an **autonomous multi-step agent** fails in production, the HTTP status code is **`200 OK`**! Nothing crashed. Instead, on Step 3 of a 6-step workflow, a subtle prompt edit caused the planner to pass `include_archived=false` to a search tool, which returned 0 records, which convinced the synthesizer to tell an enterprise customer that their warranty had expired.

How do you trace, unit-test, version, and safely deploy software that is **non-deterministic** by nature?

Let us build the **Production Agent Observability, Replay Testing & Canary Rollout Pipeline** shown in the bottom middle of the diagram in Chapter 15 [1, 2, 3].

---

### 1) Distributed Tracing for Agents with OpenTelemetry (`gen_ai.*` Spans)

A single agent request is not a flat function call—it is a **tree of nested operations** spanning memory lookups, planner LLM calls, parallel MCP tool waves, and streamed synthesis.

Using **OpenTelemetry (OTel)** with the standard `gen_ai.*` semantic conventions, the orchestrator emits a hierarchical **Trace** [1]:

| Span Level | Span Name Example | Key OTel Attributes Captured on the Span | Why On-Call Engineers Need It |
| :--- | :--- | :--- | :--- |
| **Root Span** | `agent.run` | `trace_id`, `user_id`, `agent_name`, `prompt_sha`, `graph_version`, `total_cost_usd`, `termination_reason` | Pinpoints which exact version of the prompt/graph ran and whether it succeeded or hit `MAX_STEPS`. |
| **Child Span (Memory)** | `memory.retrieve` | `db.system="pgvector"`, `top_k=5`, `latency_ms=18`, `filters="user_id,acl"` | Reveals whether slow agent turns are caused by vector DB queries or the LLM. |
| **Child Span (LLM)** | `gen_ai.chat` | `gen_ai.request.model`, `input_tokens`, `cached_input_tokens`, `output_tokens`, `ttft_ms`, `temperature` | Tracks **KV cache hit ratio**, token burn per tenant, and Time-To-First-Token regressions. |
| **Child Span (Tool Wave)** | `mcp.tool.execute` | `tool.name`, `tool.idempotency_key`, `tool.is_error`, `retry_count`, `latency_ms` | Identifies flaky upstream MCP servers and schema validation failures. |

**Privacy-Preserving Trace Export:**
Never dump raw unredacted customer PII into your observability cluster. Run a deterministic **PII Redactor** in the OpenTelemetry Collector pipeline before spans land in Jaeger/Honeycomb/Arize Phoenix, and store raw encrypted prompt/completion payloads in a separate access-controlled audit store with a strict `30-day` retention TTL.

---

### 2) Deterministic Test Harnesses & Cassette Replay (Testing Non-Deterministic Agents)

Interviewers love asking:
> *"LLMs are non-deterministic, slow (`2s/call`), and cost money, and tools mutate external databases. How do you run a fast, deterministic test suite on every Pull Request?"*

The answer combines **Dependency Injection (Inversion of Control)** with a **Three-Tier Testing Pyramid** [2, 3]:

1. **Tier 1 — Deterministic Cassette Replay (`VCR` Mode on Every Commit, `< 2s`, `$0`):**
   - Because the orchestrator receives `LLMClient` and `ToolExecutor` via **Dependency Injection** (constructor interfaces rather than hardcoded HTTP calls), unit tests inject a **Cassette Replay Harness**.
   - The harness replays recorded JSON responses from golden production traces deterministically in memory. This tests `100%` of your **deterministic orchestration code**—DAG topological sorting, parallel wave scheduling, error retry backoff, context compaction, and policy guardrails—in milliseconds with zero LLM spend.
2. **Tier 2 — Sandboxed Golden Trajectory Suite (`temperature = 0` on Pre-Merge CI, `~3 min`):**
   - Runs a real LLM (`temperature = 0`, fixed `seed`) against **stateful in-memory mock tools** (for example, an in-memory SQLite database pre-seeded with tricky edge-case accounts) across `100–300` golden scenarios [3].
   - **How to grade trajectories without brittle string matching:** Because an agent can validly call two independent tools `[get_profile, get_orders]` in either order, do **not** assert exact list equality on tool logs. Instead, assert:
     - **Final Environment State Match:** Did the in-memory database / settings state end up in the exact expected state?
     - **DAG-Valid Tool Call F1:** Precision and recall of `(tool_name, normalized_args)` against the required set, plus `0` calls to forbidden write tools.
3. **Tier 3 — Calibrated LLM-as-a-Judge Rubrics:**
   - Never ask a judge LLM *"Score this answer from 1 to 10"* (which produces noisy, high-variance numbers).
   - Force the judge to evaluate a **binary (`0/1`) checklist rubric** (*"1. Did the answer cite the exact error code from the tool output? [PASS/FAIL] 2. Did it hallucinate any unsupported policy? [PASS/FAIL]"*) and require a 1-sentence evidence quote before the verdict [2].

---

### 3) Versioning Prompts, Tools & Graphs + Progressive Canary Rollouts

In an agentic system, **changing two words in a system prompt or a tool description can break production just as severely as changing Java code**. Treat every prompt, tool JSON schema, and agent graph definition as an **immutable, content-addressed artifact** in Git (`prompt_sha`, `tool_schema_version`).

**The 4-Stage Safe Deployment Pipeline for Agent Changes:**
1. **Offline CI Gate:** Candidate version `v2.5` must achieve **`>= 90%` precision** on the Golden Trajectory Suite with **zero** security/guardrail regressions.
2. **Shadow / Dark Traffic Mode (`1%` Live Fork, Dry-Run Writes):** Fork `1%` of live production requests asynchronously to `v2.5` where all state-mutating tools are stubbed in **dry-run mode**. Log any divergence between `v2.5`'s proposed actions and `v2.4`'s actual actions.
3. **Canary Flighting (`1% -> 10% -> 50% -> 100%`):** Route `1%` of real users to `v2.5`. Monitor real-time OpenTelemetry health signals:
   - **System Signals:** `tool_error_rate`, `max_steps_exceeded_rate`, `p95_ttft_ms`, `tokens_per_run`.
   - **Quality Signals:** User explicit undo/thumbs-down rate, immediate re-query rate, and async `5%` Kafka LLM-as-Judge faithfulness scores.
4. **Instant Feature-Flag Rollback:** If the canary's `tool_error_rate` or hallucination rate spikes past the SLO threshold, automatically flip the routing pointer back to `v2.4` in under `5 seconds`.

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** Deploying an updated AI agent is like deploying new **autopilot flight-control firmware**. You never test new firmware for the first time with 300 passengers in the air. First, you test the wiring with pre-recorded electrical signals (`Cassette Replay`), then you fly 500 stormy landings in a flight simulator (`Sandboxed Golden Evals`), then you run the new computer in "shadow mode" next to the human pilot (`Shadow Traffic`), and finally you enable it on 1% of flights (`Canary`).
- **Where the analogy breaks:** Physics in a flight simulator obeys fixed differential equations. Real human users invent brand-new slang, paste broken logs, and trigger new failure modes every week—so **every production failure caught in the wild must be anonymized and added back into your Golden Evaluation Dataset** (a continuous eval flywheel) [2].
- **Real production system:** **Microsoft Edge Assisted Settings** and **Apple Internal Agent Platforms** gate global rollouts on offline precision/recall rubrics (`>90%` precision) followed by progressive Canary telemetry validation.

---

### Quick Self-Check

<details>
<summary><strong>Q1: What span hierarchy should an OpenTelemetry trace capture for an agent run, and why is <code>cached_input_tokens</code> a critical span attribute?</strong></summary>
<p><strong>Answer:</strong> A root <code>agent.run</code> span with child spans for each <code>memory.retrieve</code>, <code>gen_ai.chat</code> (LLM call), and <code>mcp.tool.execute</code> wave. Tracking <code>cached_input_tokens</code> alongside <code>input_tokens</code> immediately alerts you if a prompt change accidentally broke your KV prefix cache hit rate.</p>
</details>

<details>
<summary><strong>Q2: How does Dependency Injection allow you to test an agent orchestrator's retry, compaction, and DAG routing logic in under 2 seconds at $0 cost?</strong></summary>
<p><strong>Answer:</strong> By injecting interfaces (<code>LLMClient</code>, <code>ToolRegistry</code>, <code>MemoryStore</code>) via the constructor, unit tests can supply a <strong>Deterministic Cassette Replay client</strong> that returns pre-recorded LLM and tool payloads in memory—verifying all orchestration control flow deterministically without making network or GPU calls.</p>
</details>

<details>
<summary><strong>Q3: Why is asserting an exact ordered list of tool calls a brittle metric for evaluating multi-step agents, and what should you assert instead?</strong></summary>
<p><strong>Answer:</strong> Independent read tools (such as <code>get_user</code> and <code>get_orders</code>) can validly execute in any order or in parallel. Instead, assert (1) <strong>Final Sandbox State Match</strong> (did the mocked database reach the right final state?), (2) <strong>DAG-Valid Tool Call Precision &amp; Recall</strong>, and (3) <strong>Zero Forbidden Write Tool Calls</strong>.</p>
</details>

<details>
<summary><strong>Q4: When running a new agent version in Shadow (Dark Traffic) mode on 1% of live requests, how do you prevent the shadow agent from mutating production data?</strong></summary>
<p><strong>Answer:</strong> Configure the shadow agent's injected <code>ToolExecutor</code> to run all read-only tools normally (or read from the primary agent's cached observations) while intercepting all state-mutating write tools in <strong>dry-run / no-op mode</strong>, logging the proposed write payload for offline comparison.</p>
</details>

<details>
<summary><strong>Q5: Why does asking an LLM-as-a-Judge to "rate this response from 1 to 10" fail in production CI gates, and how do you fix it?</strong></summary>
<p><strong>Answer:</strong> Open-ended `1–10` scales suffer from high variance and central-tendency bias (`7/10` on everything). Fix it by setting <code>temperature = 0</code>, breaking the rubric into explicit <strong>binary (`PASS/FAIL`) checklist items</strong>, requiring an extracted evidence quote before scoring, and calibrating the judge against human-graded examples.</p>
</details>

---

### Sources & References
- **[1]** OpenTelemetry Specification, *Semantic Conventions for Generative AI Systems (`gen_ai.*` and Agent Spans)* — [opentelemetry.io/docs/specs/semconv/gen-ai](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- **[2]** Hamel Husain & Eugene Yan, *Your AI Product Needs Evals (Applied LLMs)* — [applied-llms.org](https://applied-llms.org/)
- **[3]** Shunyu Yao, Sierra Engineering et al., *tau-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains* (2024) — [arxiv.org/abs/2406.12045](https://arxiv.org/abs/2406.12045)
