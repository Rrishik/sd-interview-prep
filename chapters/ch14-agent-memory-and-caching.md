# Chapter 14: Agent Memory (Working, Episodic, Semantic) & KV Prompt Caching

*Part IV · Autonomous Agent Systems · 8 min core · 22 min with deep dives*

By itself, an LLM has the memory of a goldfish: the microsecond an HTTP response finishes streaming, the model forgets you ever existed.

And you cannot fix that by pasting every past conversation into a 128,000-token prompt. If you try, **"Lost in the Middle" attention decay** drops recall by `20%–40%` on facts buried in the middle of the transcript [3], while recomputing attention over 80,000 tokens ruins Time-To-First-Token (`TTFT`).

Let us look at the lower half of the diagram in Chapter 13 to see how production agents combine a **Multi-Tier Memory Hierarchy** with **GPU KV Prefix Caching** [1, 2, 4].

---

### 1) The Agent Memory Hierarchy (`CoALA`)

Production language agents split memory across distinct cognitive tiers, each backed by the storage engine that fits its access pattern [1, 2]:

| Memory Tier | Cognitive Role | What It Stores | Backing Store | Compaction & Retrieval Rule |
| :--- | :--- | :--- | :--- | :--- |
| **1. Working Memory** *(Intra-Session)* | Whiteboard scratchpad | Current goal, active DAG state, last `K=6` raw turns, and a rolling summary of older turns. | In-memory + **Redis** (`24h` TTL) + Postgres checkpoint | Append-only during turns; summarize older turns only when tokens cross a **`75%` watermark**. |
| **2. Episodic Memory** *(Experiential)* | Incident postmortem log | Timestamped summaries of **past trajectories** (*"Symptom X -> Tool A failed -> Tool B fixed it"*). | **Vector DB (`pgvector` / `Milvus`)** + JSONB metadata | Ranked by **hybrid recency score**: `0.65*CosineSim + 0.25*exp(-λ*hours) + 0.10*is_success` [1]. |
| **3. Semantic Memory** *(Long-Term Facts)* | Architecture wiki | Distilled user preferences & entity facts (`os="macOS 15"`, `jdk="Java 21"`). | **`pgvector` + Relational `user_facts` table** | Updated via **conflict-resolving upsert** (`is_active = false` on superseded facts). |

:::deepdive Context Engineering Matrix & Procedural Memory (The 4th Tier) | +5 min

A core interview skill is deciding **where each piece of information belongs**—plus completing the `CoALA` taxonomy with **Procedural Memory** [2]:

| Mechanism | What Belongs Here | Volatility | Why Not Put Everything in the Prompt? |
| :--- | :--- | :--- | :--- |
| **1. System Instructions** | Core persona, hard safety invariants, output formatting contract. | Static (Git-versioned) | Must stay short & static at token `0` to preserve `100%` GPU KV cache hits. |
| **2. Procedural Memory** *(4th CoALA Tier)* | Reusable domain playbooks, `SKILL.md` workflows, and verified tool-use exemplars (*how to do X*). | Slow-changing (versioned skills) | Load **progressively on demand** (list 1-line skill descriptions first; expand full playbook only when triggered) to prevent context bloat. |
| **3. RAG (Corpus Knowledge)** | Shared product docs, policies, runbooks, codebase indexes. | Minutes–days (CDC indexed) | Too large (`GBs–TBs`) for context; requires ACL-filtered hybrid retrieval per query. |
| **4. Persistent User Memory** | User/project facts (**Semantic**) + past session lessons (**Episodic**). | Cross-session (months) | Must survive session restarts and supersede stale preferences cleanly. |
| **5. Live Tool Call** | Current account balance, live pod health, today's inventory count. | Sub-second (real-time) | **Never store volatile transactional state in RAG or Memory**—always fetch live from the source of truth! |

:::

---

### 2) Async Consolidation, Conflict Upserts & Artifact Offloading

How do you keep memory clean across 30-turn debugging sessions and multi-month user histories?
1. **Post-Session Consolidation Worker:** When a session ends, a Kafka worker distills the trace into (a) one 3-sentence **Episode vector** and (b) structured `(user_id, attribute, value)` **Semantic facts**.
2. **Superseding Contradictory Facts:** If Alice said *"We use Java 17"* in January and *"We migrated to Java 21"* in November, appending both chunks confuses the retriever. Instead, run an atomic transaction that marks the `Java 17` row `is_active = false, superseded_by = new_id` and filters all semantic reads with `WHERE user_id = :uid AND is_active = true`.
3. **Artifact Offloading (`>1,000 tokens`):** If `get_build_logs()` returns `20,000 tokens`, never dump the raw blob into Working Memory. Save it to object storage (`artifact://run_99/step_4.log`), inject a `200-token` summary + error excerpt into the prompt, and give the agent a `read_artifact_range(id, start_line, end_line)` tool.

:::deepdive Design Drill: Six-Month Memory for a Personal Coding Assistant | +5 min

Suppose an interviewer asks: *"Design a 6-month memory system for an IDE coding agent used daily across 5 repositories."*

1. **Scope Isolation (`(user_id, repo_id)`):** Partition memories into **Global User Preferences** (*"prefers concise comments, pytest fixtures over unittest"*) vs. **Repo-Scoped Facts** (*"repo A uses pnpm + Vitest; integration tests need Docker"*), so rules from Repo A never pollute Repo B.
2. **Token Budget Allocation (`24,000` Active Context Ceiling):**
   - `3,000` tokens: Static System Prompt + Tool Schemas (**KV-cached**) [4, 5].
   - `1,500` tokens: Top-5 `is_active` Semantic Repo/User facts + Top-2 matching Episodic debugging postmortems [1, 2].
   - `7,500` tokens: On-demand AST/code chunks + triggered **Procedural `SKILL.md`** [2].
   - `12,000` tokens: Append-only Working Memory (compacted at `75%` fullness into a structured state checkpoint).
3. **Security & Memory Poisoning Defense:** Scrub `.env` secrets/tokens before consolidation, and **never auto-promote untrusted external text** (e.g., an instruction hidden inside a third-party GitHub Issue) into persistent Semantic or Procedural Memory without explicit user confirmation—blocking persistent "sleeper" prompt injections [6]!

:::

---

### 3) KV Prompt Caching: Why Static Prefixes Must Come First

During prefill, a causal Transformer computes **Key (`K`)** and **Value (`V`)** tensors where token `i` attends only to earlier tokens `1..i`. If the first `P` tokens of Turn 2 are **byte-for-byte identical** to Turn 1, the GPU reuses those `P` cached KV blocks directly from HBM memory—cutting TTFT by `75%+` and cached token cost by up to `90%` [4]:

1. **Pin Static Layers at the Top:** Order every prompt strictly as: `[1. Static System Prompt] -> [2. Canonically Sorted Tool Schemas] -> [3. Session Memory] -> [4. Append-Only Turn History] -> [5. Latest Observation & Timestamp]`.
2. **Three KV Cache Killers to Avoid:**
   - Putting `current_timestamp` or `request_id` at the top of the System Prompt (invalidates 100% of the prefix after token #5!).
   - Serializing tool schemas from an unsorted `HashMap`/`Set` (random key order busts the prefix hash).
   - Summarizing or rewriting old turns on *every* step instead of waiting for the `75%` token watermark.

:::deepdive Editable Core Memory Blocks, Sleep-Time Compute & Hybrid 3-Store Fusion | +4 min

1. **Typed Core Memory Blocks (`MemGPT` / `Letta`) [7, 8]:**
   - Instead of stuffing unstructured notes into the system prompt, partition pinned in-context memory into discrete, character-capped **Memory Blocks** (`human`, `persona`, `repo_conventions`, `current_task`) mutated through explicit tools (`block_append`, `block_replace`, `block_summarize`) [7, 8]. Enforcing a hard character cap per block (`e.g., 2,000 chars`) prevents silent context bloat while keeping block diffs auditable in versioned storage.
2. **Sleep-Time Compute (Off-Critical-Path Consolidation) [8]:**
   - Running memory pruning, deduplication, and cross-session synthesis *synchronously* during a live chat turn inflates `p99` user latency. **Sleep-Time Compute** delegates memory maintenance to a background agent that runs asynchronously during idle windows between turns or sessions [8]:
     - **`0 ms` user-facing latency penalty** on the primary request path.
     - **Asymmetric model pairing:** A fast model serves live responses while a slower, stronger reasoning model audits raw transcripts offline, resolves contradicted facts, and precomputes `learned_context` blocks for the next session [8].
3. **Hybrid 3-Store Memory Architecture (`Mem0`: Vector + Graph + KV) [9, 10]:**
   - Single-store memory breaks on either exact lookups or multi-hop relationships. Production memory layers write in parallel to **KV / Relational** (`O(1)` exact user settings), **Vector (`HNSW`)** (semantic episode similarity), and a **Knowledge Graph** (entity-relation triples like `Alice -> owns -> BillingAPI -> uses -> Kafka`), fusing candidates via weighted `α·Relevance + β·Importance + γ·Recency` scoring [9, 10].

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **Working Memory** is the sticky notes on your desk today; **Episodic Memory** is your team's postmortem archive; **Semantic Memory** is your living runbook wiki; **Procedural Memory** is muscle memory for running an incident playbook. **KV Prefix Caching** is photocopying the first 9 pages of a 10-page contract so you only hand-write Page 10.
- **Where the analogy breaks:** On paper, fixing a typo on Page 1 only reprints Page 1. In a causal Transformer, Pages 2–10 mathematically attend to Page 1—so **changing one byte on Page 1 forces the GPU to recompute Pages 2–10 from scratch**.
- **Real production system:** **Anthropic & OpenAI Prompt Caching** cache hashed 128-token KV prefix blocks in distributed GPU memory across multi-turn agent loops [4].

---

### Quick Self-Check

<details>
<summary><strong>Q1: How do Working, Episodic, Semantic, and Procedural Memory differ in what they store?</strong></summary>
<p><strong>Answer:</strong> <strong>Working Memory</strong> holds the active session's scratchpad and recent turns. <strong>Episodic Memory</strong> stores timestamped summaries of past session trajectories. <strong>Semantic Memory</strong> stores versioned user/domain facts via conflict-resolving upserts. <strong>Procedural Memory</strong> stores reusable workflows, skills, and how-to playbooks loaded on demand.</p>
</details>

<details>
<summary><strong>Q2: Why does putting <code>Current Time: 2026-11-04T21:00:00Z</code> on Line 1 of the system prompt ruin agent latency and cost?</strong></summary>
<p><strong>Answer:</strong> Because causal self-attention computes each token's KV state from all preceding tokens. Mutating Line 1 invalidates the entire GPU KV prefix cache on every turn, forcing full prefill recomputation of all system instructions and tool schemas.</p>
</details>

<details>
<summary><strong>Q3: In January a user tells the agent "My service runs on Java 17," and in November says "We upgraded to Java 21." How does Semantic Memory prevent retrieving both contradictory facts?</strong></summary>
<p><strong>Answer:</strong> The consolidation worker keys facts by <code>(user_id, attribute)</code>, marks the older <code>Java 17</code> record <code>is_active = false</code> in an atomic upsert, and pre-filters all semantic queries with <code>WHERE is_active = true</code>.</p>
</details>

<details>
<summary><strong>Q4: Why must an agent never allow untrusted external tool outputs (like a public GitHub Issue body) to write directly into persistent Semantic or Procedural Memory?</strong></summary>
<p><strong>Answer:</strong> Because of <strong>Memory Poisoning (Persistent Indirect Prompt Injection)</strong>: a malicious instruction saved into long-term memory would survive across future sessions and hijack unrelated tasks.</p>
</details>

---

### Sources & References
- **[1]** Joon Sung Park et al., *Generative Agents: Interactive Simulacra of Human Behavior* (UIST 2023) — [arxiv.org/abs/2304.03442](https://arxiv.org/abs/2304.03442)
- **[2]** Theodore Sumers et al., *Cognitive Architectures for Language Agents (CoALA)* (TMLR 2024) — [arxiv.org/abs/2309.02427](https://arxiv.org/abs/2309.02427)
- **[3]** Nelson F. Liu et al., *Lost in the Middle: How Language Models Use Long Contexts* (TACL 2024) — [arxiv.org/abs/2307.03172](https://arxiv.org/abs/2307.03172)
- **[4]** Anthropic Documentation, *Prompt Caching: KV-Cache Prefix Reuse for Multi-Turn Agents* — [platform.claude.com/docs/en/build-with-claude/prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- **[5]** Woosuk Kwon et al., *Efficient Memory Management for Large Language Model Serving with PagedAttention (vLLM)* (SOSP 2023) — [arxiv.org/abs/2309.06180](https://arxiv.org/abs/2309.06180)
- **[6]** OWASP GenAI Security Project, *OWASP Top 10 for LLM & Agentic Applications (Memory Poisoning & Indirect Injection)* — [genai.owasp.org/llm-top-10](https://genai.owasp.org/llm-top-10/)
- **[7]** Charles Packer et al., *MemGPT: Towards LLMs as Operating Systems* (2023) — [arxiv.org/abs/2310.08560](https://arxiv.org/abs/2310.08560)
- **[8]** Kevin Lin, Charles Packer et al. (Letta / UC Berkeley), *Sleep-time Compute: Beyond Inference Scaling at Test-time* (2025) — [arxiv.org/abs/2504.13171](https://arxiv.org/abs/2504.13171)
- **[9]** Prateek Chhikara et al., *Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory* (2025) — [arxiv.org/abs/2504.19413](https://arxiv.org/abs/2504.19413)
- **[10]** Rohit Ghumare et al., *AI Engineering from Scratch — Phase 14: Memory Blocks, Sleep-Time Compute & Hybrid Memory* — [aiengineeringfromscratch.com/learn/agent-engineering/the-agent-loop](https://aiengineeringfromscratch.com/learn/agent-engineering/the-agent-loop)
