# Chapter 26: Flagship AI System Designs — Web Answer Engine, PR Code Reviewer & Doc Intelligence

*Part V · LLM Internals, Harnesses & Multimodal · 9 min core · 20 min with deep dives*

Three open-ended AI System Design prompts show up repeatedly in Senior/Staff loops at frontier labs and developer-platform companies:
1. **Design a Web-Scale Cited Answer Engine (*Perplexity / SearchGPT*)** serving `10,000+ QPS` with `<1.2s TTFT` and `<60s` breaking-news freshness [1, 2].
2. **Design an Autonomous Pull-Request Code-Review Bot (*Copilot Code Review / Meta CodeCompose*)** that developers actually trust instead of muting [4, 5].
3. **Design an Enterprise Multimodal Document Pipeline (`10M` PDFs/day)** extracting tables, charts, and visual bounding-box citations [7, 8].

Let us brainstorm each from naive baseline to production architecture—explicitly naming the **latency budgets, failure modes, and trade-offs** [1, 4, 7, 8].

{{diagram:14-flagship-ai-designs.excalidraw}}

---

### 1) Flagship Design 1: Web-Scale Cited Answer Engine (*Perplexity / SearchGPT*)

Why is web-scale AI search harder than internal Enterprise RAG (Chapter 11)?
Because the open web has **billions of adversarial SEO/prompt-injection pages** [3], breaking news mutates **every 30 seconds**, and when a major event happens, **`500,000` users ask the exact same question in the same minute** [2]!

| Option | Architecture | Why It Fails or Wins at `10,000 QPS` |
| :--- | :--- | :--- |
| **Option A: Live Headless Browser Scrape** | Query Google -> launch Chromium on Top 10 URLs -> parse HTML -> summarize. | **Fails:** `3–6s` page-load tail latency, bot-blocking CAPTCHAs, and `100×` CPU burn. |
| **Option B: Static Daily Web Vector Index** | Embed crawled pages nightly into HNSW -> retrieve Top 10 -> stream LLM. | **Fails:** Blind to breaking news (`"Fed rate decision 3 mins ago"`) and bloated petabyte float RAM. |
| **Option C: Temporal Router + Tiered Fresh/Warm Index + `Singleflight` Coalescing** | `<15 ms` classifier routes temporal queries to an **in-RAM `<60s` RSS/news index** + **SSD lexical/vector shards**, coalescing hot queries via `singleflight` [1, 2]. | **Wins:** **`<1.1s` `p95` `TTFT`**, fresh live facts, and `95%` GPU savings during viral news spikes [2]! |

**End-to-End `1,050 ms` `TTFT` Budget & Safety Controls [1, 2, 3]:**
1. **Query Rewrite + `Singleflight` Coalescing (`~60 ms`):** Expand conversational query into `3` parallel search queries; deduplicate identical in-flight trending queries via **`singleflight` request coalescing** [2] + `30s`-TTL hot-event cache so `50,000` concurrent *"Super Bowl score"* queries trigger **1** upstream synthesis stream fanned out to all subscribers!
2. **Tiered Retrieval + Sub-Passage Scoring (`~180 ms`):** Fetch Top `80` URLs across the **RAM Fresh Tier** (`<60s` news/social firehose) and **Warm SSD BM25 + Compact Vector Tier**, strip hidden CSS/DOM prompt-injection traps [3], slice into `300-token` windows, and score down to the **Top `10` passages** (`~3,000` tokens) via a distilled `INT8` cross-encoder.
3. **Streaming Inline Citations (`ALCE` Grounding) (`~800 ms` prefill -> stream) [1]:** Stream markdown claims with `[1]`, `[2]` URL badges while running an async sentence-level entailment check (`ALCE` [1])—suppressing unsupported claims or unverified URLs before link rendering.

---

### 2) Flagship Design 2: Autonomous PR Code-Review Bot (*Copilot Review / CodeCompose*)

Every naive AI PR bot fails the same way: it feeds `git diff` into an LLM, leaves 14 nitpicky comments (*"Consider renaming `i` to `index`"* or hallucinating a null-pointer bug already guarded 20 lines above the diff hunk), and **developers mute the bot within a week**!

Google's **Tricorder** study established the iron law of developer-tool adoption: **any automated analyzer whose "not-useful" (false-positive) rate exceeds `~10%` loses developer trust and gets disabled** [4, 5].

**Four Architectural Pillars of a `<10%` Noise AI PR Reviewer [4, 5, 6]:**
1. **Deterministic Tools First, LLM Second:** Run `clang-format` / `eslint`, typecheckers, and deterministic `SAST` rules *before* touching an LLM—never spend tokens or probabilistic prose on formatting or syntax errors [4].
2. **AST Context Expansion Beyond `+-` Diff Hunks (`Tree-sitter` [6]):** A raw `git diff` is context-starved! Parse modified files with `Tree-sitter` [6] to pull the **enclosing function/class body**, **type/interface definitions**, and **1-hop callers/callees** across the repo so the model sees actual pre-conditions, locks, and null guards.
3. **Two-Stage Generator -> Critic Precision Gate (`Confidence >= 0.85`) [4, 5]:**
   - **Pass 1 (Bug Hunter):** Proposes candidate defects (`concurrency`, `authz`, `resource leak`, `off-by-one`) with exact `file:start_line-end_line` spans.
   - **Pass 2 (Skeptical Critic):** Attempts to *disprove* each candidate against the expanded AST context and repo conventions—**dropping `70%–85%` of low-confidence/style nits** so a typical PR receives **`0–3` high-signal comments** [4, 5]!
4. **Incremental Hunk Hashing & Implicit Acceptance Telemetry:** Key reviewed hunks by `SHA256(file_path + ast_symbol + normalized_hunk)` so a `git push --force` re-reviews **only newly changed hunks** (never re-posting dismissed comments!). Measure quality via **Resolved-by-Subsequent-Commit Rate** and **Thumbs-Down / Dismiss Rate (`<10%` SLO)** [4, 5].

:::deepdive Flagship Design 3: Enterprise Multimodal Document & PDF Intelligence (`10M` Docs/Day) | +5 min

**Prompt:** *Design a system ingesting `10M` complex financial/medical PDFs per day (multi-column layouts, merged-cell tables, scanned charts) for cited Q&A and structured JSON extraction [7, 8].*

1. **Why Naive `pdftotext` + `500-Token` Chunking Breaks:** Plain text extraction scrambles two-column reading order, turns financial tables (`2024 | 2025 | YoY%`) into orphaned numbers, and completely drops bar charts and scanned signatures [7, 8].
2. **Complexity-Routed Ingestion Pipeline (`Fast Lane` vs. `VLM Lane`) [7, 8]:**
   - **Page Router (`<5 ms`/page):** Inspect PDF object stream + layout entropy. Route **`70%` clean digital text pages** through fast structural parser (`~20×` cheaper), and route **`30%` table-heavy, chart, or scanned pages** to the **GPU Vision-Language Lane** (`Kafka` batch queue on spot/reserved GPUs) [8].
   - **Dual Representation (`ColPali` Visual Patches + Structured Markdown Tables) [7]:** Index complex pages both via **late-interaction visual patch embeddings (`ColPali` [7])**—which retrieve directly over rendered page images without brittle OCR cascades—and VLM-extracted **HTML/Markdown tables** paired with exact **`(doc_id, page_num, bbox: [x1, y1, x2, y2])`** coordinates!
3. **Visual Bounding-Box Provenance:** Every extracted number or RAG claim returns its `(page, bbox)` coordinates so the UI highlights the exact table cell on the rendered PDF—allowing human auditors to verify `$14.2M` in `1 second` [7, 8].

:::

:::deepdive Option Comparison, Half-Budget Cuts & Interview Traps Across All Three | +5 min

| System | What to Cut First If Budget Halves | #1 Tempting Trap Answer to Avoid |
| :--- | :--- | :--- |
| **1. Web Answer Engine** | Serve `evergreen` queries (`~60%` of traffic) from quantized `8B/70B FP8` open models + aggressive semantic/exact URL cache; keep frontier synthesis for complex multi-hop queries [8]. | *"Fetch URLs live on every user query without a tiered index or `singleflight` coalescing"* (melts under viral news spikes [2]). |
| **2. AI PR Code Reviewer** | Skip LLM review on lockfiles, generated code, docs-only PRs, and draft WIP pushes until marked *Ready for Review* (cuts token spend **`~65%`**!) [5, 8]. | *"Optimize for high recall so we catch every possible nit"* (destroys precision, breaches Tricorder's `<10%` noise bar, and gets muted [4]). |
| **3. Multimodal Doc Pipeline** | Run `VLM / ColPali` **only** on pages where the layout detector spots tables, figures, or low OCR confidence—never render `100%` of plain-text pages through vision encoders [7, 8]. | *"Run synchronous VLM OCR inside the user's upload HTTP request"* (a `200-page` PDF takes minutes—always ingest asynchronously via Kafka + page-level progress state [8]). |

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** A **Web Answer Engine** is a live newsroom research desk with a wire-service ticker (`<60s` RAM tier) and fact-checker (`ALCE`); an **AI PR Reviewer** is a Staff Engineer who reads callers before commenting and stays silent when everything is clean (`Tricorder` rule); a **Multimodal Doc Pipeline** is an auditor who uses a magnifying glass (`VLM`) only on dense balance-sheet tables rather than plain cover letters.
- **Where the analogy breaks:** A human newsroom researcher naturally ignores invisible white-on-white webpage text; an LLM scraper will execute hidden prompt injections inside scraped DOM nodes unless sanitized and isolated from user credentials [3]!
- **Real production system:** **Perplexity / SearchGPT** (tiered fresh/warm search + inline citations), **GitHub Copilot Code Review / Meta CodeCompose / Google Tricorder** (AST-expanded, precision-gated code review), and **`ColPali` / Azure & AWS Document Intelligence** (layout-routed bbox provenance) [1, 4, 5, 7].

---

### Quick Self-Check

<details>
<summary><strong>Q1: What happens in a Web-Scale AI Answer Engine when breaking news hits and 200,000 users ask the exact same query within 10 seconds?</strong></summary>
<p><strong>Answer:</strong> Without request coalescing, 200,000 duplicate retrieval + LLM streams stampede the index and GPUs. Using <strong><code>singleflight</code> in-flight coalescing</strong> plus a short-TTL (<code>15–30s</code>) hot-query cache executes <strong>one</strong> search-and-synthesis pipeline and fans the streamed cited tokens out to all waiting subscribers.</p>
</details>

<details>
<summary><strong>Q2: Why does feeding only the raw <code>git diff</code> into an LLM produce high false-positive rates in AI PR Code Review, and what is the Tricorder noise threshold?</strong></summary>
<p><strong>Answer:</strong> Raw diff hunks omit enclosing function bodies, type contracts, null checks, and callers in other files, causing hallucinated bugs. Google's Tricorder research showed developer tools must stay <strong>below ~10% "not-useful" (false-positive) rate</strong>—achieved via Tree-sitter AST context expansion plus a skeptical Critic confidence gate.</p>
</details>

<details>
<summary><strong>Q3: On a <code>git push --force</code> updating 1 file in a 20-file PR, how do you prevent an AI PR Reviewer from re-posting comments developers already dismissed?</strong></summary>
<p><strong>Answer:</strong> Fingerprint each reviewed hunk by <code>SHA256(file_path + ast_symbol + normalized_diff_hunk)</code> and store dismissed/posted fingerprints per PR—re-evaluating only modified AST hunks on subsequent pushes.</p>
</details>

<details>
<summary><strong>Q4: Why do production Document Intelligence pipelines route pages selectively between a fast digital-text parser and a Vision-Language / <code>ColPali</code> GPU lane?</strong></summary>
<p><strong>Answer:</strong> Roughly <code>60–75%</code> of enterprise PDF pages are clean single-column digital text that parses in milliseconds on CPU, while multi-column tables, charts, and scans require vision-language layout grounding and <code>(page, bbox)</code> coordinates—selective routing cuts GPU vision spend by <code>~3×</code> without losing table accuracy.</p>
</details>

---

### Sources & References
- **[1]** Tianyu Gao et al., *Enabling Large Language Models to Generate Text with Citations (`ALCE`)* (EMNLP 2023) — [arxiv.org/abs/2305.14627](https://arxiv.org/abs/2305.14627)
- **[2]** Go Extended Standard Library, *`golang.org/x/sync/singleflight` — Duplicate Call Suppression & Stampede Coalescing* — [pkg.go.dev/golang.org/x/sync/singleflight](https://pkg.go.dev/golang.org/x/sync/singleflight)
- **[3]** Kai Greshake et al., *Not What You've Signed Up For: Indirect Prompt Injection in Web-Integrated LLMs* (AISec 2023) — [arxiv.org/abs/2302.12173](https://arxiv.org/abs/2302.12173)
- **[4]** Caitlin Sadowski et al. (Google), *Tricorder: Building a Program Analysis Ecosystem* (CACM 2018) — [research.google/pubs/tricorder](https://research.google/pubs/tricorder-building-a-program-analysis-ecosystem/)
- **[5]** Vijayaraghavan Murali et al. (Meta), *AI-assisted Code Authoring at Scale (`CodeCompose`)* (ESEC/FSE 2023) — [arxiv.org/abs/2305.12050](https://arxiv.org/abs/2305.12050)
- **[6]** Max Brunsfeld et al., *Tree-sitter: Incremental AST Parsing for Source Code Context* — [tree-sitter.github.io/tree-sitter](https://tree-sitter.github.io/tree-sitter/)
- **[7]** Manuel Faysse et al., *`ColPali`: Efficient Document Retrieval with Vision Language Models* (ICLR 2025) — [arxiv.org/abs/2407.01449](https://arxiv.org/abs/2407.01449)
- **[8]** Rohit Ghumare et al., *AI Engineering from Scratch — Production AI System Design & Multimodal Pipelines* — [aiengineeringfromscratch.com/interviews](https://aiengineeringfromscratch.com/interviews)
