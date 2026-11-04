# Chapter 14: Agent Memory Architecture (Working, Episodic, Semantic) & KV Prompt Caching

*Part IV · Autonomous Agent Systems · 10 min read*

By itself, an LLM has the memory of a goldfish: the microsecond an HTTP response finishes streaming, the model forgets you ever existed.

To build an autonomous agent that *reasons over past interactions, remembers user preferences, and maintains state across multi-day workflows*, you must engineer an external **Memory Architecture** around the model [1, 2].

And you cannot simply paste every past conversation into a 128,000-token prompt. If you try, you hit two walls:
1. **"Lost in the Middle" Attention Decay:** LLMs recall facts at the very top and very bottom of a prompt well, but accuracy drops by `20%–40%` when critical details are buried in the middle of a noisy 80,000-token transcript [3].
2. **Prefill Latency & Cost Explosion:** Re-computing attention over 80,000 tokens on every turn ruins Time-To-First-Token (`TTFT`) unless your prompt layout preserves the GPU's **KV Prefix Cache** [4].

Let us examine the **Three-Tier Agent Memory Hierarchy** and **KV Prompt Caching** shown in the lower half of the diagram in Chapter 13 [1, 2, 4].

---

### 1) The Three-Tier Agent Memory Hierarchy (Working, Episodic & Semantic)

Cognitive architectures for language agents (`CoALA`) divide memory into three distinct tiers, each backed by a different storage engine and retrieval strategy [1, 2]:

| Memory Tier | Human Cognitive Analogy | What It Stores in an Agent | Backing Storage Engine | Retrieval & Compaction Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **1. Working Memory** *(Short-Term / Intra-Session)* | Your mental scratchpad while solving a problem on a whiteboard. | Active task goal, current DAG plan, recent `K` raw turns, tool scratchpad, and a rolling summary of older turns in the current session. | In-process state + **Redis** (`Hash` / `List` with `24h` TTL) + PostgreSQL checkpoints. | Loaded every turn; compacted via **sliding window + summarization** when tokens cross budget. |
| **2. Episodic Memory** *(Experiential / Past Trajectories)* | Remembering *what happened* last week when a deployment failed and which command fixed it. | Timestamped summaries of **past sessions & tool trajectories** (*"Symptom X -> Tool A failed -> Tool B resolved it"*). | **Vector DB (`pgvector` / `Milvus`)** + JSONB metadata (`user_id`, `timestamp`, `outcome`). | **Dynamic Few-Shot Recall:** Ranked by `w1*CosineSim + w2*TimeDecay + w3*Outcome`. |
| **3. Semantic Memory** *(Long-Term Factual Knowledge)* | Knowing timeless facts (*"Alice's service runs on Java 21 in us-west-2"*). | Structured user preferences, entity facts, and domain knowledge distilled across sessions. | **Hybrid Store:** `pgvector`/`Milvus` + Relational `user_facts` table with versioned upserts. | Hybrid `BM25 + Vector` search; updated via **Conflict-Resolving Upsert** when facts change. |

---

### 2) Episodic Time-Decay & Semantic Conflict Resolution

How do Episodic and Semantic Memory work together across sessions without polluting the prompt with stale or contradictory facts?

1. **Asynchronous Memory Consolidation (Post-Session Worker):**
   When an agent session finishes, the orchestrator publishes the trace to Kafka (`agent.sessions.completed`). A background **Memory Consolidation Worker** extracts two artifacts:
   - **An Episode Summary (written to Episodic Memory):** Compresses a 15-turn debugging trace into a 3-sentence experience vector: *"When resolving code-signing error `CS-881` on macOS Sequoia, `clear_derived_data` failed but `reset_provisioning_keychain` succeeded."*
   - **Atomic Entity Facts (upserted into Semantic Memory):** Extracts structured triples such as `(user_id="alice", key="os_version", value="macOS 15.2")`.
2. **Time-Decay Scoring for Episodic Recall:**
   If you retrieve past episodes using pure cosine similarity, an outdated incident from 11 months ago can outrank an identical incident from 2 hours ago. Production retrievers combine semantic similarity with an exponential **recency decay** [1]:
   `score(episode) = 0.65 * cosine_sim(query, ep_vec) + 0.25 * exp(-0.01 * hours_elapsed) + 0.10 * is_success`
3. **Resolving Contradictions in Semantic Memory (`ADD / UPDATE / INVALIDATE`):**
   Suppose Alice told the agent *"My team uses Java 17"* in January, and in November says *"We migrated to Java 21."* If you blindly append vector chunks to `pgvector`, your retriever will fetch **both** `"uses Java 17"` and `"uses Java 21"`!
   - **The Production Fix:** Before inserting a new semantic fact, the consolidation worker queries existing active facts for `(user_id, key)`. If a conflict exists, it executes an atomic transaction that marks the old row `is_active = false, superseded_by = new_fact_id` and inserts the new row with `is_active = true`. Retrieval queries always include the pre-filter `WHERE user_id = :uid AND is_active = true`.

---

### 3) Context Compaction: Surviving 30-Turn Tool Trajectories

During a long-running workflow, a single tool call like `get_build_logs()` might return `20,000 tokens` of raw text. To keep Working Memory lean and prevent attention degradation, apply three compaction rules:

- **Artifact Offloading (Pointer Substitution):** When any tool output exceeds `1,000 tokens`, the harness saves the full payload to object/blob storage (`artifact://run_99/step_4.log`) and injects only a `200-token` schema summary + error excerpt into Working Memory, alongside a `read_artifact_range(id, start_line, end_line)` tool.
- **Sub-Task Pruning:** Once a sub-goal in the plan DAG transitions to `DONE`, collapse its intermediate `Thought / Action / Observation` turns into a single structured result node.
- **High-Watermark Rolling Summarization:** Keep the `System Prompt` and `Task Goal` pinned at the top, keep the most recent `K = 6` turns verbatim at the bottom, and summarize older turns only when total working memory crosses a **`75%` token watermark**.

---

### 4) LLM Prompt Caching (KV-Cache Prefix Optimization)

Why did we say *"summarize only at a 75% watermark, NOT on every single turn"*? Because of how **GPU KV Prompt Caching** works under the hood [4].

During the **Prefill phase**, a Transformer computes **Key (`K`)** and **Value (`V`)** attention tensors for every input token. Because self-attention is **causal** (token `i` only attends to preceding tokens `1..i`, never to future tokens `i+1..L`), the `K` and `V` tensors for the first `P` tokens are **100% identical** across requests if tokens `1..P` are byte-for-byte unchanged.

| Prompt Ordering Layer | Stability | Where It Must Sit in the Prompt | KV Cache Behavior |
| :--- | :--- | :--- | :--- |
| **1. Static System Instructions** (`2,500 tokens`) | Immutable across all users | **Very top (Prefix Position 1)** | **100% Cache Hit** across every request. |
| **2. Tool JSON Schemas** (`5,000 tokens`, **canonically sorted!**) | Immutable per agent version | **Prefix Position 2** | **100% Cache Hit** (unless you randomize JSON key order!). |
| **3. User Memory & Few-Shot Examples** (`1,000 tokens`) | Fixed for the entire session | **Prefix Position 3** | **Cache Hit** on Turns `2..N` of the session. |
| **4. Append-Only Turn Trajectory** (`Turns 1 .. N-1`) | Grows by appending only | **Middle (Prefix Position 4)** | Incremental **Cache Hit** on all prior turns! |
| **5. Latest Tool Observation + Current Timestamp** | Changes every turn | **Very bottom (Tail Position 5)** | Only these final `~300` new tokens pay full GPU prefill compute! |

**Three Mistakes That Destroy KV Prompt Cache Hit Rates in Production:**
1. **Putting `current_timestamp` or `request_id` at the top of the System Prompt:** Mutating token `#6` invalidates the entire `8,500-token` prefix after it (`0%` cache hit rate!). Always move volatile metadata to the final tail message.
2. **Iterating over an unsorted `HashMap` / `Set` when serializing Tool Schemas:** If Server A emits `[Tool_A, Tool_B]` and Server B emits `[Tool_B, Tool_A]`, the prefix hash misses. Always sort tool names and JSON keys alphabetically.
3. **Mutating or summarizing old turns on every step:** Rewriting Turn 1 on every step busts the KV cache from Turn 1 onward. Keep history strictly **append-only** until you hit your compaction watermark.

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **Working Memory** is the sticky notes on your desk for today's task; **Episodic Memory** is your team's incident postmortem archive; **Semantic Memory** is your up-to-date architecture wiki. **KV Prompt Caching** is like using a rubber stamp for the first 9 pages of a 10-page legal form so you only hand-write Page 10.
- **Where the analogy breaks:** On a paper form, fixing a typo on Page 1 only requires reprinting Page 1. In a causal Transformer, every token on Pages 2–10 mathematically attends to Page 1's KV vectors—so changing **one character on Page 1 forces the GPU to recompute Pages 2 through 10 from scratch**.
- **Real production system:** **Anthropic Prompt Caching** and **OpenAI Prefix Caching** store hashed 128-token KV blocks in distributed GPU memory, cutting multi-turn agent TTFT by `75%–85%` and input token cost by up to `90%` [4].

---

### Quick Self-Check

<details>
<summary><strong>Q1: How do Working Memory, Episodic Memory, and Semantic Memory differ in what they store and how they are backed?</strong></summary>
<p><strong>Answer:</strong> <strong>Working Memory</strong> stores the active session's immediate state, scratchpad, and recent turns (in-memory/Redis with TTL). <strong>Episodic Memory</strong> stores timestamped summaries of past interaction trajectories and tool outcomes in a vector store (<code>pgvector</code>/<code>Milvus</code>) for experience replay. <strong>Semantic Memory</strong> stores distilled, long-term facts and user preferences updated via conflict-resolving upserts.</p>
</details>

<details>
<summary><strong>Q2: Why does injecting <code>Current Time: 2026-11-04T19:45:00Z</code> in the first line of your system prompt ruin agent latency and token cost?</strong></summary>
<p><strong>Answer:</strong> Because Transformer self-attention is causal: every token attends to all earlier tokens. Changing a timestamp at the top of the prompt alters the attention state for every token that follows, invalidating the GPU's <strong>KV prefix cache</strong> and forcing a full prefill recomputation of all system instructions and tool definitions on every turn.</p>
</details>

<details>
<summary><strong>Q3: In January a user tells your agent "My service uses Java 17," and in November they say "We upgraded to Java 21." What breaks if Semantic Memory simply appends vector chunks, and how do you fix it?</strong></summary>
<p><strong>Answer:</strong> Pure append-only vector storage retrieves both <code>"Java 17"</code> and <code>"Java 21"</code> with nearly identical cosine similarity, confusing the generator. Fix it with a <strong>Memory Consolidation upsert</strong> that queries existing facts for <code>(user_id, attribute)</code>, marks the old fact <code>is_active = false</code>, and filters retrieval by <code>WHERE is_active = true</code>.</p>
</details>

<details>
<summary><strong>Q4: An agent has an 8,000-token static prefix (system prompt + sorted tools) and adds 500 tokens per turn for 10 turns. If cached tokens cost 10% of normal input tokens, how much input cost does KV caching save on Turn 10?</strong></summary>
<p><strong>Answer:</strong> Without caching, Turn 10 bills full price for <code>8,000 + (10 × 500) = 13,000 tokens</code>. With append-only KV caching, <code>12,500</code> prior tokens hit the cache (costing the equivalent of <code>1,250</code> tokens) and only the <code>500</code> new tail tokens pay full price—an effective cost of <code>1,750</code> vs <code>13,000 tokens</code> (an <strong>~86.5% reduction</strong>).</p>
</details>

<details>
<summary><strong>Q5: Why should context summarization run only when Working Memory crosses a high-water mark (e.g., 75% of budget) rather than after every single turn?</strong></summary>
<p><strong>Answer:</strong> Summarizing after every turn rewrites the middle of the message history on every step, which invalidates the KV cache for all subsequent turns. Keeping history strictly append-only until the 75% watermark preserves `90%+` KV cache hit rates across the multi-turn loop.</p>
</details>

---

### Sources & References
- **[1]** Joon Sung Park et al., *Generative Agents: Interactive Simulacra of Human Behavior* (Stanford / UIST 2023) — Memory Stream & Recency-Relevance-Importance Scoring
- **[2]** Theodore Sumers et al., *Cognitive Architectures for Language Agents (CoALA)* (TMLR 2024) — Working, Episodic & Semantic Memory
- **[3]** Nelson F. Liu et al., *Lost in the Middle: How Language Models Use Long Contexts* (TACL 2024) — [arxiv.org/abs/2307.03172](https://arxiv.org/abs/2307.03172)
- **[4]** Anthropic & OpenAI Engineering, *Prompt Caching: KV-Cache Prefix Reuse for Multi-Turn Agents* (2024–2025)
