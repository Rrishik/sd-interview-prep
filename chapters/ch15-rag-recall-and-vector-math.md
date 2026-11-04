# Chapter 15: Retrieval Math (Recall@K, MRR, nDCG@K) & Vector Indexes (pgvector vs Milvus)

*Part III · AI & LLM Engineering Systems · 8 min read*

When an enterprise RAG agent gives a wrong answer, who is at fault?
Did the **Retriever** fail to pull the right chunk out of 10 million documents, or did the **Generator LLM** misread the chunk sitting at Rank #1?

To isolate the Retriever from the Generator—and choose the right vector index (`HNSW` vs. `IVF`, `pgvector` vs. `Milvus`)—production teams track four retrieval metrics against a labeled ground-truth set [1, 2].

{{diagram:06-mcp-evals-reactive.excalidraw}}

---

### 1) The Four Core Retrieval Metrics: `Recall@K`, `Precision@K`, `MRR` & `nDCG@K`

Suppose for query `q`, the database contains **`4` relevant chunks** (`Total_Relevant = 4`), and our retriever returns **`Top K = 5` chunks** where ranks **#1, #3, and #5** are relevant (`[✅, ❌, ✅, ❌, ✅]`):

| Metric | Formula | Value on `[✅, ❌, ✅, ❌, ✅]` | Where It Is Used in Production |
| :--- | :--- | :--- | :--- |
| **1. `Recall@K`** *(Coverage)* | `Relevant_in_Top_K / Total_Relevant_in_DB` | `3 / 4 = 0.75` (**`75%`**) | **Primary metric for Stage-1 Hybrid Retrieval (`Top 50`):** Did the evidence make it into the candidate net? |
| **2. `Precision@K`** *(Signal Ratio)* | `Relevant_in_Top_K / K` | `3 / 5 = 0.60` (**`60%`**) | Quantifies **prompt noise** (`40%` of retrieved chunks are distractions). |
| **3. `MRR`** *(Mean Reciprocal Rank)* | `Avg(1 / rank_of_FIRST_relevant)` | First ✅ at rank `1` -> **`1.00`** *(if first ✅ is at #3, `1/3 = 0.33`)* | Best when the agent only needs **one exact lookup** (error code or API spec). |
| **4. `nDCG@K`** *(Ranking Quality)* | `DCG@K / IDCG@K`, with `DCG@K = Σ rel_i / log2(i + 1)` | Penalizes pushing high-grade matches (`rel=3`) down the list. | **Primary metric for Stage-2 Cross-Encoder Rerankers (`Top 5`).** |

**Why Stuffing `Top 50` Chunks Directly Into the Prompt Backfires:**
Even if `Recall@50` is `96%`, having only 3 relevant chunks means `Precision@50 = 3/50 = 6%`. Flooding the prompt with `94%` irrelevant text triggers **"Lost in the Middle" attention dilution** and increases hallucinations. Always use Stage 1 (`BM25 + Vector RRF`) to maximize **`Recall@50`**, and a Stage 2 **Cross-Encoder Reranker** to maximize **`nDCG@5`** before calling the LLM [1].

---

### 2) Vector Index Internals (`HNSW` vs. `IVF-PQ`) & RAM Math

How do you search 10 million `1,536-dim float32` vectors in `5 ms` instead of a `600 ms` brute-force scan?

- **`HNSW` (Hierarchical Navigable Small World Graph):** Multi-layer proximity skip-graph with long highway jumps at the top and dense neighbor edges (`M` links) at Layer 0 [2].
  - **The RAM Math:** `10M × 1,536 × 4 bytes = 61.4 GB` of raw vectors + `~20 GB` of graph edges = **`~80 GB RAM`**. Switching to `float16` (`halfvec`) or 8-bit Scalar Quantization (`SQ8`) cuts RAM by **`2×` to `4×`** (`20–40 GB`) with `< 1%` recall loss [3].
- **`IVF-PQ` (Inverted File + Product Quantization):** Partitions space into `C` K-means centroids and compresses sub-vectors into codebooks, scanning only the closest `nprobe` buckets. Uses a fraction of the RAM at slightly lower recall.

---

### 3) Choosing Between `pgvector` (PostgreSQL) and `Milvus`

| Criterion | Choose `pgvector` (PostgreSQL) | Choose `Milvus` (Distributed Vector Engine) |
| :--- | :--- | :--- |
| **Scale** | Up to **`10M – 50M` vectors** (with `halfvec` HNSW + iterative filtered scan). | **`100M – 10B+` vectors** across disaggregated query/storage nodes. |
| **Consistency & Joins** | **Full ACID transactions** in the same table as user state and ACL metadata (zero CDC lag). | Tunable consistency; synced asynchronously from OLTP via Kafka CDC. |
| **Best Agent Role** | **Episodic & Semantic Agent Memory** (filtered per `user_id` and `is_active = true`). | **Global Enterprise Knowledge Corpus RAG** across billions of chunks. |

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **`Recall@K`** asks what fraction of swimmers in the water made it into the rescue net; **`Precision@K`** asks what fraction of the net is swimmers vs. seaweed; **`nDCG@K`** asks whether the most critical swimmer is right on top at Rank #1.
- **Where the analogy breaks:** Extra seaweed in a boat just adds weight; extra irrelevant chunks in an LLM prompt actively **corrupt self-attention** and cause hallucinations.
- **Real production system:** **GitHub Copilot & Stripe Docs Search** pair lexical `BM25` + `HNSW` vector retrieval (optimizing `Recall@50`) with a fast cross-encoder reranker (optimizing `nDCG@5`) [1, 3].

---

### Quick Self-Check

<details>
<summary><strong>Q1: A database has 8 relevant chunks for a query. Your retriever returns Top K = 10 chunks with 6 relevant matches at ranks 2, 3, 5, 7, 8, and 10. What are <code>Recall@10</code>, <code>Precision@10</code>, and <code>RR</code>?</strong></summary>
<p><strong>Answer:</strong> <code>Recall@10 = 6 / 8 = 0.75 (75%)</code>, <code>Precision@10 = 6 / 10 = 0.60 (60%)</code>, and since the first relevant hit is at rank 2, <code>Reciprocal Rank (RR) = 1 / 2 = 0.50</code>.</p>
</details>

<details>
<summary><strong>Q2: Roughly how much RAM do 10 million 1,536-dim <code>float32</code> vectors require in HNSW, and how do you cut that by 2×–4×?</strong></summary>
<p><strong>Answer:</strong> Raw vectors take <code>10M × 1536 × 4B ≈ 61.4 GB</code> plus <code>~20 GB</code> for HNSW graph edges (<code>~80 GB</code> total). Using <code>float16</code> (<code>halfvec</code>) cuts RAM by <code>2×</code> (<code>~40 GB</code>), and 8-bit Scalar Quantization (<code>SQ8</code>) cuts it by <code>4×</code> (<code>~20 GB</code>) with under 1% recall loss.</p>
</details>

<details>
<summary><strong>Q3: For an agent's Episodic Memory store of 5 million records requiring ACID consistency with PostgreSQL user tables, do you pick <code>pgvector</code> or <code>Milvus</code>?</strong></summary>
<p><strong>Answer:</strong> Pick <strong><code>pgvector</code></strong>: 5M vectors fit easily in a single Postgres HNSW index with <code>halfvec</code>, allow transactional updates alongside session rows, and avoid distributed cluster overhead and CDC lag.</p>
</details>

---

### Sources & References
- **[1]** Christopher D. Manning, Prabhakar Raghavan & Hinrich Schütze, *Introduction to Information Retrieval* — Chapter 8: Evaluation (`Recall@K`, `Precision@K`, `MRR`, `nDCG`)
- **[2]** Yu A. Malkov & D. A. Yashunin, *Efficient and Robust Approximate Nearest Neighbor Search Using HNSW Graphs* (IEEE TPAMI 2020)
- **[3]** `pgvector` Documentation — *HNSW, `halfvec` Quantization & Iterative Filtered Scans* — [github.com/pgvector/pgvector](https://github.com/pgvector/pgvector)
