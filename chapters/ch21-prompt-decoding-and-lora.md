# Chapter 21: Prompt Conditioning, Constrained Decoding (FSM/CFG) & LoRA/QLoRA Math

*Part V · LLM Internals, Harnesses & Multimodal · 9 min core · 19 min with deep dives*

Ask an LLM `"Extract the product, price, and stock status as JSON"` and `90%` of the time it works.

The other `10%` of the time—usually at 3:00 AM under peak load—it replies `"Sure! Here is the JSON: {...}"` wrapped in markdown fences, drops a closing brace on token truncation, or invents `"inStock": "yes"` instead of a boolean, crashing your downstream microservice [1, 3].

Closing the gap between **probabilistic token generation** and **deterministic software interfaces** requires mastering four layers below high-level frameworks: **prompt distribution conditioning**, **token-level constrained decoding**, **streamed parallel tool-call reassembly**, and **parameter-efficient fine-tuning (`LoRA` / `QLoRA`)** [1, 3, 6, 8].

{{diagram:09-prompt-decoding-lora.excalidraw}}

---

### 1) Prompt Anatomy as Probability-Distribution Conditioning

An LLM is trained over everything from peer-reviewed distributed-systems papers to zero-upvote forum posts. A prompt is not a magic incantation—it is a **prior that narrows conditional next-token probability `P(y_t | x, y_<t)`** onto the exact slice of behavior, format, and domain rigor you want [1]:

1. **Separate the Three Message Slots:**
   - **System Instruction:** Highest-priority behavioral contract, role invariants, and refusal/scope rules. Keep rules crisp (`<500–800` tokens) and free of internal contradictions (*"Be exhaustive"* + *"Stay under 50 words"*) so compliance does not degrade [1].
   - **User Turn + XML Data Delimiters:** Wrap variable or untrusted inputs inside explicit tags (`<document>`, `<schema>`, `<examples>`) rather than mixing instructions and raw text in one paragraph [1].
   - **Assistant Prefill / Output Contract:** Place immutable instructions at the very start (preserving Chapter 14's GPU KV prefix cache) and re-anchor the exact output contract at the very end of the prompt to counter U-shaped **Lost-in-the-Middle** attention decay [1, 2].
2. **Constraint Taxonomy & Sampling Hygiene (`temperature` XOR `top_p`):**
   - Pair **negative constraints** (*"Do NOT invent fields missing from `<document>`"*), **positive invariants** (*"Cite chunk IDs on every metric"*), and **conditional fallbacks** (*"If input is ambiguous, emit `status: needs_clarification`"*).
   - Set `temperature = 0.0` for extraction, classification, routing, and code; `0.3` for analytical synthesis; `0.7–1.0` for creative ideation. **Never tune `temperature` and `top_p` simultaneously**—truncating nucleus probability mass after sharpening logits produces brittle, unpredictable sampling [1].

---

### 2) The Structured Output Spectrum & Constrained Decoding (`FSM` / `CFG`)

Why does `"Respond only in JSON"` fail `5%–15%` of the time? Because at every decode step, the model samples from `100,000+` vocabulary tokens—and after emitting `{"price":`, thousands of English words have non-zero probability unless masked out at the decoder level [3, 4]:

| Level | Mechanism | Schema Guarantee | Production Trade-Off |
| :--- | :--- | :--- | :--- |
| **1. Prompt-Only** | `"Return valid JSON matching..."` | **None (`~85–92%`)** | Fails on markdown fences, preambles, trailing commas, and smaller models [1]. |
| **2. JSON Mode** | `response_format: json_object` | **Valid syntax only** | Parses as JSON, but keys may be missing, renamed, or wrong types [1, 5]. |
| **3. Validate + Retry** | Pydantic / Zod parse -> feed validation error back | **High (after `1–3` retries)** | Multiplies tail latency (`2×–3×`) and token cost whenever validation trips [1]. |
| **4. Constrained Decoding** | **JSON Schema (`2020-12`) -> FSM / CFG logit mask** (`Outlines`, `XGrammar`, Strict Mode) | **`100%` syntactic & schema compliance in `1` pass** | Zero retry latency; requires handling `length` truncation & typed `refusal` [3, 4, 5]. |

**How Constrained Decoding Works Under the Hood (`Outlines` & `XGrammar`) [3, 4]:**
1. Ahead of inference, the engine compiles your **JSON Schema** into a **Deterministic Finite Automaton (`FSM`)** for regular fields or a **Pushdown Automaton / Context-Free Grammar (`CFG`)** for nested recursive objects, pre-indexing valid token transitions across the model's `128k` subword vocabulary [3, 4].
2. During each `10–25 ms` decode step, a `<50 µs` bitmask lookup sets the logit of every schema-violating token to **`-∞` prior to `softmax`**—making invalid JSON mathematically un-sampleable without hurting throughput [4]!
3. **Three Branches Every Caller Must Still Handle [5]:** Even under strict grammar masking, always inspect (a) **`parsed` payload**, (b) **`finish_reason == "length"`** (output hit `max_tokens` mid-object), and (c) **typed `refusal`** (safety policy declined the request outside the target schema).

:::deepdive Parallel Tool Calls, Streamed Argument Reassembly & Cross-Provider Traps | +5 min

1. **Collapsing Fan-Out Latency with Parallel Tool Calls [5, 6, 7]:**
   - Answering *"Compare latency in `us-east`, `eu-west`, and `ap-south`"* via serial ReAct takes `3` LLM turns + `3` sequential tool RTTs (`~4.2s`). With parallel tool calling enabled, the model emits **all `3` call objects in a single turn**, your host runs them via `asyncio.gather`, and wall-clock time drops to `max(t_1, t_2, t_3)`—cutting fan-out latency by **`60%–70%`** [6].
   - **When You MUST Disable Parallel Calls (`parallel_tool_calls: false`):** Whenever tools have **stateful ordering dependencies** (`create_branch` before `commit_file`), mutate shared rows, or hit strict downstream concurrency caps [5, 6, 7].
2. **The Streamed Partial-JSON & ID-Correlation Trap [5, 6, 7]:**
   - Over streaming SSE, arguments for `3` concurrent calls arrive as interleaved partial strings (`delta.tool_calls[index].function.arguments` on OpenAI [5] or `input_json_delta` blocks keyed by `tool_use_id` on Anthropic [7]).
   - **Never call `json.loads()` on partial stream chunks!** Maintain an isolated string accumulator per `(index, tool_call_id)`, parse JSON **only** on `finish_reason == "tool_calls"` / `content_block_stop`, and attach the exact `tool_call_id` to every `tool` result message so out-of-order completions correlate unambiguously [6].

:::

---

### 3) Prompting vs. RAG vs. Fine-Tuning — And Exact `LoRA` / `QLoRA` Math

Reach for the right customization lever before touching model weights [1, 8]:
- **Prompting + Few-Shot:** Task rules, formatting, and reasoning scaffolds you can specify in `<2,000` tokens.
- **RAG:** Volatile, factual, or ACL-scoped enterprise knowledge requiring freshness and source citations.
- **Fine-Tuning (`LoRA` / `QLoRA`):** Consistent domain style/taxonomy, ultra-compact prompts (dropping `3,000` few-shot tokens per call), or **distilling a frontier planner/classifier into a cheap, `15 ms` `8B` model** [1, 8].

**Why Full Fine-Tuning Blows Up VRAM (`~56 GB` for `8B`):**
Updating all `8B` parameters in `FP16/BF16` requires `16 GB` (weights) + `16 GB` (gradients) + `32 GB` (`FP32` Adam momentum & variance states) ≈ **`64 GB` VRAM** *before* batch activations—and risks **catastrophic forgetting** of general reasoning [8, 9].

**`LoRA` (*Low-Rank Adaptation*, Hu et al.) & `QLoRA` (*4-bit NF4*, Dettmers et al.) [8, 9]:**
- Freeze pretrained weight matrix `W (d × d)` and inject two rank-`r` adapter matrices (`A` of shape `r × d`, `B` of shape `d × r` with `r << d`, typically `r = 8, 16, 32`):
  `y = Wx + (α / r) · B · A · x`
- On a `4096 × 4096` projection (`16,777,216` params), rank `r = 16` trains only `2 × 4096 × 16 = 131,072` params (**`0.78%` of weights!**). Initialize `A ~ N(0, σ²)` and **`B = 0`** so `(α / r) · B · A = 0` at Step 0 [8].
- **`QLoRA`** quantizes frozen `W` into information-theoretically optimal **4-bit NormalFloat (`NF4`)** (`~4 GB` for `8B` weights) with double quantization and paged optimizers while keeping tiny `BF16` LoRA adapters trainable—fitting an `8B` fine-tune inside **`~6 GB` VRAM** at near-identical quality [9]!

:::deepdive Serving LoRA at Scale (Merged Weights vs. S-LoRA) & Matryoshka Embeddings | +5 min

1. **Zero-Latency Adapter Merge vs. Multi-Tenant `S-LoRA` Pool [8, 10]:**
   - **Single production model:** Offline-compute `W_merged = W + (α / r) · B · A` (dequantizing `NF4` `W` to `BF16` first so 4-bit rounding does not crush small updates) and serve with **zero extra inference latency (`0 ms`)** [8, 9].
   - **Hundreds of per-tenant adapters (`S-LoRA` in `vLLM`) [10]:** Keep **one shared frozen base model** (`16 GB`) in GPU HBM, batch the base `Wx` GEMM across all concurrent requests, and page `~50 MB` tenant-specific `(B_i, A_i)` adapters dynamically from unified memory via custom CUDA kernels—serving **thousands of custom models on a single GPU** [10].
2. **Bonus Vector-RAM Lever — Matryoshka Representation Learning (`MRL`) [11]:**
   - Modern embedding models (`text-embedding-3-large`, `Nomic`, `Qwen3-Embedding`) train nested prefixes (`d = 64, 128, 256, 512, ..., 3072`) simultaneously so early coordinates carry coarse semantic signal [11]. Truncating + L2-renormalizing `3072-d` embeddings down to **`512-d`** cuts HNSW RAM and network I/O by **`6×`** while retaining `97%+` of full-dimension retrieval Recall@10 [1, 11]!

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **Prompting** is giving a chef a detailed recipe card; **Constrained Decoding** is pouring batter into a cast-iron waffle mold so it physically cannot bake into any other shape; **`LoRA`** is bolting a lightweight precision jig onto a factory press instead of melting and recasting the 10-ton steel machine.
- **Where the analogy breaks:** A waffle mold guarantees **shape**, not **taste**! Constrained decoding guarantees `{"diagnosis": string, "confidence": float}` parses `100%` of the time, but cannot stop the model from putting a hallucinated diagnosis inside that valid string—you still need grounded context and semantic guardrails [3, 5].
- **Real production system:** **OpenAI Structured Outputs**, **`vLLM` (`XGrammar` + `S-LoRA`)**, and **HuggingFace PEFT / bitsandbytes (`QLoRA`)** power grammar-guaranteed tool calls and multi-tenant adapter serving in production [4, 5, 9, 10].

---

### Quick Self-Check

<details>
<summary><strong>Q1: How does token-level Constrained Decoding guarantee 100% JSON Schema compliance without post-hoc retry loops?</strong></summary>
<p><strong>Answer:</strong> It compiles the JSON Schema into a Finite State Machine (FSM) or Context-Free Grammar (CFG) over the tokenizer vocabulary and masks every syntactically or type-invalid next token to <code>-∞</code> logit before <code>softmax</code> at each decode step.</p>
</details>

<details>
<summary><strong>Q2: What breaks if your streaming SSE client calls <code>json.loads()</code> as tool-call deltas arrive during parallel function calling?</strong></summary>
<p><strong>Answer:</strong> Streamed tool arguments arrive as partial string slices interleaved across multiple concurrent calls. Parsing early throws syntax errors; you must buffer chunks per <code>(index, tool_call_id)</code> until the call block completes, then parse once and return results tagged with each <code>tool_call_id</code>.</p>
</details>

<details>
<summary><strong>Q3: In LoRA (<code>y = Wx + (α / r) · B · A · x</code>), why is <code>A</code> initialized randomly while <code>B</code> is initialized to all zeros?</strong></summary>
<p><strong>Answer:</strong> Setting <code>B = 0</code> makes <code>B · A = 0</code> on Step 0 so the model starts training from the exact pretrained base model distribution without injecting random initial noise, while non-zero <code>A</code> ensures non-zero gradients flow into <code>B</code> on the first backward pass.</p>
</details>

<details>
<summary><strong>Q4: Why does full fine-tuning an 8B model take ~56–64 GB of GPU VRAM whereas 4-bit QLoRA fits in ~6 GB?</strong></summary>
<p><strong>Answer:</strong> Full FP16 fine-tuning stores <code>16 GB</code> weights, <code>16 GB</code> full gradients, and <code>32 GB</code> FP32 Adam optimizer states across all 8B parameters. QLoRA freezes base weights in 4-bit NF4 (<code>~4 GB</code>) and stores gradients and Adam states only for the <code>&lt;1%</code> trainable LoRA adapter weights.</p>
</details>

---

### Sources & References
- **[1]** Rohit Ghumare et al., *AI Engineering from Scratch — Phase 11: Prompt Engineering, Structured Outputs, Embeddings & LoRA* — [aiengineeringfromscratch.com/learn/llm-engineering/prompt-engineering](https://aiengineeringfromscratch.com/learn/llm-engineering/prompt-engineering)
- **[2]** Nelson F. Liu et al., *Lost in the Middle: How Language Models Use Long Contexts* (TACL 2024) — [arxiv.org/abs/2307.03172](https://arxiv.org/abs/2307.03172)
- **[3]** Brandon T. Willard & Rémi Louf, *Efficient Guided Generation for Large Language Models (Outlines FSM)* (2023) — [arxiv.org/abs/2307.09702](https://arxiv.org/abs/2307.09702)
- **[4]** Yixin Dong et al., *XGrammar: Flexible and Efficient Structured Generation Engine for Large Language Models* (2024) — [arxiv.org/abs/2411.15100](https://arxiv.org/abs/2411.15100)
- **[5]** OpenAI Developers, *Function Calling & Structured Outputs Guide* — [platform.openai.com/docs/guides/function-calling](https://platform.openai.com/docs/guides/function-calling)
- **[6]** Rohit Ghumare et al., *AI Engineering from Scratch — Phase 13: The Tool Interface & Parallel Streaming Tool Calls* — [aiengineeringfromscratch.com/learn/tools-and-protocols/the-tool-interface](https://aiengineeringfromscratch.com/learn/tools-and-protocols/the-tool-interface)
- **[7]** Anthropic Documentation, *Tool Use Overview & Parallel Tool Execution* — [platform.claude.com/docs/en/agents-and-tools/tool-use/overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- **[8]** Edward J. Hu et al., *LoRA: Low-Rank Adaptation of Large Language Models* (ICLR 2022) — [arxiv.org/abs/2106.09685](https://arxiv.org/abs/2106.09685)
- **[9]** Tim Dettmers et al., *QLoRA: Efficient Finetuning of Quantized LLMs* (NeurIPS 2023) — [arxiv.org/abs/2305.14314](https://arxiv.org/abs/2305.14314)
- **[10]** Ying Sheng et al., *S-LoRA: Serving Thousands of Concurrent LoRA Adapters* (MLSys 2024) — [arxiv.org/abs/2311.03285](https://arxiv.org/abs/2311.03285)
- **[11]** Aditya Kusupati et al., *Matryoshka Representation Learning* (NeurIPS 2022) — [arxiv.org/abs/2205.13147](https://arxiv.org/abs/2205.13147)
