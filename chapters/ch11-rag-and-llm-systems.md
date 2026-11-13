# Chapter 11: Production RAG, Hybrid Search & Enterprise ACL Security

*Part III · AI & LLM Engineering Systems · 8 min core · 17 min with deep dives*

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
   `score(doc) = 1 / (60 + rank_bm25) + 1 / (60 + rank_vector)` [2, 4].
2. **Stage 2 — Cross-Encoder Reranker (`Top 50 -> Top 5` in `~60 ms`):** Pass the 50 candidate chunks + query into a compact **Cross-Encoder Reranker** (like `Cohere Rerank` or `BGE-Reranker`). Unlike embeddings (which compress a whole chunk into one vector ahead of time), a Cross-Encoder attends across every query word and chunk word together, picking the **Top 5 gold chunks** so your LLM prompt stays short, cheap, and accurate.

:::deepdive Ingestion, Chunking Trade-Offs, Query Rewriting & Grounded Citations | +5 min

Retrieval quality is capped by how documents are normalized and chunked long before any vector search runs:

| Design Lever | Options & Mechanics | Production Trade-Off |
| :--- | :--- | :--- |
| **1. Document Normalization** | Parse PDFs/HTML/Markdown into structure-aware AST blocks (preserving section headers and markdown tables intact). | Naive character slicing splits a pricing table row away from its column headers, making the chunk unintelligible. |
| **2. Chunk Size & Overlap** | **Small (`128–256` tokens):** Sharp embedding focus, lacks surrounding context.<br>**Medium (`400–600` tokens, `10–15%` overlap):** Industry sweet spot.<br>**Large (`1,024+` tokens):** Dilutes vector specificity; wastes prompt budget. | **Contextual Retrieval Fix [2]:** Prepend a 1-sentence document/section breadcrumb (`"[Doc: Q3 Billing Policy > EU Refunds] ..."`) to each `400`-token chunk *before* computing both its embedding and BM25 terms—cutting retrieval failure rates by `~49%`. |
| **3. Query Rewriting** | Rewrite conversational queries (*"What about for contractors?"* -> *"EU refund eligibility policy for contractors"*), or expand ambiguous queries into `2–3` lexical + semantic variants. | Adds `~120 ms` with a small fast model, but rescues follow-up turns whose pronouns (`"it"`, `"that error"`) carry zero retrieval signal. |
| **4. Grounded Synthesis & Citations** | Format retrieved chunks with XML/ID tags (`<source id="doc_42#c7">...</source>`) and instruct the model to emit inline `[doc_42#c7]` citations—or abstain if unsupported [3]. | Run a lightweight post-check verifying that every cited `id` actually exists in the retrieved Top-K set (catching fabricated citation IDs before streaming to the UI). |

:::

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

:::deepdive Index Freshness, CDC Tombstones & Permission Revocation | +4 min

Static benchmarks ignore the hardest day-2 RAG problem: **source documents and user permissions change every minute**.

1. **Event-Driven CDC Ingestion (`< 30s` Freshness):** Publish source writes (`doc.updated`, `doc.deleted`, `acl.changed`) via an **Outbox + Kafka** pipeline [1]. Hash each normalized chunk (`SHA256(text)`): when a 50-page doc changes one paragraph, re-embed only the `1–2` dirty chunks instead of all `120` chunks [3].
2. **Permission-Change Decoupling:** If `doc_42` moves from `public` to `exec-only`, re-embedding vectors is wasteful. Store ACLs in a fast metadata attribute / joinable permission table so ACL updates take effect in milliseconds without touching float vectors.
3. **Deleted/Superseded Version Guard:** If Kafka CDC lags by `10 seconds`, a recently deleted doc could still appear in HNSW. Perform a `2 ms` batch primary-key/version check (`SELECT id, acl_epoch FROM docs_meta WHERE id IN (...)`) on the final Top 5 chunks right before prompt assembly to guarantee **read-after-delete** and **instant ACL revocation**.

:::

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

<details>
<summary><strong>Q4: Why does prepending a document/section header breadcrumb to each chunk before embedding ("Contextual Retrieval") dramatically reduce retrieval misses?</strong></summary>
<p><strong>Answer:</strong> Isolated 400-token chunks often say things like <em>"Revenue grew 12% in Q3"</em> without naming which company or year. Prepending <code>[Acme Corp 2025 10-K &gt; Q3 Results]</code> anchors both dense embeddings and BM25 keywords to the owning entity.</p>
</details>

---

### Sources & References
- **[1]** Chip Huyen, *AI Engineering: Building Applications with Foundation Models* (O'Reilly, 2025) — RAG, Hybrid Retrieval & Reranking
- **[2]** Anthropic Engineering, *Contextual Retrieval: Combining Contextual Embeddings and Contextual BM25 with Reranking* (2024) — [anthropic.com/news/contextual-retrieval](https://www.anthropic.com/news/contextual-retrieval)
- **[3]** Eugene Yan et al., *Applied LLMs: What We've Learned From A Year of Building with LLMs* — [applied-llms.org](https://applied-llms.org/)
- **[4]** Gordon V. Cormack, Charles L. A. Clarke & Stefan Buettcher, *Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods* (ACM SIGIR 2009) — [plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
