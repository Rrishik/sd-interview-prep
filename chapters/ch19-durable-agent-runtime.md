# Chapter 19: Durable Agent State Machines, Async Run APIs & Scaling to 1M Runs/Day

*Part IV · Autonomous Agent Systems · 8 min core · 18 min with deep dives*

In a prototype, an agent is a `while` loop inside an `HTTP POST /chat` handler.

In production, that design collapses the first afternoon you get real traffic:
1. A tool call needs **human manager approval**—which takes `4 hours`. You cannot hold an HTTP socket or a worker pod open for 4 hours!
2. Worker Pod #12 gets evicted by Kubernetes on **Step 4 of 6**, losing the first 3 LLM calls and double-charging the customer on retry.
3. A single enterprise tenant kicks off a `50,000-row` batch agent job at 9:00 AM, exhausting your global LLM Tokens-Per-Minute (`TPM`) quota and taking down every interactive user.

The architectural fix is fundamental: **model every agent run as an asynchronous, checkpointed Durable State Machine** decoupled from HTTP connections [1, 2].

{{diagram:07-durable-agent-runtime.excalidraw}}

---

### 1) The Async Agent Run API & Durable State Lifecycle

Instead of blocking inside one synchronous request, expose a **5-endpoint Asynchronous Run Resource** (similar to OpenAI Assistants/Responses background runs, Temporal workflows, and LangGraph Cloud) [1, 2]:

| Endpoint | HTTP Contract | What Happens Under the Hood |
| :--- | :--- | :--- |
| **`POST /agent/runs`** | Accepts `Idempotency-Key` + goal; returns **`202 Accepted`** + `{run_id, status: "QUEUED"}` in `< 25 ms`. | Inserts `agent_runs` row (`QUEUED`) and publishes `run_id` to `Kafka: agent.runs` via transactional outbox. |
| **`GET /agent/runs/{id}`** | Returns current state (`QUEUED`, `RUNNING`, `WAITING_APPROVAL`, `COMPLETED`, `FAILED`, `CANCELLED`). | Fast primary-key read from Postgres / Redis state cache for polling or UI hydration. |
| **`GET /agent/runs/{id}/events`** | Server-Sent Events (`SSE`) accepting **`Last-Event-ID: 42`** header. | Replays any missed events `> 42` from a **Redis Stream (`XREAD`)** before tailing live tokens—surviving mobile Wi-Fi drops seamlessly! |
| **`POST /runs/{id}/approvals`** | Submits `{step_id, decision: "APPROVED" or "REJECTED"}`. | Transitions state `WAITING_APPROVAL -> QUEUED` and re-enqueues `run_id` so *any* stateless worker resumes from the checkpoint! |
| **`POST /runs/{id}/cancel`** | Sets `cancel_requested = true` + publishes cancel signal on Redis Pub/Sub. | Active worker aborts in-flight LLM/MCP calls at the next token/checkpoint and transitions to `CANCELLED`. |

**Zero-Thread Human-in-the-Loop (`WAITING_APPROVAL`):**
When the policy gate intercepts a high-impact write (`refund_order($250)`), the worker persists the proposed tool payload into `agent_steps`, sets `status = WAITING_APPROVAL`, emits an `approval.required` SSE event, **and exits cleanly—holding zero threads, zero RAM, and zero DB locks** whether the human responds in `3 seconds` or `3 days` [1]!

:::deepdive Crash Recovery Mechanics: Step Journals, Leases & Idempotent Replay | +5 min

How do you guarantee a multi-step agent run survives a worker pod crash on Step 4 without re-running Steps 1–3?

1. **Two-Table Durable Checkpoint Schema (PostgreSQL):**
   - `agent_runs(run_id PK, tenant_id, status, current_step, lease_owner, lease_expires_at, lease_epoch, budget_spent_usd)`
   - `agent_steps(run_id, step_idx, phase, input_hash, output_json, prompt_tokens, cost_usd, PRIMARY KEY (run_id, step_idx))`
2. **Lease + Heartbeat Acquisition:**
   - Worker claims a run via atomic `UPDATE agent_runs SET lease_owner = :pod, lease_expires_at = now() + 15s, lease_epoch = lease_epoch + 1` and renews every `5s`.
   - Before every LLM call or tool execution, the worker checks if `(run_id, step_idx)` already has a committed `output_json` in `agent_steps`.
3. **Mid-Step Pod Death Walkthrough:**
   - Suppose Pod A finishes Steps `1..3` (committed to `agent_steps`), calls `create_jira_ticket()` in Step `4` with `idempotency_key = SHA256(run_id + ":4")`, and OOM-crashes *before* writing Step 4's result to Postgres.
   - `15 seconds` later, a lease-reaper re-queues `run_id`. Pod B loads Steps `1..3` directly from `agent_steps` (`0` LLM tokens spent!), re-invokes Step `4` with the **exact same deterministic `idempotency_key`**, receives the cached Jira ticket ID from the deduplication layer, commits Step `4` with `lease_epoch`, and finishes the run!

:::

---

### 2) Scaling to 1,000,000 Agent Runs/Day: Routing, Failover & Token Quotas

Running `1,000,000` multi-step tasks per day introduces failure modes that ordinary CRUD microservices never face—specifically **multi-second GPU latency spikes**, **provider `429` TPM limits**, and **noisy-neighbor token starvation** [2, 3]:

1. **Tiered Model Routing (`70 / 30` Split):**
   - A fast router classifies incoming steps: **`~70%` of steps** (intent routing, query rewriting, schema extraction, simple tool selection) go to a compact, fast model (`~10×` cheaper, `250 ms` TTFT), escalating only **`~30%` of complex reasoning/synthesis steps** to a frontier model.
2. **Health-Scored Provider Failover & Circuit Breakers:**
   - Track rolling `30s` windows of `HTTP 429/5xx` and `p95 TTFT` per `(provider, region, model)`. If `us-east` hits a GPU brownout, trip the circuit breaker to `OPEN` and fail over new turns to `eu-west` or a secondary model family via a normalized OpenAI/Spring-AI schema adapter—while keeping healthy runs **sticky by `run_id`** to preserve GPU KV prefix caches!
3. **Two-Phase Redis Lua Token & Cost Budgets:**
   - Standard request-count rate limiting (`100 req/min`) fails when Request A uses `400` tokens and Request B uses `60,000` tokens.
   - **Pre-Flight Reserve + Post-Turn Reconcile:** Before calling the LLM, atomically reserve `estimated_input_tokens + max_output_tokens` in a per-tenant Redis Lua token bucket. Once the stream finishes, refund `max_output_tokens - actual_output_tokens` and increment `tenant_daily_spend_usd`—halting runaway tenants before they exceed their contract cap.

:::deepdive Envelope Capacity Math & Fair Queuing for 1,000,000 Runs/Day | +5 min

Always ground a `1M runs/day` design prompt with 60-second back-of-the-envelope numbers:

- **Throughput & Concurrency:**
  - Average runs/sec: `1,000,000 / 86,400 ≈ 11.6 runs/s` -> **Peak (`5×` diurnal spike) `≈ 60 runs/s`**.
  - Average `4` LLM turns/run -> **`240` peak LLM QPS** and **`~180` peak tool QPS**.
  - At `4,000` avg tokens/turn (`80%` KV-cached input + `400` output tokens): **`240 × 4,000 ≈ 960,000 tokens/sec` (`~58M TPM` peak)** across your model endpoints!
  - If an active run takes `6 seconds` on average, Little's Law (`L = λ × W`) gives `60 runs/s × 6s = 360` concurrent active runs—easily served by **`8–12` reactive orchestrator pods**!
- **Multi-Tenant Noisy-Neighbor Isolation:**
  - Never put interactive user chat runs and `50,000-item` offline batch runs into the same FIFO queue!
  - Split into **`agent.runs.interactive`** (SLO `< 3s` TTFT, dedicatedTPM reservation) and **`agent.runs.batch`** (spot/provisioned-spillover capacity), using **Weighted Fair Queuing / Deficit Round Robin per `tenant_id`** so Tenant A submitting 10,000 jobs cannot delay Tenant B's single interactive request by more than one scheduling quantum.

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** A synchronous HTTP agent is a phone call where hanging up forces you to start your tax return over from Line 1. A **Durable Checkpointed Agent** is a cloud spreadsheet saved after every cell: if your laptop battery dies or you pause 2 days waiting for your accountant's signature, another browser opens right at Row 42.
- **Where the analogy breaks:** Re-opening a spreadsheet has no external side effects; replaying an agent step that calls Stripe or GitHub *does*—which is why durable state machines **only work when paired with deterministic step idempotency keys** [1].
- **Real production system:** **Temporal**, **LangGraph Platform**, and **OpenAI Background Responses** execute long-horizon agents as event-sourced/checkpointed state machines with resumable SSE streams [1, 2].

---

### Quick Self-Check

<details>
<summary><strong>Q1: How should an agent runtime pause for a human approval that might take 6 hours without holding open a worker thread or database transaction?</strong></summary>
<p><strong>Answer:</strong> Persist the pending tool call and checkpoint state to the database with <code>status = WAITING_APPROVAL</code>, emit an SSE notification, and release the worker completely. When <code>POST /runs/{id}/approvals</code> arrives hours later, re-enqueue <code>run_id</code> so any stateless worker resumes from the saved checkpoint.</p>
</details>

<details>
<summary><strong>Q2: How does <code>GET /agent/runs/{id}/events</code> recover cleanly when a mobile client drops Wi-Fi for 4 seconds mid-stream?</strong></summary>
<p><strong>Answer:</strong> Every SSE frame carries a sequential <code>id: &lt;seq&gt;</code> backed by a short-TTL Redis Stream. On reconnect, the browser automatically sends <code>Last-Event-ID: &lt;seq&gt;</code>, allowing the gateway to replay missed frames from Redis before resuming live tailing.</p>
</details>

<details>
<summary><strong>Q3: Why do LLM gateways use two-phase Token Reservation (<code>reserve</code> before prefill, <code>reconcile</code> after stream) instead of counting tokens only after the response completes?</strong></summary>
<p><strong>Answer:</strong> Because LLM calls take seconds: if you only debit quota after completion, a burst of 500 concurrent requests from one tenant will all pass the pre-check simultaneously and blow past the TPM limit by <code>500×</code> before the first stream finishes.</p>
</details>

<details>
<summary><strong>Q4: Why should a multi-region LLM router prefer sticky routing by <code>run_id</code> during normal operation rather than round-robin across regions on every turn?</strong></summary>
<p><strong>Answer:</strong> Sticky routing keeps consecutive turns of the same multi-step run on the same inference cluster so GPU <strong>KV Prefix Caches</strong> stay warm—saving <code>75%+</code> TTFT and up to <code>90%</code> cached input cost—only failing over across regions when health checks trip.</p>
</details>

---

### Sources & References
- **[1]** Temporal Engineering, *Durable Execution for AI Agents & Human-in-the-Loop Workflows* (2025) — [temporal.io](https://temporal.io/)
- **[2]** Anthropic & OpenAI API Guides, *Streaming Responses, Background Runs & Rate-Limit Token Buckets* (2025–2026)
- **[3]** Martin Kleppmann, *Designing Data-Intensive Applications (DDIA)* — Event-Driven State Machines, Leases & Idempotency
