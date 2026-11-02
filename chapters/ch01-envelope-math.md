# Chapter 1: Back-of-the-Envelope Math (Or: How Not to Panic at 30,000 QPS)

*Part I · Core Building Blocks · 7 min read*

Imagine you are sitting at a whiteboard. Someone asks you: *"Design a notification system for 100 million daily active users."*

At this exact moment, two different movies can play out in your head.

In Movie A, you immediately start drawing boxes labeled "Microservice," "Load Balancer," and "NoSQL" while secretly hoping nobody asks how many servers you actually need. In Movie B, you pause for 60 seconds, write four numbers on the board, and realize that **one single number—peak writes per second—already eliminates half the databases on earth.**

Back-of-the-envelope math is not about memorizing 47 hardware benchmarks [1]. It is a 60-second sanity check that tells you *where your system will catch fire first*.

---

### 1) The Only Three Time Conversions You Ever Need

Humans think in *days*. Computers crash in *seconds*.

Whenever you see a daily number (like "100 million messages per day"), your first job is to translate **per day** into **per second**. A day has `86,400` seconds (`24 × 60 × 60`), which is annoying to divide in your head. So for back-of-the-envelope estimation, round `86,400` to **`100,000` (`10^5`) seconds per day** [1, 2].

| Daily Volume | Divide by `100,000` | Average Requests / Sec (QPS) | Peak QPS (`3×` to `5×` Average) |
| :--- | :--- | :--- | :--- |
| **1 Million / day** | `1,000,000 / 100,000` | **10 QPS** | **30–50 QPS** (One tiny VM handles this asleep) |
| **100 Million / day** | `100,000,000 / 100,000` | **1,000 QPS** | **3,000–5,000 QPS** (One good Postgres box + cache) |
| **1 Billion / day** | `1,000,000,000 / 100,000` | **10,000 QPS** | **30,000–50,000 QPS** (Needs queueing / sharding) |

Notice the rightmost column: **Peak QPS**. Traffic is never flat; everyone wakes up at 9:00 AM, opens their apps at lunch, or taps a breaking-news alert at the same second. Always multiply your average QPS by **`3×` to `5×`** to get your peak capacity target [2].

---

### 2) How Fast Is a Computer, Really? (Human-Scale Time)

Computer latency numbers look like tiny decimals (`0.5 ns`, `100 µs`, `10 ms`), so our brains lump them all together as "fast."

To see why that is a trap, let us scale **1 nanosecond up to 1 full second** of human time (a mental model popularized by Jeff Dean and Brendan Gregg [3]):

| Operation | Real Computer Time | Scaled to Human Time (`1 ns = 1 sec`) | What Your Architecture Feels |
| :--- | :--- | :--- | :--- |
| **CPU L1 Cache read** | `0.5 ns` | **0.5 seconds** | Reaching for your coffee mug on the desk. |
| **Main RAM read (Redis)** | `100 ns` | **1.5 minutes** | Walking to the kitchen for a snack. |
| **NVMe SSD random read** | `100 µs` (`100,000 ns`) | **1.15 days** | Ordering a package with overnight shipping. |
| **Same-datacenter network hop** | `500 µs` (`0.5 ms`) | **5.8 days** | Waiting a full workweek for a reply. |
| **Cross-continent packet (US ↔ EU)** | `150 ms` | **4.75 years** | Sending a ship across the ocean and waiting half a decade. |

When someone asks *"Why can't we just check the database on disk for every API request at 50,000 QPS?"*, look at the table above. In CPU time, going to RAM (Redis) is a 90-second walk to the kitchen; going across the network to a disk page is a multi-day expedition [3].

---

### 3) Capacity Rules of Thumb for One Commodity Server

When you calculate `30,000 peak QPS`, how do you know if that is big or small? Compare your number against what **one standard cloud server** (`16–32 vCPU`, `64–128 GB RAM`) can comfortably handle before tail latency (`p99`) spikes [1, 2]:

- **Stateless API Gateway / Web Server:** `10,000 – 25,000 QPS` per node.
- **Stateful WebSocket Server (Chat / Live Connections):** `50,000 – 100,000 open idle TCP connections` per node (limited by RAM per socket + file descriptors).
- **Single Relational Database Primary (PostgreSQL / MySQL):** `5,000 – 10,000 simple writes/sec`, or `20,000 – 50,000 indexed point reads/sec` (add read replicas to scale reads; shard or queue to scale writes).
- **Single Redis Instance (In-Memory):** `100,000+ ops/sec` on a single thread [4].
- **Single Kafka Broker:** `50,000 – 100,000+ messages/sec` (`100–200 MB/s` sequential disk throughput) [5].

---

### 4) AI Engineering Math: Tokens, Bandwidth & KV-Cache RAM

When designing AI-enabled backend systems, there is one more calculation that immediately clarifies architecture bottlenecks: **LLM latency and GPU memory math** [6].

- **1 Token** is roughly `0.75` English words (or `4` characters). A 1-page document is ~`500 tokens`.
- **Time To First Token (TTFT):** The "prefill" step where the GPU processes your input prompt in parallel. For a `4,000-token` RAG prompt, TTFT is typically **`300 ms – 800 ms`**.
- **Inter-Token Latency (ITL):** Generating output tokens happens *one token at a time* (autoregressively), limited by GPU memory bandwidth. A fast production model streams at **`40 – 80 tokens/sec`** (`12–25 ms` per token).
- **Why a 300-token answer takes 5 seconds:** `0.5s (TTFT) + (300 tokens / 60 tokens/sec) = 5.5 seconds` total wall-clock time. That is why every interactive AI app **must stream tokens via Server-Sent Events (SSE)** instead of blocking until the entire paragraph is finished [6].

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** Back-of-the-envelope math is like checking whether your sofa fits through the apartment stairwell *before* you hire the moving truck. You do not need millimeter precision; you only need to know whether the doorway is 30 inches wide or 80 inches wide.
- **Where the analogy breaks:** A doorway never changes width based on how many people walk through it. In distributed systems, throughput degrades *non-linearly* once CPU or disk utilization crosses ~70% because of queuing theory (Little's Law and lock contention).
- **Real production system:** **Discord** used back-of-the-envelope math when migrating trillions of messages from Cassandra to ScyllaDB, realizing their hot-partition read latency was dominated by JVM garbage-collection pauses and multi-SSTable disk reads [7].

---

### Quick Self-Check

<details>
<summary><strong>Q1: Your service logs 500 million events per day, and each event is 2 KB. How much average QPS, peak QPS (at 4×), and daily storage do you need?</strong></summary>
<p><strong>Answer:</strong> Average QPS = <code>500,000,000 / 100,000 = 5,000 QPS</code>. Peak QPS (4×) = <code>20,000 QPS</code>. Daily storage = <code>500M × 2 KB = 1,000,000,000 KB ≈ 1 TB/day</code> (or <code>365 TB/year</code> before replication).</p>
</details>

<details>
<summary><strong>Q2: Can a single unsharded PostgreSQL primary comfortably absorb 40,000 heavy transactional writes per second during a flash spike?</strong></summary>
<p><strong>Answer:</strong> No. A single relational primary typically tops out around <code>5,000–10,000</code> transactional writes/sec due to B-Tree page locks, WAL fsyncs, and index maintenance. At 40,000 writes/sec, you must either buffer writes in a log queue (Kafka) or shard writes across multiple database partitions.</p>
</details>

<details>
<summary><strong>Q3: Why does an LLM take 4+ seconds to write a 250-word paragraph even on an H100 GPU cluster?</strong></summary>
<p><strong>Answer:</strong> Because output generation is autoregressive: each token depends on the previous token and requires reading the model weights from GPU HBM memory once per token. At ~60 tokens/sec, 250 words (~330 tokens) takes ~5.5 seconds—which is why SSE streaming is mandatory for UX.</p>
</details>

---

### Sources & References
- **[1]** Alex Xu, *System Design Interview — An Insider's Guide (Vol. 1)*, Chapter 2: Back-of-the-Envelope Estimation — [ByteByteGo](https://bytebytego.com/)
- **[2]** Martin Kleppmann, *Designing Data-Intensive Applications (DDIA)*, Chapter 1: Reliability, Scalability, and Maintainability — [dataintensive.net](https://dataintensive.net/)
- **[3]** Jeff Dean & Colin Scott, *Latency Numbers Every Programmer Should Know* — [Interactive Visualizer](https://colin-scott.github.io/personal_website/research/interactive_latency.html)
- **[4]** Redis Official Documentation, *Redis Benchmarks & Single-Threaded Event Loop* — [redis.io/docs](https://redis.io/docs/)
- **[5]** Jay Kreps (LinkedIn), *The Log: What every software engineer should know about real-time data's unifying abstraction* — [engineering.linkedin.com](https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying)
- **[6]** Chip Huyen, *AI Engineering: Building Applications with Foundation Models* (O'Reilly, 2025) — Latency & Token Economics
- **[7]** Discord Engineering, *How Discord Stores Trillions of Messages* — [discord.com/blog](https://discord.com/blog/how-discord-stores-trillions-of-messages)
