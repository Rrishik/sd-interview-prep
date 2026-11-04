# Chapter 15: Retrieval Evaluation Math (Recall@K, MRR, nDCG@K) & Vector Indexes (pgvector vs Milvus)

*Part IV · Autonomous Agent Systems · 10 min read*

Suppose your enterprise RAG agent gives a wrong answer to a customer's question. Who is to blame?
- Did your **Retriever** fail to pull the right document chunk out of your 10-million-chunk database?
- Or did your **Retriever** pull the exact right chunk at Rank #1, and your **Generator LLM** misread it or hallucinated anyway?

If you only test the final generated paragraph, you are debugging blindfolded. To isolate the **Retriever** from the **Generator**, production teams measure four mathematical retrieval metrics against a labeled ground-truth dataset—and tune their **Vector & Hybrid Indexes (`pgvector`, `Milvus`, `HNSW`, `BM25 + RRF`)** accordingly [1, 2].

Let us walk through the exact retrieval math and vector index internals shown in the lower left of the diagram below [1, 2, 3].

{{diagram:06-mcp-evals-reactive.excalidraw}}

---

### 1) The Four Core Retrieval Metrics: Recall@K, Precision@K, MRR & nDCG@K

Suppose for a test query `q`, our entire database contains **`4` truly relevant chunks** (`Total_Relevant = 4`). Our retriever returns a ranked list of **`Top K = 5` chunks**, where positions **#1, #3, and #5** are relevant (`[Relevant, Irrelevant, Relevant, Irrelevant, Relevant]`):

| Metric | Exact Formula | Value on `[✅, ❌, ✅, ❌, ✅]` (`4` relevant in DB) | What It Measures (And Where to Use It) |
| :--- | :--- | :--- | :--- |
| **1. `Recall@K`** *(Coverage)* | `Relevant_in_Top_K / Total_Relevant_in_DB` | `3 / 4 = 0.75` (**`75%`**) | **Primary metric for Stage-1 Retrieval (`Top 50`):** Did the needed evidence make it into the candidate net? Ignores rank order. |
| **2. `Precision@K`** *(Signal-to-Noise)* | `Relevant_in_Top_K / K` | `3 / 5 = 0.60` (**`60%`**) | Measures **context noise**: tells you that `40%` of the chunks entering your prompt are irrelevant distractions. |
| **3. `MRR`** *(Mean Reciprocal Rank)* | `Average(1 / rank_of_FIRST_relevant_chunk)` | First ✅ is at rank `1` -> `1 / 1 = 1.00`. *(If `[❌, ❌, ✅]`, `RR = 1/3 = 0.33`)* | Best when the agent only needs **one single hit** (e.g., looking up a specific error code or API spec). |
| **4. `nDCG@K`** *(Normalized Discounted Cumulative Gain)* | `DCG@K / IDCG@K`, where `DCG@K = sum(rel_i / log2(i + 1))` | Rewards placing highly relevant chunks (`rel=3`) at Rank #1 with logarithmic discounting. | **Gold standard for Stage-2 Cross-Encoder Rerankers:** Measures graded relevance (`0..3`) and exact ordering quality. |

**How to Calculate `nDCG@3` in 30 Seconds on a Whiteboard:**
Suppose your reranker returns 3 chunks with graded relevance scores `rel = [1, 3, 0]` (Rank 1 is marginally relevant `1`, Rank 2 is a perfect match `3`, Rank 3 is irrelevant `0`):
1. **Compute actual `DCG@3`:** Divide each score by `log2(rank + 1)`:
   `DCG@3 = 1 / log2(2) + 3 / log2(3) + 0 / log2(4) = 1.0 + (3 / 1.585) + 0 = 2.893`
2. **Compute ideal `IDCG@3`** (sorting the same chunks in best possible order `[3, 1, 0]`):
   `IDCG@3 = 3 / log2(2) + 1 / log2(3) + 0 / log2(4) = 3.0 + (1 / 1.585) + 0 = 3.631`
3. **Divide:** `nDCG@3 = 2.893 / 3.631 = 0.797`.

---

### 2) Why Increasing `K` Can Hurt End-to-End Accuracy (The Precision-Recall Trap)

A common mistake is thinking: *"Since `Recall@50` (`96%`) is higher than `Recall@5` (`78%`), let us skip the reranker and stuff all 50 chunks directly into the LLM prompt!"*

When you do that in production, end-to-end answer accuracy **drops** while latency and cost explode. Why?
- If only 3 chunks in the DB are relevant, passing `K = 50` chunks means **`Precision@50 = 3 / 50 = 6%`**—so **94% of your LLM prompt is distracting noise**!
- That noise triggers **"Lost in the Middle" attention dilution** and increases hallucination rates.
- **The Two-Stage Rule:** Use **Hybrid Retrieval (`BM25 + Vector` merged via Reciprocal Rank Fusion `RRF`)** to maximize **`Recall@50`** in `~25 ms`, then pass those 50 candidates through a **Cross-Encoder Reranker** to maximize **`nDCG@5`** and **`Precision@5`**, sending only the **Top 5** chunks to the LLM.

---

### 3) Vector Index Internals: HNSW vs. IVF & `pgvector` vs. `Milvus`

How does a vector database search 10 million 1,536-dimensional `float32` vectors in `5 milliseconds` instead of doing an `O(N)` brute-force scan that takes `600 milliseconds`?

1. **`HNSW` (Hierarchical Navigable Small World Graph):**
   - Organizes vectors into a multi-layer proximity skip-graph: the top layer has long highway jumps across the vector space, and Layer 0 has dense local neighbor edges (`M` links per node).
   - **Trade-off:** Delivers the highest `Recall@K` (`>98%`) at `< 8 ms` latency, but is **RAM-intensive**. Ten million `1536-dim float32` vectors require `10M × 1536 × 4 bytes = 61.4 GB` of raw vectors plus `~20 GB` of graph edge pointers (**`~80 GB RAM`**). Using `float16` (`halfvec`) or 8-bit Scalar Quantization (`SQ8`) cuts RAM by **`2×` to `4×`** (`20–40 GB`) with `< 1%` recall loss [2, 3].
2. **`IVF-PQ` (Inverted File with Product Quantization):**
   - Clusters vectors into `C` K-means centroids (e.g., `4,096` buckets) and compresses sub-vectors into compact codebooks. Searches only the closest `nprobe` buckets at query time. Uses a fraction of the RAM of HNSW, at the cost of slightly lower recall on boundary queries.

| Decision Criterion | Choose `pgvector` (PostgreSQL) | Choose `Milvus` (Distributed Vector Engine) |
| :--- | :--- | :--- |
| **Vector Volume** | Up to **`10M – 50M` vectors** (with `halfvec` HNSW or DiskANN). | **`100M – 10B+` vectors** with disaggregated S3/MinIO storage and query nodes. |
| **Consistency & Metadata Joins** | **Full ACID transactions!** Vectors live in the exact same row/table as relational user state and ACL metadata (zero sync lag). | Eventual/tunable consistency; requires a Kafka CDC pipeline to keep vectors synced with relational DB rows. |
| **Best Role in Agent Architecture** | **Agent Episodic & Semantic Memory** (where every query filters by `user_id` and `is_active = true`). | **Massive Global Knowledge Corpus RAG** (billions of enterprise docs, codebases, or catalog items). |

---

### 4) Important Focus Areas for Interviews

- **Isolating Failure Modes with the RAG Triad:** If `Recall@5` is `40%`, fix **chunking, embeddings, or hybrid BM25+Vector retrieval**. If `Recall@5` is `95%` but `nDCG@5` is `0.52`, add or tune a **Cross-Encoder Reranker**. If `Recall@5` is `95%` and `nDCG@5` is `0.91` but the final answer is wrong, fix the **Generator prompt or model faithfulness**.
- **Filtered HNSW Iterative Scan (`pgvector 0.8+`):** In older vector indexes, filtering `WHERE user_id = 42` during an HNSW graph traversal could return fewer than `K` results if most graph neighbors belonged to other users. Modern `pgvector` supports **iterative index scans** (`hnsw.iterative_scan = relaxed_order`) plus composite B-Tree/GIN filtering so per-user memory queries always return a full `Top K` set.

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **`Recall@K`** asks: *"When the rescue boat casts a net of size `K`, what fraction of the swimmers in the water did it pull into the boat?"* **`Precision@K`** asks: *"Out of everything inside the net, what fraction was swimmers versus seaweed?"* **`nDCG@K`** asks: *"When you open the net, is the most critical swimmer right on top at Position #1?"*
- **Where the analogy breaks:** Extra seaweed in a rescue boat just adds weight. Extra irrelevant chunks in an LLM prompt actively **corrupt self-attention** and cause the generator to hallucinate or overlook the single relevant paragraph.
- **Real production system:** **Enterprise Security & Malicious Extension Detection Engines** combine lexical `BM25` (for exact manifest permissions, API identifiers, and obfuscated URLs) with dense vector embeddings via **Reciprocal Rank Fusion (`RRF`)**, optimizing Stage 1 for `Recall@50` so zero threats slip through and Stage 2 verification for `>90%` precision before revocation.

---

### Quick Self-Check

<details>
<summary><strong>Q1: For a test query, your database contains 8 relevant chunks. Your retriever returns Top K = 10 chunks, and 6 of them are relevant (at ranks 2, 3, 5, 7, 8, 10). What are <code>Recall@10</code>, <code>Precision@10</code>, and the Reciprocal Rank (<code>RR</code>)?</strong></summary>
<p><strong>Answer:</strong> <code>Recall@10 = 6 / 8 = 0.75 (75%)</code>. <code>Precision@10 = 6 / 10 = 0.60 (60%)</code>. Since the first relevant chunk is at rank <code>2</code>, <code>Reciprocal Rank (RR) = 1 / 2 = 0.50</code>.</p>
</details>

<details>
<summary><strong>Q2: Why do two-stage RAG pipelines optimize Stage 1 (Hybrid BM25 + Vector) for <code>Recall@50</code> and Stage 2 (Cross-Encoder Reranker) for <code>nDCG@5</code>?</strong></summary>
<p><strong>Answer:</strong> Stage 1 is a fast coarse filter (<code>~25 ms</code>) over millions of chunks: if a relevant chunk is missed in Stage 1, Stage 2 can never recover it. Stage 2 runs a heavier Cross-Encoder (<code>~60 ms</code>) on those 50 candidates to rank the best 5 chunks at the very top (<code>nDCG@5</code>) and strip out the 45 noisy chunks before calling the LLM.</p>
</details>

<details>
<summary><strong>Q3: You are designing an Episodic Memory store for an agent with 5 million episode records where every query filters by <code>user_id</code> and requires ACID consistency with PostgreSQL session tables. Do you choose <code>pgvector</code> or <code>Milvus</code>?</strong></summary>
<p><strong>Answer:</strong> Choose <strong><code>pgvector</code> on PostgreSQL</strong>. Five million vectors fit comfortably in a single Postgres HNSW index (especially with <code>halfvec</code>), support transactional updates in the same ACID database as session state, and avoid the operational complexity and CDC sync lag of a separate distributed vector cluster.</p>
</details>

<details>
<summary><strong>Q4: Roughly how much RAM do 10 million 1,536-dimensional <code>float32</code> vectors take in an HNSW index, and how do you cut that memory by 2× to 4×?</strong></summary>
<p><strong>Answer:</strong> Raw vectors take <code>10M × 1,536 × 4 bytes ≈ 61.4 GB</code>, plus <code>~20 GB</code> for HNSW graph edges (<strong><code>~80 GB RAM</code></strong> total). Switching to <code>float16</code> (<code>halfvec</code>) cuts RAM by <code>2×</code> (<code>~40 GB</code>), and 8-bit Scalar Quantization (<code>SQ8</code>) cuts RAM by <code>4×</code> (<code>~20 GB</code>) with under 1% recall loss.</p>
</details>

<details>
<summary><strong>Q5: Your team increases the number of chunks passed directly to the LLM from <code>K = 5</code> to <code>K = 50</code> because <code>Recall@50</code> is 96%. Why does end-to-end answer accuracy drop by 15%?</strong></summary>
<p><strong>Answer:</strong> Passing 50 chunks drops <strong><code>Precision@50</code></strong> below 10%, flooding the prompt with 90%+ irrelevant text. This triggers the <strong>"Lost in the Middle"</strong> attention decay and increases hallucinations. Keep Stage-1 retrieval at <code>Top 50</code>, but use a Cross-Encoder Reranker to pass only the <code>Top 5</code> chunks to the LLM.</p>
</details>

---

### Sources & References
- **[1]** Christopher D. Manning, Prabhakar Raghavan & Hinrich Schütze, *Introduction to Information Retrieval* (Cambridge University Press) — Chapter 8: Evaluation (`Recall@K`, `Precision@K`, `MRR`, `nDCG`)
- **[2]** Yu A. Malkov & D. A. Yashunin, *Efficient and Robust Approximate Nearest Neighbor Search Using Hierarchical Navigable Small World Graphs (HNSW)* (IEEE TPAMI 2020)
- **[3]** `pgvector` Documentation — *HNSW, IVFFlat, `halfvec` Quantization, and Iterative Filtered Scans* — [github.com/pgvector/pgvector](https://github.com/pgvector/pgvector)
