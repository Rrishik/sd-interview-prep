# Chapter 25: AI System Design Brainstorming — Multi-Repo Code Search, <100ms Scoring & Interview Traps

*Part V · LLM Internals, Harnesses & Multimodal · 9 min core · 20 min with deep dives*

In a Senior/Staff AI System Design round, jumping straight to *"We'll put `vLLM` + `Milvus` + `LangGraph` behind an API Gateway"* is a yellow flag.

Strong candidates **brainstorm options out loud (`Option A -> Option B -> Option C`)**, anchor every box to an explicit **latency, freshness, and dollar budget**, name **what they would cut if the budget halved**, and steer clear of plausible-sounding **production traps** [1].

Let us walk through three real-world design drills—**Multi-Repo Codebase Search (`10,000` repos)**, **`<100 ms` Inline Risk/Safety Scoring**, and **Model/Prompt Ship-Gates**—followed by the **10 "Wrong Answers"** interviewers use to test production depth [1, 2, 3, 4].

{{diagram:13-codebase-rag-and-tradeoffs.excalidraw}}

---

### 1) Case Study 1: Cited Search & Copilot Indexing Over 10,000 Code Repositories

**Prompt:** *Design code Q&A across `10,000` internal repos (`~200M` lines of code, `10k QPS` peak) where answers must cite exact `repo:path:Lstart-Lend` spans and reflect new `git push` commits within **`<60 seconds`** [1].*

**Brainstorming the Options (`Naive -> Better -> Production`):**

| Design Option | How It Works | Why It Fails or Wins at `200M` LOC |
| :--- | :--- | :--- |
| **Option A: Giant `1M`-Token Context** | Stuff repo files directly into a long-context model. | **Fails:** `200M` LOC is `~1.5B` tokens (`1,500×` window), costs `$5+`/query, and has no cross-repo ranking [1]. |
| **Option B: Fixed `500`-Token Vector RAG** | Slice code every `500` tokens + cosine HNSW search. | **Fails:** Slices functions in half, misses exact symbol names (`check_acl_v2`), and gets **poisoned by `20%` generated protobuf/lockfile boilerplate** crowding Top-K [1]! |
| **Option C: AST + 3-Modality Index + Call Graph** | **Tree-sitter AST** spans + **Dense + Weighted BM25 + Cached NL Summary** + **Cross-Repo Symbol Graph** + **`<60s` AST diff webhook** [1, 2]. | **Wins:** Coherent symbol units, bridges NL intent (`"auth check"`) to terse code (`chk_perm()`), traverses cross-repo imports, and re-indexes only mutated functions [1, 2]! |

**Four Load-Bearing Details of Option C [1, 2]:**
1. **Syntax-Aware Ingestion (`Tree-sitter` [2]):** Parse files into function/class/method AST nodes (`repo`, `commit_sha`, `path`, `symbol`, `start_line`, `end_line`), flagging generated files (`*.pb.go`, `dist/`, lockfiles) in metadata so ranking down-weights boilerplate [1].
2. **Three Retrievable Modalities + Cross-Repo Graph:** Index each AST node as (a) **dense code embedding**, (b) **field-weighted sparse BM25** (`symbol_name ×4`, `summary ×2`, `body ×1`), and (c) **1-sentence natural-language summary** generated once by a small model (with cached system preamble) to bridge vocabulary mismatch—plus a **symbol graph** (`imports`, `calls`, `inherits`) to expand Top-50 candidates `1` hop across repo boundaries before cross-encoder reranking (`50 -> 10`) [1].
3. **`<60s` Incremental Freshness on `git push`:** Never re-embed a whole repository on push! Compute a content hash per AST node on changed files; re-embed + re-summarize **only modified/new functions**, update changed call-graph edges, and tombstone deleted symbols across all stores within `60 seconds` [1].
4. **Deterministic Span Verification & Half-Budget Cut:** Parse every `[repo:path:L10-L28]` citation against the indexed commit tree—dropping or re-asking any claim with a missing or unsupported span. *If budget halves:* drop LLM-generated summaries on cold/archived repos first (keep AST + weighted BM25 + dense code embeddings on active branches) [1].

---

### 2) Case Study 2: `<100 ms` Inline Real-Time Scoring & Content-Addressed Ship-Gates

**A. Designing `<100 ms` `p99` Inline Scoring (Fraud, Abuse, or Prompt-Safety Gate at `5,000 QPS`) [1, 3]:**
- **Why Frontier LLMs Are Disqualified Inline:** A `500 ms` LLM call blows a `100 ms` `p99` checkout/chat budget by `5×`. Size concurrency with **Little's Law (`L = λ × W`)**: at `5,000 QPS` and `40 ms` mean service time, `L = 5,000 × 0.04 = 200` requests are in flight—easily served by a small pool of stateless replicas calling:
  1. **Online Feature Store (`<5 ms` Redis / DynamoDB):** Pre-materialized entity counters synced from an offline store via **point-in-time joins** (logging exact serving-time feature vectors to Kafka so retraining never suffers **training–serving skew**!) [1, 3].
  2. **Distilled Encoder / Small Classifier (`<25 ms` ONNX / TensorRT):** Emits calibrated risk score split by two thresholds into `ALLOW`, `STEP_UP_REVIEW`, or `BLOCK`—falling back deterministically to fast heuristic rules if the model times out at `60 ms` [1].
- **The Two Silent Post-Launch Killers [1, 3]:**
  1. **Censored-Label Feedback Loop:** Blocked transactions/messages *never execute*, so they never generate chargebacks or user reports—causing the next retrained model to falsely learn that blocked patterns are "safe"! Fix: allow a strictly capped **`1%` exploration holdout** (or human-labeled audit sample of blocks) with explicit propensity weights [1, 3].
  2. **Silent Concept Drift:** Input feature distributions look `100%` green while adversarial behavior shifts—caught only by **delayed-outcome monitors** and shadow canaries [1].

**B. Designing the Model & Prompt Release Ship-Gate (`Eval & Alignment Pipeline`) [1, 4]:**
- Every candidate model/prompt run produces an immutable, **hash-chained manifest** (`seed`, `git_sha`, stage `input_hash -> output_hash`, `eval_dataset_hash`) so any engineer can deterministically replay why a release shipped [1].
- **Three Non-Negotiable Numeric Gates:** (1) **`13-gram` Train–Eval De-Contamination Gate (`<0.1%` overlap)** *before* SFT starts, (2) **Stage-by-Stage Ablation Gate (`Base -> SFT -> SFT+DPO -> Quantized`)** proving preference tuning didn't regress core tasks, and (3) **KL-Divergence Budget Gate** [4] ensuring RLHF/DPO alignment did not overcook the policy into sycophancy or mode collapse [1, 4].

:::deepdive Prompt & Semantic Cache Break-Even Math + Multi-Provider Outage Failover | +5 min

1. **Exact Prefix-Cache Break-Even Math [1, 5]:**
   - Suppose a provider charges **`1.25×`** base input price to write a `5-minute` KV prefix cache and **`0.10×`** to read it (`2.0×` write for a `1-hour` TTL cache) [5]:
     - **`5-min` TTL (`1` write + `1` read):** `(1.25 + 0.10) / 2 = 0.675×` normal price (**`32.5%` savings on the very first reuse!**; `1` write + `10` reads = `0.205×` -> **`80%` saved**).
     - **`1-hour` TTL (`2.0×` write):** `1` write + `1` read averages `(2.0 + 0.10) / 2 = 1.05×` (net loss!), breaking even at **`>= 2` reads** (`(2.0 + 0.20) / 3 = 0.73×`) [1].
     - **Three Production Cache Traps:** (a) Blocks shorter than the provider's `1,024-token` minimum silently skip caching, (b) `50` parallel cold requests arriving *before* the first write commits all pay `1.25×` (**cache stampede**—coalesce cold writes or warm prefixes on deploy!), and (c) never run semantic caching at `temperature > 0` for creative diversity or without `(tenant_id, acl_hash)` key isolation [1, 5].
2. **Regional Provider Outage Degradation Ladder [1]:**
   - `Primary Model (bounded timeout, zero blind retries on 529 overload)` -> `Cross-Provider Fallback Model (normalized via Gateway schema adapter)` -> `Tenant-Scoped Semantic/Exact Cache for hot queries` -> `Graceful Deterministic Fallback UI` (all tracked per-step on a single cost/latency trace) [1].

:::

:::deepdive 10 "Tempting Wrong Answers" Interviewers Bait Candidates Into | +5 min

Memorize why these plausible-sounding answers fail in Senior/Staff interviews [1]:

| Tempting Wrong Answer | Why It Fails in Production | Senior / Staff Engineering Answer |
| :--- | :--- | :--- |
| **1. "A `1M`-token window replaces RAG."** | `O(N)` cost/TTFT per query, cannot hold `200M` LOC, and attention decays in the middle [6]. | Use hybrid retrieval + reranking to select the top `5–15` spans, then reason in context [1]. |
| **2. "Prefill/decode disaggregation boosts single-GPU FLOPs."** | It adds RDMA KV-transfer cost; total FLOPs don't rise. | It eliminates prefill stalls on decode streams so independent pools maximize **SLO Goodput** [7]. |
| **3. "Always enable speculative decoding in prod."** | At high batch (`>=64`) or low `α < 0.55`, draft rejections burn compute and hurt `p99` [8]. | Measure `α` on real domain traffic and disable speculation above a dynamic batch threshold [1, 8]. |
| **4. "Our cluster hits `20k tok/s` so UX is fast."** | High aggregate throughput at `batch=512` often hides `4s` `TTFT` and `60 ms` `TPOT`. | Gate capacity and autoscaling on **multi-SLO Goodput** (`TTFT` + `TPOT` + `E2E` at `p99`) [7]. |
| **5. "`INT4 AWQ` makes a `70B` model fit any load in `40 GB`."** | Weight-only `INT4` shrinks weights (`35 GB`) while `FP16` KV cache still takes `30+ GB` at scale! | Budget `Weights + Paged KV Pool + Activations`, and pair `AWQ` with `FP8` KV quantization [1]. |
| **6. "Quantize after evals pass and ship immediately."** | `4-bit` rounding can silently break tool-call JSON schemas or math reasoning on domain edge cases. | Treat quantized weights as a **new artifact** that must pass the full eval & safety ship-gate [1]. |
| **7. "Disable caches during load tests for fairness."** | Production runs *with* prefix caching (`70%+` hit rate); cold-only tests mis-size prefill pools! | Seed realistic zipfian prefix reuse *and* test cold-cache stampede behavior separately [1]. |
| **8. "Re-index the repo on every commit for simplicity."** | Re-embedding `2M–200M` LOC per commit blows freshness to hours and burns `$1,000s`/day. | Hash AST symbol nodes and re-embed/tombstone **only the symbol diff** in `<60s` [1, 2]. |
| **9. "Retrain weekly only on allowed transactions."** | Blocked items lack ground-truth labels (**selection bias**), blinding future models to blocked attacks [3]. | Log serving-time features + maintain a `1%` audited exploration sample with importance weights [1, 3]. |
| **10. "Scale GPU pods on average CPU/GPU utilization."** | A GPU sits at `95%` memory/compute both when healthy (`batch=32`) and when `500` users are queued! | Autoscale LLM fleets on **scheduler queue depth** and **in-flight KV-cache block utilization** [1]. |

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** Brainstorming AI System Design is like **urban transit engineering**: you don't propose a bullet train (`Autonomous Agent / Dedicated H100 Fleet`) before checking passenger volume, station transfer times (`AST diff / <5ms feature store`), and fare box recovery (`Cache & GPU break-even math`) against dedicated bus lanes (`Deterministic Workflow / Hybrid Search`).
- **Where the analogy breaks:** Concrete bridges degrade over decades; AI systems suffer **silent distribution shift, censored feedback loops, and prompt/model regressions overnight** unless guarded by automated contamination checks, exploration holdouts, and live canary gates [1, 3].
- **Real production system:** **GitHub Copilot / Cursor Codebase Indexing** (Tree-sitter AST + Merkle/symbol diffs), **Stripe Radar** (`<100 ms` point-in-time feature cascades + exploration holdouts), and **Anthropic / OpenAI Prefix Caching** embody these exact architectures [1, 2, 5].

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why does chunking source code at Tree-sitter AST function/class boundaries beat fixed 500-token windows, and why add an LLM summary modality?</strong></summary>
<p><strong>Answer:</strong> AST boundaries keep each function/class intact with stable <code>repo:path:line</code> citations and enable fast per-symbol diff re-indexing on <code>git push</code>. Adding a cached-preamble 1-sentence NL summary bridges vocabulary mismatch between natural-language questions (<em>"how is auth enforced?"</em>) and terse identifiers (<code>chk_acl()</code>).</p>
</details>

<details>
<summary><strong>Q2: What is the "censored-label feedback loop" in a &lt;100 ms blocking classifier (fraud, spam, or safety), and how do you prevent it?</strong></summary>
<p><strong>Answer:</strong> Actions blocked by the model never complete, so you never observe whether they were truly fraudulent or benign—causing retrained models to underestimate risk on previously blocked patterns. Prevent it via a small audited exploration holdout (e.g., 1%) or human-labeled review sample weighted by propensity.</p>
</details>

<details>
<summary><strong>Q3: A provider charges 1.25× input price to write a 5-minute prefix cache and 0.10× to read it. How many cache reads are needed to break even?</strong></summary>
<p><strong>Answer:</strong> Just <strong>1 read</strong>! One write plus one read costs <code>(1.25 + 0.10) / 2 = 0.675×</code> the normal uncached price per call (a <code>32.5%</code> saving immediately), whereas a <code>2.0×</code> 1-hour cache requires at least <strong>2 reads</strong> to beat uncached pricing.</p>
</details>

<details>
<summary><strong>Q4: Why should LLM serving fleets autoscale on scheduler queue depth and KV-cache block fullness rather than raw GPU compute utilization?</strong></summary>
<p><strong>Answer:</strong> Continuous batching keeps GPU utilization high across both healthy latency (<code>batch=24</code>) and severe overload (<code>300</code> queued requests waiting 5 seconds for prefill). Queue depth and KV-block pressure directly lead <code>TTFT</code> and <code>TPOT</code> SLO violations before timeouts cascade.</p>
</details>

---

### Sources & References
- **[1]** Rohit Ghumare et al., *AI Engineering from Scratch — AI System Design, Cost/Capacity & Multi-Agent Interview Bank* — [aiengineeringfromscratch.com/interviews](https://aiengineeringfromscratch.com/interviews)
- **[2]** Max Brunsfeld et al., *Tree-sitter: An Incremental Parsing System for Programming Tools (AST Code Chunking)* — [tree-sitter.github.io/tree-sitter](https://tree-sitter.github.io/tree-sitter/)
- **[3]** D. Sculley et al. (Google), *Hidden Technical Debt in Machine Learning Systems (Feedback Loops & Training-Serving Skew)* (NeurIPS 2015) — [papers.nips.cc/paper/2015/hidden-technical-debt](https://papers.nips.cc/paper_files/paper/2015/hash/86df7dcfd896fcaf2674f757a2463eba-Abstract.html)
- **[4]** Rafael Rafailov et al., *Direct Preference Optimization: Your Language Model is Secretly a Reward Model (KL-Constrained Alignment)* (NeurIPS 2023) — [arxiv.org/abs/2305.18290](https://arxiv.org/abs/2305.18290)
- **[5]** Anthropic Documentation, *Prompt Caching Pricing, Break-Even & Minimum Token Thresholds* — [platform.claude.com/docs/en/build-with-claude/prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- **[6]** Nelson F. Liu et al., *Lost in the Middle: How Language Models Use Long Contexts* (TACL 2024) — [arxiv.org/abs/2307.03172](https://arxiv.org/abs/2307.03172)
- **[7]** Yinmin Zhong et al., *DistServe: Disaggregating Prefill and Decoding for Goodput-Optimized LLM Serving* (USENIX OSDI 2024) — [arxiv.org/abs/2401.09670](https://arxiv.org/abs/2401.09670)
- **[8]** Yuhui Li et al., *EAGLE-3: Scaling up Inference Acceleration of Large Language Models* (2025) — [arxiv.org/abs/2503.01840](https://arxiv.org/abs/2503.01840)
