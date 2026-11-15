# Chapter 24: LLM Inference & GPU Serving Internals (Disaggregated Prefill/Decode, EAGLE-3 & Economics)

*Part V · LLM Internals, Harnesses & Multimodal · 9 min core · 19 min with deep dives*

When a backend team boasts *"Our GPU cluster hits 15,000 tokens per second!"* while `40%` of users wait `3.5 seconds` for their first word to appear, they fell into the **Throughput vs. Goodput Trap** [9].

Serving an LLM is nothing like serving a stateless REST microservice—because every single request splits into **two completely different hardware regimes** inside the same GPU: a **compute-bound Prefill phase** followed by an **HBM memory-bandwidth-bound Decode phase** [2, 3, 4].

Understanding how modern engines (`vLLM`, `SGLang`, `TensorRT-LLM`) schedule, disaggregate, speculate, and quantize those two phases is what separates hand-wavy API wrappers from Senior AI Infrastructure design [1, 2, 4, 8].

{{diagram:12-llm-inference-serving.excalidraw}}

---

### 1) Roofline Physics: Compute-Bound Prefill vs. Memory-Bound Decode (`Goodput`)

Follow a `70B`-parameter model quantized to `FP8` (`~70 GB` of weights) on an `H100` (`~3.35 TB/s` HBM3 bandwidth) [4, 9]:
1. **Prefill (`TTFT` — Compute-Bound):** All `4,096` prompt tokens multiply against the weight matrices in parallel (`Matrix × Matrix` GEMMs). Tensor Cores run near `100%` utilization; latency scales roughly linearly (or super-linearly for attention) with **input prompt length**.
2. **Decode (`TPOT` / `ITL` — Memory-Bandwidth-Bound):** Autoregressive generation emits **one token at a time** per sequence. At `batch = 1`, generating *one* token still forces the GPU to stream all **`70 GB` of model weights** from HBM into SRAM (`Matrix × Vector`)! Even at theoretical peak bandwidth (`3,350 GB/s ÷ 70 GB`), a single GPU cannot exceed **`~47 tokens/sec` (`~21 ms` per token)** while `98%` of its Tensor Core FLOPs sit idle [4, 6]!
3. **Continuous Batching (`Orca`) + `PagedAttention` (`vLLM`) [1, 2]:**
   - Static batching padded every request to the longest sequence and waited for the slowest answer to finish. **Iteration-level Continuous Batching** inserts new requests and evicts finished ones on *every decode step*, amortizing that `70 GB` weight read across `64–128` concurrent sequences [1].
   - **`PagedAttention`** stores KV tensors in non-contiguous `16-token` virtual-memory blocks (eliminating `60–80%` contiguous KV fragmentation so `3–4×` larger batches fit in HBM) [2], while **`RadixAttention` (`SGLang`)** retains evicted KV blocks in an LRU radix tree for cross-turn prefix reuse [8].
4. **Optimize for `Goodput`, Never Raw Throughput [3, 4, 9]:**
   - Define **`Goodput`** as the rate (or share) of requests simultaneously satisfying *every* user SLO—e.g., **`TTFT <= 500 ms` AND `TPOT <= 15 ms` AND `E2E <= 2.5 s`** [4, 9]. Cranking batch size to `512` maximizes aggregate `tokens/sec` while pushing `p99 TPOT` above `60 ms` and collapsing Goodput toward `0%`!

---

### 2) Chunked Prefill vs. Disaggregated Prefill/Decode (`DistServe` / `Dynamo`)

What happens on a co-located GPU when 64 users are smoothly streaming decode tokens (`7 ms` `TPOT`) and User 65 submits a **`32,000-token` RAG prompt**?
The `32k` prefill monopolizes the GPU for **`~800 ms`**, freezing all 64 active streams mid-sentence (**generation stall**) [3, 4]! Production stacks solve prefill–decode interference in two stages:

| Architecture | How It Works | What It Improves | Cost & Failure Trade-Off |
| :--- | :--- | :--- | :--- |
| **1. Chunked Prefill** *(`Sarathi-Serve`)* [3] | Slices the `32k` prompt into fixed `2,048-token` chunks and piggybacks one prefill chunk alongside running decode tokens per step. | Bounds `TPOT` spikes (`~7 ms -> ~15 ms` instead of `800 ms`) on a single unified GPU pool [3]. | Decode tokens still share step time with prefill chunks; long prompts pay slightly higher `TTFT`. |
| **2. Disaggregated Prefill / Decode** *(`DistServe`, `Dynamo`, `llm-d`)* [4, 9] | Routes prompts to a **Compute-Tuned Prefill Pool**, transfers `FP8` KV blocks over **RDMA / InfiniBand (`NIXL`)**, and streams tokens from a **Bandwidth-Tuned Decode Pool** [4]. | Zero prefill-on-decode stalls; independent autoscaling & parallelism (`TP` for prefill, large batch/`EP` for decode) -> **`2×–4.5×` higher Goodput** under tight SLOs [4]! | **Does NOT magically raise raw single-GPU FLOPs**—costs RDMA bandwidth + KV-transfer failure handling (must configure fallback re-prefill if transfer drops) [9]. |

:::deepdive Speculative Decoding (`EAGLE-3`) Math & Why High Batch Size Kills Speculation | +5 min

1. **How Speculative Decoding Exploits Idle Decode Compute (`Leviathan et al.` & `EAGLE-3`) [5, 6]:**
   - Because low-batch decode is **memory-bandwidth-bound**, verifying `K + 1` tokens in parallel inside one target forward pass takes almost the same HBM read time as generating `1` token (`70 GB` weights read once!) [5].
   - A tiny draft mechanism proposes `K` tokens (`e.g., K = 5`); the target model scores all `K` in **one forward pass** via rejection sampling (**100% mathematically lossless** to the target distribution!) [5].
   - Whereas standalone `1B` draft models achieve low acceptance (`α ≈ 0.4`), **`EAGLE-3`** attaches a lightweight autoregressive head directly to fused multi-layer **target hidden states**, lifting acceptance rate **`α` to `0.65–0.80`** [6].
2. **The Break-Even Equation & The High-Concurrency Trap [6, 9]:**
   - Expected tokens emitted per step is `1 + K · α`, giving wall-clock speedup **`Speedup ≈ (1 + K · α) / (1 + ε)`** where `ε` is draft + verification compute overhead [6, 9].
   - **Critical Interview Trap:** Speculative decoding is **NOT a free universal speedup**! As concurrent batch size climbs (`batch >= 64–128`), `K × batch` verification tokens push the target GPU from *memory-bound* back into the **compute-bound** regime (exploding `ε`), and whenever domain shift drops **`α < 0.55`**, rejected draft tokens waste FLOPs and **degrade `p99` latency** [6, 9]. Gate speculative decoding dynamically on live `queue_depth` and measured domain `α`!

:::

---

### 3) Production Quantization Zoo & Managed API vs. Self-Hosted GPU Break-Even

1. **Matching Quantization Format to Hardware & Workload [7, 9]:**
   - **`FP8` (`W8A8` + `FP8` KV Cache):** Datacenter default on Hopper (`H100`/`H200`) and Blackwell (`B200`)—halves `70B` weights from `140 GB -> 70 GB` *and* halves KV-cache footprint with near-zero reasoning degradation [9].
   - **`AWQ` (`INT4` Activation-Aware Weight-Only, Lin et al.) [7]:** Protects the `~1%` most salient activation channels to shrink `70B` weights to **`~35 GB`** (fitting on a single `80 GB` GPU!) with fast `Marlin` CUDA kernels. **Trap:** Weight-only `INT4` leaves the **KV cache in `FP16` (`20–30 GB` at `batch=128`)** unless you *also* enable `FP8`/`INT8` KV quantization—and always calibrate on **in-domain prompts** and re-run your full eval ship-gate post-quantization [7, 9]!
   - **`GPTQ` (`INT4` + Marlin):** Preferred in `vLLM` when serving **dozens of `LoRA` adapters** atop a `4-bit` base [9].
   - **`GGUF` (`Q4_K_M` / `Q5_K_M`):** Optimized for **CPU & Apple Silicon (`llama.cpp`)** edge inference—*never* use `GGUF` on datacenter GPUs (`3×–7×` slower than `FP8`/`Marlin-AWQ`) [9].

:::deepdive Managed Token API vs. Self-Hosted GPUs vs. Custom Silicon Break-Even Math | +5 min

When an interviewer asks *"Should we call a Managed Token API, rent Serverless GPUs, or run our own `vLLM`/`SGLang` H100 cluster?"*, compute **effective cost per million goodput tokens** across traffic shapes [9]:

| Serving Tier | Billing Model | Wins When... | Loses When... |
| :--- | :--- | :--- | :--- |
| **1. Managed Token API / Batch API** *(OpenAI, Anthropic, Bedrock, Fireworks)* | `$/1M` input & output tokens (`50%` off for `24h` async Batch lane) | **Spiky / bursty traffic (`<35%` avg GPU duty cycle)**, frontier closed models, or small teams avoiding GPU SRE overhead [9]. | Sustained `24/7` high-volume open-weight traffic (`>5B–10B` tokens/day) where token margins exceed raw GPU cost `3×`. |
| **2. Dedicated `vLLM` / `SGLang` GPU Pool** *(H100 / B200 on K8s)* | `$/GPU-hour` (`~$2–$3/hr` reserved H100) | **Steady `>45–50%` GPU utilization**, strict VPC data residency, custom `S-LoRA` pools, or long-prefix `RadixAttention` workloads [8, 9]. | Diurnal `10×` peak-to-trough swings without autoscaling (idle GPUs burn cash overnight) or slow `5-min` container cold starts [9]. |
| **3. Custom SRAM Silicon** *(Groq `LPU`, Cerebras `WSE`)* | Premium `$/1M` tokens, weights pinned in on-chip SRAM | **Ultra-low `TPOT` (`<2–5 ms/tok`, `300–800+ tok/s`)** for real-time voice cascades or interactive code autocomplete [9]. | Massive batch offline throughput where HBM GPU clusters deliver lower `$/token`. |

**Worked Break-Even Sanity Check:** Suppose 2 reserved `H100`s (`$5.00/hr` = **`$3,600/month`**) sustain `2,500 output tok/s` at `50%` average daily utilization (`2,500 × 0.50 × 86,400 × 30 ≈ 3.24B tokens/month` -> **`~$1.11 / 1M tokens`**). If a managed API charges `$0.80 / 1M` tokens, **the API is cheaper** (especially once SRE + failover capacity are counted)! Self-hosting only wins when sustained token volume or specialized prefix/LoRA caching pushes effective GPU cost well below API rates [9].

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **Prefill** is loading 50 passengers onto a train at the station (door width / compute bound); **Decode** is driving the entire 200-ton locomotive down the track even if only 1 passenger is aboard (fuel/bandwidth bound—which is why **Continuous Batching** packs 80 passengers per trip!). **Disaggregation** separates busy boarding platforms from express highway lanes.
- **Where the analogy breaks:** Moving passengers between platforms is free; moving a `32k-token` `KV` cache between a Prefill GPU and a Decode GPU ships **gigabytes of tensors** across the network—without `RDMA`/`InfiniBand` (`NIXL`) or `FP8` KV compression, network transfer stalls erase the disaggregation win [4, 9].
- **Real production system:** **`vLLM`**, **`SGLang` (`RadixAttention`)**, and **`NVIDIA Dynamo` / `llm-d`** run chunked prefill, `EAGLE-3` speculation, and RDMA prefill–decode disaggregation across production GPU fleets [2, 4, 6, 8, 9].

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why is LLM Prefill compute-bound while low-batch Decode is HBM memory-bandwidth-bound?</strong></summary>
<p><strong>Answer:</strong> Prefill processes all prompt tokens in parallel (<code>Matrix × Matrix</code> GEMMs), saturating GPU Tensor Cores. Autoregressive Decode generates one token per sequence per step, forcing the GPU to read the entire model weight footprint from HBM for just a tiny <code>Matrix × Vector</code> step unless amortized across a large continuous batch.</p>
</details>

<details>
<summary><strong>Q2: Does disaggregating Prefill and Decode onto separate GPU pools increase raw single-GPU FLOP throughput? Why do production clusters do it?</strong></summary>
<p><strong>Answer:</strong> No—it adds KV-cache network transfer overhead. Production clusters disaggregate to eliminate long-prefill stalls on active decode streams and independently tune parallelism and batch sizes for <code>TTFT</code> vs. <code>TPOT</code>, multiplying <strong>SLO Goodput</strong>.</p>
</details>

<details>
<summary><strong>Q3: Why can turning on <code>EAGLE-3</code> speculative decoding degrade latency when concurrent batch size climbs to 128 or domain acceptance <code>α</code> drops below ~0.55?</strong></summary>
<p><strong>Answer:</strong> Speculative decoding relies on spare compute during memory-bound decode. At large batch sizes (<code>K × 128</code> tokens), verification pushes the target GPU into the compute-bound regime, and low acceptance <code>α</code> wastes forward-pass FLOPs on rejected draft tokens.</p>
</details>

<details>
<summary><strong>Q4: A team quantizes a 70B model's weights to 4-bit AWQ (~35 GB) for an 80 GB GPU, yet still OOMs at 128 concurrent 4k-token users. What did they forget?</strong></summary>
<p><strong>Answer:</strong> Weight-only <code>INT4</code> quantization does not shrink the <strong>KV cache</strong>! At 128 concurrent sequences, an unquantized <code>FP16</code> KV cache plus activation workspaces consumes <code>30–45+ GB</code>—requiring PagedAttention admission caps and <code>FP8</code> KV-cache quantization.</p>
</details>

---

### Sources & References
- **[1]** Gyeong-In Yu et al., *Orca: A Distributed Serving System for Transformer-Based Generative Models (Continuous Batching)* (USENIX OSDI 2022) — [usenix.org/conference/osdi22/presentation/yu](https://www.usenix.org/conference/osdi22/presentation/yu)
- **[2]** Woosuk Kwon et al., *Efficient Memory Management for Large Language Model Serving with PagedAttention (vLLM)* (ACM SOSP 2023) — [arxiv.org/abs/2309.06180](https://arxiv.org/abs/2309.06180)
- **[3]** Amey Agrawal et al., *Taming Throughput-Latency Tradeoff in LLM Inference with Sarathi-Serve (Chunked Prefill)* (USENIX OSDI 2024) — [arxiv.org/abs/2403.02310](https://arxiv.org/abs/2403.02310)
- **[4]** Yinmin Zhong et al., *DistServe: Disaggregating Prefill and Decoding for Goodput-Optimized Large Language Model Serving* (USENIX OSDI 2024) — [arxiv.org/abs/2401.09670](https://arxiv.org/abs/2401.09670)
- **[5]** Yaniv Leviathan, Matan Kalman & Yossi Matias, *Fast Inference from Transformers via Speculative Decoding* (ICML 2023) — [arxiv.org/abs/2211.17192](https://arxiv.org/abs/2211.17192)
- **[6]** Yuhui Li et al., *EAGLE-3: Scaling up Inference Acceleration of Large Language Models via Training-Time Test* (2025) — [arxiv.org/abs/2503.01840](https://arxiv.org/abs/2503.01840)
- **[7]** Ji Lin et al., *AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration* (MLSys 2024) — [arxiv.org/abs/2306.00978](https://arxiv.org/abs/2306.00978)
- **[8]** Lianmin Zheng et al., *SGLang: Efficient Execution of Structured Language Model Programs (RadixAttention)* (NeurIPS 2024) — [arxiv.org/abs/2312.07104](https://arxiv.org/abs/2312.07104)
- **[9]** Rohit Ghumare et al., *AI Engineering from Scratch — Phase 17 & Inference Serving Interview Bank* — [aiengineeringfromscratch.com/interviews](https://aiengineeringfromscratch.com/interviews)
