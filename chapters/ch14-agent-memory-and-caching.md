# Chapter 14: Agent Memory (Working, Episodic, Semantic) & KV Prompt Caching

*Part III · AI & LLM Engineering Systems · 8 min read*

By itself, an LLM has the memory of a goldfish: the microsecond an HTTP response finishes streaming, the model forgets you ever existed.

And you cannot fix that by pasting every past conversation into a 128,000-token prompt. If you try, **"Lost in the Middle" attention decay** drops recall by `20%–40%` on facts buried in the middle of the transcript [3], while recomputing attention over 80,000 tokens ruins Time-To-First-Token (`TTFT`).

Let us look at the lower half of the diagram in Chapter 13 to see how production agents combine a **Three-Tier Memory Hierarchy** with **GPU KV Prefix Caching** [1, 2, 4].

---

### 1) The Three-Tier Agent Memory Hierarchy (`CoALA`)

Production language agents split memory into three tiers, each backed by the storage engine that fits its access pattern [1, 2]:

| Memory Tier | Cognitive Role | What It Stores | Backing Store | Compaction & Retrieval Rule |
| :--- | :--- | :--- | :--- | :--- |
| **1. Working Memory** *(Intra-Session)* | Whiteboard scratchpad | Current goal, active DAG state, last `K=6` raw turns, and a rolling summary of older turns. | In-memory + **Redis** (`24h` TTL) + Postgres checkpoint | Append-only during turns; summarize older turns only when tokens cross a **`75%` watermark**. |
| **2. Episodic Memory** *(Experiential)* | Incident postmortem log | Timestamped summaries of **past trajectories** (*"Symptom X -> Tool A failed -> Tool B fixed it"*). | **Vector DB (`pgvector` / `Milvus`)** + JSONB metadata | Ranked by **hybrid recency score**: `0.65*CosineSim + 0.25*exp(-λ*hours) + 0.10*is_success` [1]. |
| **3. Semantic Memory** *(Long-Term Facts)* | Architecture wiki | Distilled user preferences & entity facts (`os="macOS 15"`, `jdk="Java 21"`). | **`pgvector` + Relational `user_facts` table** | Updated via **conflict-resolving upsert** (`is_active = false` on superseded facts). |

---

### 2) Async Consolidation, Conflict Upserts & Artifact Offloading

How do you keep memory clean across 30-turn debugging sessions and multi-month user histories?
1. **Post-Session Consolidation Worker:** When a session ends, a Kafka worker distills the trace into (a) one 3-sentence **Episode vector** and (b) structured `(user_id, attribute, value)` **Semantic facts**.
2. **Superseding Contradictory Facts:** If Alice said *"We use Java 17"* in January and *"We migrated to Java 21"* in November, appending both chunks confuses the retriever. Instead, run an atomic transaction that marks the `Java 17` row `is_active = false, superseded_by = new_id` and filters all semantic reads with `WHERE user_id = :uid AND is_active = true`.
3. **Artifact Offloading (`>1,000 tokens`):** If `get_build_logs()` returns `20,000 tokens`, never dump the raw blob into Working Memory. Save it to object storage (`artifact://run_99/step_4.log`), inject a `200-token` summary + error excerpt into the prompt, and give the agent a `read_artifact_range(id, start_line, end_line)` tool.

---

### 3) KV Prompt Caching: Why Static Prefixes Must Come First

During prefill, a causal Transformer computes **Key (`K`)** and **Value (`V`)** tensors where token `i` attends only to earlier tokens `1..i`. If the first `P` tokens of Turn 2 are **byte-for-byte identical** to Turn 1, the GPU reuses those `P` cached KV blocks directly from HBM memory—cutting TTFT by `75%+` and cached token cost by up to `90%` [4]:

1. **Pin Static Layers at the Top:** Order every prompt strictly as: `[1. Static System Prompt] -> [2. Canonically Sorted Tool Schemas] -> [3. Session Memory] -> [4. Append-Only Turn History] -> [5. Latest Observation & Timestamp]`.
2. **Three KV Cache Killers to Avoid:**
   - Putting `current_timestamp` or `request_id` at the top of the System Prompt (invalidates 100% of the prefix after token #5!).
   - Serializing tool schemas from an unsorted `HashMap`/`Set` (random key order busts the prefix hash).
   - Summarizing or rewriting old turns on *every* step instead of waiting for the `75%` token watermark.

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **Working Memory** is the sticky notes on your desk today; **Episodic Memory** is your team's postmortem archive; **Semantic Memory** is your living runbook wiki. **KV Prefix Caching** is photocopying the first 9 pages of a 10-page contract so you only hand-write Page 10.
- **Where the analogy breaks:** On paper, fixing a typo on Page 1 only reprints Page 1. In a causal Transformer, Pages 2–10 mathematically attend to Page 1—so **changing one byte on Page 1 forces the GPU to recompute Pages 2–10 from scratch**.
- **Real production system:** **Anthropic & OpenAI Prompt Caching** cache hashed 128-token KV prefix blocks in distributed GPU memory across multi-turn agent loops [4].

---

### Quick Self-Check

<details>
<summary><strong>Q1: How do Working, Episodic, and Semantic Memory differ in what they store?</strong></summary>
<p><strong>Answer:</strong> <strong>Working Memory</strong> holds the active session's scratchpad and recent turns (Redis/in-memory). <strong>Episodic Memory</strong> stores timestamped summaries of past session trajectories and tool outcomes for few-shot experience replay. <strong>Semantic Memory</strong> stores timeless entity facts and preferences maintained via conflict-resolving upserts.</p>
</details>

<details>
<summary><strong>Q2: Why does putting <code>Current Time: 2026-11-04T21:00:00Z</code> on Line 1 of the system prompt ruin agent latency and cost?</strong></summary>
<p><strong>Answer:</strong> Because causal self-attention computes each token's KV state from all preceding tokens. Mutating Line 1 invalidates the entire GPU KV prefix cache on every turn, forcing full prefill recomputation of all system instructions and tool schemas.</p>
</details>

<details>
<summary><strong>Q3: In January a user tells the agent "My service runs on Java 17," and in November says "We upgraded to Java 21." How does Semantic Memory prevent retrieving both contradictory facts?</strong></summary>
<p><strong>Answer:</strong> The consolidation worker keys facts by <code>(user_id, attribute)</code>, marks the older <code>Java 17</code> record <code>is_active = false</code> in an atomic upsert, and pre-filters all semantic queries with <code>WHERE is_active = true</code>.</p>
</details>

---

### Sources & References
- **[1]** Joon Sung Park et al., *Generative Agents: Interactive Simulacra of Human Behavior* (UIST 2023) — Recency, Relevance & Importance Memory Scoring
- **[2]** Theodore Sumers et al., *Cognitive Architectures for Language Agents (CoALA)* (TMLR 2024) — Working, Episodic & Semantic Memory
- **[3]** Nelson F. Liu et al., *Lost in the Middle: How Language Models Use Long Contexts* (TACL 2024) — [arxiv.org/abs/2307.03172](https://arxiv.org/abs/2307.03172)
- **[4]** Anthropic & OpenAI Engineering, *Prompt Caching: KV-Cache Prefix Reuse for Multi-Turn Agents* (2024–2025)
