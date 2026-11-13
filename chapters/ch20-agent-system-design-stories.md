# Chapter 20: End-to-End Agent System Design Stories (Coding, MCP Enterprise, Support & Research)

*Part IV · Autonomous Agent Systems · 9 min core · 20 min with deep dives*

In a senior GenAI or Agent System Design interview, the prompt is intentionally ambiguous:
*"Design an autonomous bug-fixing agent for our monorepo"* or *"Design an enterprise assistant connecting to Git, Jira, and Postgres."*

Candidates who jump straight into drawing vector databases or naming SDKs lose structure fast. Strong candidates drive a repeatable **12-Step First-Principles Agent Blueprint**, starting with the simplest viable architecture and adding autonomy only where deterministic code falls short [1, 2, 3].

{{diagram:08-agent-case-studies.excalidraw}}

---

### 1) The 12-Step Agent System Design Blueprint

Keep this mental checklist ready for any `45-minute` agent design interview [1, 2]:

| Phase | Steps to Cover | Key Engineering Decision |
| :--- | :--- | :--- |
| **A. Scope & Justification (`5 min`)** | **1.** Clarify goal, users, success metrics & *prohibited outcomes*.<br>**2.** Pin scale, p95 latency, cost/task & privacy constraints.<br>**3.** Justify **Single Call vs. Workflow vs. Agent** [1]. | Never default to an open-ended agent if a deterministic workflow handles `80%+` of traffic! |
| **B. Intelligence & Context (`10 min`)** | **4.** Tiered model routing & fallback strategy.<br>**5.** Context routing (`Prompt` vs `RAG` vs `4-Tier Memory` vs `Live Tool`) + KV-cache prefix order. | Put static schemas first; pre-filter RAG by ACLs; keep live state behind tools. |
| **C. Tools, Loop & Runtime (`15 min`)** | **6.** Tool / MCP contracts, schemas & `1:1` auth boundaries.<br>**7.** Loop topology (`DAG`, `Evaluator-Optimizer`, `Handoffs`), budgets & HITL.<br>**8.** Durable checkpoints, retries, idempotency & Sagas. | Model runs as checkpointed state machines; bind identity from caller tokens, never LLM args. |
| **D. Safety, Evals & Scale (`10 min`)** | **9.** Threat model (indirect injection, CaMeL, microVM sandbox).<br>**10.** OTel spans, Replay/Golden evals & Canary gates.<br>**11–12.** Queues, TPM budgets, tradeoffs & **simplest V1**. | Gate rollouts on `cost_per_successful_task`, `loop_rate`, and `0%` adversarial leak rate. |

---

### 2) Case Study A: Autonomous Coding & Bug-Investigation Agent

**Prompt:** *Design an agent triggered by a production exception or bug ticket that investigates a large repository and proposes a verified fix.*

1. **Why an Agent Is Justified:** Root-causing an unfamiliar stack trace requires dynamic hypothesis testing (`grep -> read caller -> inspect git blame -> reproduce test`), which cannot be hardcoded as a fixed pipeline—paired with a deterministic **Evaluator-Optimizer** inner loop (`Edit -> Compile -> Test -> Lint`) [1].
2. **Sandbox & Tool Architecture (Top Half of Diagram):**
   - Provision an **ephemeral Firecracker microVM** mounted to a shallow/CoW **Git worktree** at the failing commit SHA—containing **zero production DB credentials** and a default-deny egress firewall (allowing only the internal package mirror).
   - Provide **coarse, token-efficient tools**: `symbol_usages(lsp)`, `ripgrep_search`, `git_log_range`, `read_file_lines`, `apply_unified_diff`, and `run_targeted_test(selector)`. Offload verbose compiler logs (`>1,000` tokens) to artifacts, feeding only failing assertion diffs into Working Memory.
3. **Safety & Termination Gates:** Cap the Evaluator-Optimizer repair loop at `max_iterations = 4` and `wall_clock = 8 min`. Block edits to CI/security paths (`.github/`, `CODEOWNERS`). On green tests, push to `bot/fix-<ticket>` and open a **Draft PR** attaching the reproduction test and OTel trace—**never auto-merging to `main`**.

---

### 3) Case Study B: Multi-Server Enterprise MCP Assistant

**Prompt:** *Design an internal assistant that answers questions and executes workflows across Git, Jira/ServiceNow, and Analytics SQL while strictly preserving per-user permissions.*

1. **MCP `1:1` Isolation & OAuth On-Behalf-Of (`OBO`):**
   - The **Enterprise MCP Host** spawns isolated **`1:1` MCP Clients** to the `Git`, `Ticketing`, and `Analytics` MCP Servers over Streamable HTTP [3].
   - **Zero Shared Admin Keys:** For every tool call, the Host exchanges the user's SSO JWT via **OAuth 2.0 On-Behalf-Of (`OBO`)** for a short-lived, audience-scoped token (`aud="mcp://ticketing"`). Even under prompt injection, the Ticketing MCP Server physically cannot read tickets outside that user's Jira RBAC, and the Analytics MCP Server connects via a read-only database role with **Row-Level Security (`RLS`)**.
2. **Orchestration & Consent UX:**
   - Use **Plan-and-Execute** to fan out parallel read-only MCP calls (`git_recent_deploys` + `jira_open_incidents` + ACL-filtered runbook RAG), cutting multi-source latency from `7s` to `~2.2s`.
   - Any mutating tool (`jira_transition_issue`, `git_revert_pr`) pauses the durable run in `WAITING_APPROVAL` and renders a structured **User Consent Diff Card** in the UI before executing with a `SHA-256` idempotency key.

:::deepdive Case Study C: Customer-Support System (Deterministic Workflow vs. Bounded Agent) | +5 min

**Prompt:** *Design a customer-support system handling 500,000 tickets/day across order tracking, cancellations, address changes, and complex damaged-shipment disputes.*

- **Step 1 — Don't Over-Agentify (`80 / 20` Split):**
  - A fast intent classifier (`150 ms`) routes **`~80%` of traffic** (order status, standard within-window returns, FAQ) into **Deterministic Workflows**: fixed code fetches `get_order(session.user_id)`, evaluates exact business rules in Java/Python, and uses a single small-LLM call strictly to phrase a polite response. Cost: `<$0.001`, hallucinated policy risk: **`0%`**.
- **Step 2 — Bounded Exception Agent (`20%` Ambiguous Cases):**
  - Multi-item partial damages, carrier delays + loyalty exceptions route to a **Bounded ReAct/Two-Pass Agent** equipped with read tools (`get_order`, `get_carrier_scan`, `search_return_policy`) and policy-gated write tools (`issue_credit`, `reship_item`).
- **Step 3 — Hard Financial Invariants:**
  - Deterministic policy middleware enforces `credit_amount <= min(order_total, $50)` and `rolling_30d_credits(user_id) <= $100`; anything above transitions the durable run to `WAITING_APPROVAL` in a human supervisor queue with a pre-summarized case brief.

:::

:::deepdive Case Study D: Parallel Deep-Research Agent with Claim-Level Citation Grounding | +6 min

**Prompt:** *Design a research agent that investigates a broad technical or market question across internal documents and live web sources and produces a cited, hallucination-free report.*

1. **Lead Planner -> Parallel Search Workers (`Map-Reduce` Context Isolation):**
   - If one agent runs 15 sequential searches, `60,000` tokens of noisy snippets flood one context window ("Lost in the Middle").
   - Instead, a **Lead Planner** decomposes the prompt into `3–5` orthogonal sub-questions and spawns **parallel Sub-Agents** (`Agents-as-Tools`), each with its own isolated `16K` context window, `max_searches = 3`, and ACL-scoped hybrid retriever.
   - Each worker returns **only compressed, source-tagged evidence cards** (`{claim, quote_span, doc_id, published_at, authority_tier}`)—discarding `90%` of raw HTML/chunk noise before reaching the Synthesizer!
2. **Conflict Resolution & Citation Verification:**
   - When an older 2024 doc contradicts a 2026 spec, instruct the Synthesizer to surface the version/date discrepancy explicitly rather than silently picking one.
   - Run a fast **Post-Generation Citation Verifier** (exact quote-span check + lightweight NLI entailment model) confirming every `[doc_id]` supports its sentence; strip or flag any unsupported sentence before marking the durable run `COMPLETED`.

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** Designing a production agent system is like designing a **modern hospital emergency department**: triage nurses route `80%` of routine cases to standard checklists (**Deterministic Workflows**), complex multi-symptom cases convene specialist consults (**Scoped Multi-Agent / MCP**), pharmacists double-check every high-dose prescription independently (**Deterministic Policy Gate**), and every chart note links to lab evidence (**Grounded Citations & OTel Traces**).
- **Where the analogy breaks:** Hospital clinicians share implicit ethical judgment; LLM components treat adversarial text inside a patient intake form as instructions unless **external privilege boundaries (`OBO` tokens, CaMeL isolation, and sandboxes)** enforce least privilege in code.
- **Real production system:** **GitHub Copilot Coding Agent**, **Anthropic Claude Research**, and **Block / Stripe MCP Assistants** combine microVM sandboxes, parallel sub-agent map-reduce, and OAuth-scoped MCP servers [1, 2, 3].

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why should a Coding Agent run inside an ephemeral microVM worktree and open a Draft PR instead of committing directly with repo admin credentials?</strong></summary>
<p><strong>Answer:</strong> Untrusted code, tests, or issue text in a repo can trigger malicious shell commands or indirect prompt injections. An ephemeral microVM with zero prod secrets, default-deny egress, protected CI paths, and a mandatory human Draft PR gate bounds the blast radius to zero.</p>
</details>

<details>
<summary><strong>Q2: How does OAuth 2.0 On-Behalf-Of (OBO) prevent cross-tenant and confused-deputy data leaks in a multi-server Enterprise MCP Assistant?</strong></summary>
<p><strong>Answer:</strong> Instead of authenticating to Jira or Postgres with a shared superuser service account, the MCP Host exchanges the caller's JWT for short-lived, per-server down-scoped tokens so each downstream system enforces that exact user's native RBAC and Row-Level Security.</p>
</details>

<details>
<summary><strong>Q3: In a 500k-ticket/day Customer Support platform, why is routing 80% of tickets to a Deterministic Workflow superior to sending 100% of tickets through an Autonomous Agent?</strong></summary>
<p><strong>Answer:</strong> Routine intents (order tracking, standard returns) follow fixed rules where deterministic code gives <code>5×</code> lower latency, <code>10×</code> lower token cost, and <code>0%</code> policy hallucination—reserving expensive dynamic agent reasoning strictly for the <code>20%</code> ambiguous exceptions.</p>
</details>

<details>
<summary><strong>Q4: Why do Deep-Research Agents spawn parallel sub-agents with isolated context windows instead of running 15 searches sequentially in a single ReAct loop?</strong></summary>
<p><strong>Answer:</strong> Parallel sub-agents cut wall-clock latency from <code>15</code> serial hops to <code>1</code> parallel wave and prevent raw search snippets from polluting the lead synthesizer's context window—returning only distilled, source-tagged evidence cards.</p>
</details>

---

### Sources & References
- **[1]** Anthropic Engineering, *Building Effective Agents* & *Multi-Agent Research System Architecture* (2024–2025) — [anthropic.com/research/building-effective-agents](https://www.anthropic.com/research/building-effective-agents)
- **[2]** OpenAI, *A Practical Guide to Building Agents* & *Agents SDK Orchestration* (2025–2026) — [developers.openai.com/api/docs/guides/agents/orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration)
- **[3]** Model Context Protocol (MCP) Specification (`2026-07-28`), *Authorization, Trust Boundaries & Architecture* — [modelcontextprotocol.io/specification/2026-07-28/architecture](https://modelcontextprotocol.io/specification/2026-07-28/architecture)
