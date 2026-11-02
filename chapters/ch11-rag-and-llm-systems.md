# Chapter 11: Production RAG, Hybrid Search & Enterprise ACL Security

*Part III · AI & LLM Engineering Systems · 9 min read*

Every weekend tutorial makes **Retrieval-Augmented Generation (RAG)** look like 10 lines of Python: chop a PDF into 500-word chunks, call an embedding API, dump vectors into a vector database, and pass the top 3 matches to an LLM.

Then you deploy that prototype at a real company with 50,000 internal documents, and three things immediately go wrong:
1. A developer searches for error code `ERR_4092_CONN_RESET`—and the vector database returns documents about *"emotional stress and resetting your mindset"* because dense vector embeddings blur exact alphanumeric codes!
2. An intern asks *"What is the CEO's compensation package?"*—and your RAG bot cheerfully quotes the confidential HR board deck!
3. Your p99 latency hits `6 seconds`, and your LLM API bill hits `$40,000/month`.

Let us design the **Production Enterprise RAG Pipeline** that solves all three [1, 2].

{{diagram:04-rag-and-agents.excalidraw}}

---

### 1) Why Dense Vector Search Alone Fails (And Why Hybrid Search + Reranking Wins)

Look at the top pipeline in the diagram above. When a user asks a question, there are **two complementary ways** to find relevant chunks [1, 2]:

| Retrieval Method | How It Works | What It Is Great At | Where It Fails |
| :--- | :--- | :--- | :--- |
| **1. Sparse Keyword Search (`BM25`)** | Inverted index (Elasticsearch / OpenSearch) matching exact terms weighted by rareness (`TF-IDF`). | Exact part numbers (`SKU-9912`), function names, error codes, acronyms. | Fails on synonyms (*"laptop won't boot"* misses a doc titled *"MacBook startup failure"*). |
| **2. Dense Vector Search (`HNSW` / `IVF`)** | Maps text to a `768–1536` float vector; finds nearest neighbors by cosine similarity in an **HNSW graph**. | Semantic meaning and paraphrasing across different words. | Blurs exact IDs, numbers, and rare domain jargon; HNSW indexes are RAM-heavy (`~6 KB per vector`). |

**The Production Architecture (Two-Stage Retrieval):**
1. **Stage 1 — Parallel Hybrid Retrieval (`Top 50` in `~30 ms`):** Run `BM25` keyword search AND `HNSW` vector search in parallel, then merge the two ranked lists using **Reciprocal Rank Fusion (`RRF`)**:
   `score(doc) = 1 / (60 + rank_bm25) + 1 / (60 + rank_vector)` [2].
2. **Stage 2 — Cross-Encoder Reranker (`Top 50 -> Top 5` in `~60 ms`):** Pass the 50 candidate chunks + query into a compact **Cross-Encoder Reranker** (like `Cohere Rerank` or `BGE-Reranker`). Unlike embeddings (which compress a whole chunk into one vector ahead of time), a Cross-Encoder attends across every query word and chunk word together, picking the **Top 5 gold chunks** so your LLM prompt stays short, cheap, and accurate.

---

### 2) The #1 Enterprise RAG Security Bug: Post-Retrieval ACL Filtering

Suppose your company has 1,000,000 document chunks, and **990,000** of them belong to Executive HR, while **10,000** belong to Engineering.

An engineer queries the vector database for **"Top 10 chunks matching '2026 Q3 roadmap'"**, and your code filters out unauthorized chunks *after* the vector search returns (**Post-Filtering**):
- What happens if all 10 of the closest vectors in the database happen to be in Executive HR?
- Your post-filter throws away all 10 results and returns **`0 chunks`**—even though Engineering had 50 valid roadmap docs sitting at ranks `#11..#60`!

**The Production Rule:** Always enforce **Pre-Retrieval ACL Metadata Filtering** inside the vector/hybrid index query itself [1]:
- At ingestion time, stamp each chunk with its Access Control List: `acl_groups: ["eng-all", "public"]`.
- At query time, resolve the caller's groups (`user_groups = ["eng-all"]`) and pass a mandatory filter predicate **into the HNSW + BM25 search**: `WHERE acl_groups OVERLAPS ['eng-all', 'public']`.
- Never cache semantic RAG answers globally across users with different ACL permissions.

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why do production RAG systems retrieve Top 50 with Hybrid Search (BM25 + Vector) and then narrow to Top 5 with a Cross-Encoder Reranker?</strong></summary>
<p><strong>Answer:</strong> Bi-encoder vector search + BM25 is fast enough (<code>~20–30 ms</code>) to scan millions of chunks for high recall, while a Cross-Encoder is much more accurate at pairwise relevance scoring—running it on just the Top 50 takes <code>~60 ms</code> and cuts LLM input tokens by <code>10×</code>.</p>
</details>

<details>
<summary><strong>Q2: Why does Post-Retrieval ACL filtering break RAG recall?</strong></summary>
<p><strong>Answer:</strong> If you ask the vector index for <code>Top K=10</code> globally and then drop the 10 results because the user lacks permission, the user gets <strong>zero results</strong> even when authorized documents existed at rank 11.</p>
</details>

<details>
<summary><strong>Q3: What is Reciprocal Rank Fusion (RRF), and why is it used to combine BM25 and Vector scores?</strong></summary>
<p><strong>Answer:</strong> BM25 scores (unbounded floats like <code>14.2</code>) and cosine similarity scores (<code>0.0 to 1.0</code>) live on incompatible scales. RRF combines their <strong>ordinal ranks</strong> (<code>1/(60 + rank)</code>) without needing brittle score calibration.</p>
</details>

---

### Sources & References
- **[1]** Chip Huyen, *AI Engineering: Building Applications with Foundation Models* (O'Reilly, 2025) — RAG, Hybrid Retrieval & Reranking
- **[2]** Anthropic Engineering, *Contextual Retrieval: Combining Contextual Embeddings and Contextual BM25 with Reranking* — [anthropic.com/news/contextual-retrieval](https://www.anthropic.com/news/contextual-retrieval)
- **[3]** Eugene Yan et al., *Applied LLMs: What We've Learned From A Year of Building with LLMs* — [applied-llms.org](https://applied-llms.org/)
