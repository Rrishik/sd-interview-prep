# Chapter 17: Agent Observability (OpenTelemetry), Deterministic Replay & Canary Rollouts

*Part III · AI & LLM Engineering Systems · 7 min core · 16 min with deep dives*

When a REST microservice fails, it throws an `HTTP 500` and a stack trace.

When a **multi-step AI agent** fails, the HTTP status is **`200 OK`**! On Step 3 of a 6-step run, a two-word prompt tweak caused the planner to pass `include_archived=false`, which returned `0` rows, which convinced the synthesizer to give the user a plausible-sounding wrong answer.

Let us look at the bottom middle of the diagram in Chapter 15 to see how production teams trace, unit-test, and safely roll out non-deterministic agents [1, 2, 3].

---

### 1) Distributed Tracing with OpenTelemetry (`gen_ai.*` Spans)

A single agent run is a **tree of spans** across memory, LLM calls, and parallel tool waves. Using OpenTelemetry (`OTel`) `gen_ai.*` semantic conventions, emit four span levels [1]:
- **Root Span (`agent.run`):** Captures `trace_id`, `prompt_sha`, `graph_version`, `total_cost_usd`, and `termination_reason` (`COMPLETED` vs. `MAX_STEPS`).
- **Memory Span (`memory.retrieve`):** Captures `db.system="pgvector"`, `top_k`, and filter latency.
- **LLM Span (`gen_ai.chat`):** Captures `model`, `input_tokens`, **`cached_input_tokens`** (to catch KV-cache regressions instantly!), `output_tokens`, and `ttft_ms`.
- **Tool Span (`mcp.tool.execute`):** Captures `tool.name`, `idempotency_key`, `is_error`, and `retry_count`.
- **Privacy Rule:** Scrub PII in the OTel Collector before spans hit Jaeger/Honeycomb/Phoenix; keep raw encrypted payloads in an access-controlled audit store with a 30-day TTL.

:::deepdive The Complete Production Agent Metric Taxonomy | +5 min

Define **task success** before picking metrics, then monitor four orthogonal metric buckets so optimizing one cannot silently break another [2, 3]:

| Metric Bucket | Key Production Metrics | Why Single Metrics Mislead Without It |
| :--- | :--- | :--- |
| **1. Outcome Quality** | **`task_success_rate`** (end-state verified), **`citation_precision`** (`supported_claims / cited_claims`). | High user chat engagement often means the user is frustrated and arguing with a failing agent! |
| **2. Trajectory & Tool Health** | **`tool_selection_accuracy`**, **`argument_schema_pass_rate`**, **`steps_per_task`**, **`loop_rate`** (`%` runs hitting duplicate calls or `max_steps`). | An agent can achieve `85%` task success by brute-forcing `9` sloppy tool retries per run. |
| **3. Economics & Latency** | **`cost_per_successful_task`** (`total_spend / successful_runs`), **`p50 / p95 TTFT`**, **`end_to_end_duration_ms`**. | *Cost per token* looks cheap on a smaller model until a `2×` drop in success rate makes **`cost_per_successful_task` higher**! |
| **4. Safety & Escalation** | **`policy_block_rate`**, **`human_escalation_rate`**, **`user_undo_or_revert_rate`**. | Catching silent regressions where an overly cautious prompt escalates `60%` of tickets to humans. |

:::

---

### 2) Testing Non-Deterministic Agents: Dependency Injection & Replay Pyramid

How do you run fast, deterministic tests on every Pull Request when live LLMs are slow, costly, and non-deterministic? Combine **Dependency Injection (`LLMClient`, `ToolExecutor` interfaces)** with a 3-tier pyramid [2, 3]:

| Test Tier | What It Runs | Speed & Cost | What It Verifies |
| :--- | :--- | :--- | :--- |
| **1. Cassette Replay (`VCR` Unit Tests)** | Injects a fake `LLMClient` & `ToolExecutor` that replay recorded JSON fixtures in memory. | **`< 2s`, `$0`** (Every commit) | `100%` of deterministic orchestration logic: DAG wave scheduling, retries, compaction, and policy gates. |
| **2. Sandboxed Golden Suite (`temp=0`)** | Live LLM against stateful in-memory mock tools (e.g., seeded SQLite DB) across `200` scenarios. | **`~3 min`** (Pre-merge CI) | Grades **Final Sandbox State Match** + **DAG-Valid Tool Call F1** (never brittle ordered string matching!). |
| **3. Binary Rubric LLM-as-Judge** | Evaluates responses with explicit **`PASS/FAIL` binary checklists** + mandatory evidence quotes. | Async CI & `5%` Kafka prod sample | Avoids noisy `1–10` rating variance; catches faithfulness and tone regressions [2]. |

---

### 3) Versioning Artifacts & 4-Stage Canary Rollouts

Treat prompts, tool JSON schemas, and agent graphs as immutable Git-versioned artifacts (`prompt_sha`). Roll out changes in four stages:
1. **Offline CI Gate:** Must pass `>= 90%` precision on the Golden Trajectory Suite with zero safety regressions.
2. **Shadow (Dark Traffic) Mode (`1%` Live Fork):** Run the new version asynchronously on `1%` of live traffic with all write tools stubbed in **dry-run/no-op mode**, comparing proposed actions against production.
3. **Progressive Canary (`1% -> 10% -> 50% -> 100%`):** Monitor OTel `tool_error_rate`, `max_steps_exceeded_rate`, `p95_ttft_ms`, user undo/thumbs-down rate, and async `5%` Kafka judge scores.
4. **Instant Feature-Flag Rollback:** Automatically revert the routing pointer to the prior `prompt_sha` in `< 5s` if any SLO trips.

:::deepdive Design Drill: End-to-End Evaluation Plan Comparing Agent v1 vs. Agent v2 | +4 min

When asked *"Agent v2 switches to a new planner prompt and smaller worker model—how do you prove v2 is safe to ship?"*, walk through four gates:

1. **Stratified Golden Benchmark (`N = 300` cases):** Slice cases across easy happy-path (`40%`), multi-hop edge cases (`30%`), tool-outage recovery (`15%`), and adversarial prompt-injection traps (`15%`). Run **3 trials per case** (`pass^3` consistency metric from `tau-bench` [3]) because an agent with `80%` single-run accuracy succeeds 3 times in a row only `0.8^3 = 51.2%` of the time!
2. **Paired Diff Analysis:** Inspect every regression where `v1 = PASS` and `v2 = FAIL` before looking at aggregate averages—averages hide catastrophic regressions on rare, high-value intents.
3. **Shadow Dry-Run Parity (`24 hours`):** Verify `v2`'s proposed write tool calls match `v1` within acceptable divergence and check `cached_input_tokens` ratio hasn't regressed.
4. **Online A/B Experiment:** Split by `user_id` (not per-request, so multi-turn sessions stay consistent), gating promotion on non-inferior `task_success_rate`, `0` critical safety violations, and improved `cost_per_successful_task`.

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** Rolling out an agent update is like testing **aircraft autopilot firmware**: first test the wiring with pre-recorded signals (`Cassette Replay`), then fly 200 storms in a simulator (`Sandboxed Golden Evals`), then run in passive shadow mode beside the human pilot (`Shadow Traffic`), and finally enable on 1% of flights (`Canary`).
- **Where the analogy breaks:** Flight simulators obey fixed physics; real users invent new edge cases daily—so every production failure caught in the wild must be anonymized and added back into your **Golden Eval Dataset** [2].
- **Real production system:** **Sierra, Intercom Fin, and GitHub Copilot** gate every prompt or tool-schema change on replay harnesses, `tau-bench`-style state assertions, and progressive canary telemetry [2, 3].

---

### Quick Self-Check

<details>
<summary><strong>Q1: How does Dependency Injection let you test an orchestrator's DAG routing, retry backoff, and guardrails in under 2 seconds at $0 cost?</strong></summary>
<p><strong>Answer:</strong> By injecting <code>LLMClient</code> and <code>ToolExecutor</code> interfaces via the constructor, unit tests supply a <strong>Deterministic Cassette Replay harness</strong> that returns pre-recorded responses in memory without network or GPU calls.</p>
</details>

<details>
<summary><strong>Q2: Why is asserting an exact ordered list of tool calls brittle for multi-step agents, and what should you assert instead?</strong></summary>
<p><strong>Answer:</strong> Independent read tools (<code>get_user</code>, <code>get_orders</code>) can validly run in any order. Assert (1) <strong>Final Sandbox State Match</strong>, (2) <strong>Unordered/DAG-Valid Tool Call F1</strong>, and (3) <strong>Zero Forbidden Write Calls</strong>.</p>
</details>

<details>
<summary><strong>Q3: In Shadow (Dark Traffic) mode on 1% of live requests, how do you prevent the candidate agent from mutating production databases?</strong></summary>
<p><strong>Answer:</strong> Inject a shadow <code>ToolExecutor</code> that executes read-only tools normally (or reads cached observations) while intercepting all state-mutating write tools in <strong>dry-run mode</strong>, logging the proposed payload for comparison.</p>
</details>

<details>
<summary><strong>Q4: Why is <code>cost_per_successful_task</code> a better North Star economic metric than <code>cost_per_1k_tokens</code>?</strong></summary>
<p><strong>Answer:</strong> A cheaper model that loops twice as long or fails half the time forces retries and human escalations, raising total spend per resolved user goal even though its per-token price is lower.</p>
</details>

---

### Sources & References
- **[1]** OpenTelemetry Specification, *Semantic Conventions for Generative AI Systems (`gen_ai.*`)* — [opentelemetry.io/docs/specs/semconv/gen-ai](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- **[2]** Hamel Husain & Eugene Yan, *Your AI Product Needs Evals (Applied LLMs)* — [applied-llms.org](https://applied-llms.org/)
- **[3]** Shunyu Yao et al., *tau-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains* (2024) — [arxiv.org/abs/2406.12045](https://arxiv.org/abs/2406.12045)
