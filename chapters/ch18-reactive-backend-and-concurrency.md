# Chapter 18: Reactive Agent Backends (Spring WebFlux), High-Contention Concurrency & Keyset Pagination

*Part IV · Autonomous Agent Systems · 10 min read*

Why does an **AI Agent Engineering** interview test **Non-Blocking Reactive Streams (`Spring WebFlux` / `Project Reactor`)**, **Multithreading (`AtomicLong` vs `LongAdder`)**, and **Database Internals (`Keyset Pagination`, `OLTP vs OLAP`, `SQL NULLs`)** right alongside LLM architectures?

Because the LLM is only 20% of a production agent platform. The other 80% is high-concurrency backend systems engineering:
- Holding **50,000 open streaming connections** for 15 seconds each without exhausting OS threads.
- Counting millions of tokens per second across 64 CPU cores without **race conditions** or cache-line lock contention.
- Paginating through 50 million agent execution logs in `< 2 ms` without melting your PostgreSQL primary.

Let us master all three backend pillars shown in the bottom right of the diagram in Chapter 15 [1, 2, 3].

---

### 1) Why Agent Servers Must Be Non-Blocking (`Spring WebFlux` & `Flux<SSE>`)

In a classic CRUD microservice, a database lookup takes `5 ms`. A traditional **Thread-per-Request** server (like Spring MVC on Tomcat with `200` worker threads) can easily handle `200 / 0.005s = 40,000 QPS`.

Now replace that `5 ms` DB read with an **AI Agent workflow** that streams tokens and runs tools for **`10 seconds`**:
- Under blocking Thread-per-Request, each active user locks up 1 OS thread (`~1 MB` stack RAM) sitting idle `99%` of the time waiting on network packets from the LLM or MCP server.
- With 200 worker threads, **201 simultaneous users completely freeze the server** (`40,000 QPS` collapses to **`20 QPS`**!).

**The Production Fix — Reactive Event Loops (`Spring WebFlux` / `Project Reactor`):**
Instead of blocking a thread on network I/O, a tiny pool of Netty event-loop threads (`1 per CPU core`, using OS `epoll`/`kqueue`) multiplexes **50,000+ concurrent Server-Sent Events (`SSE`) streams** on a single node [1]:

| Concept | Reactive Java (`Spring Boot / WebFlux / Spring AI`) | Equivalent in `.NET / TypeScript` | Role in an Agent Backend |
| :--- | :--- | :--- | :--- |
| **Async Single Value (`0..1`)** | **`Mono<AgentPlan>`** | `Task<AgentPlan>` / `Promise<AgentPlan>` | Non-blocking single LLM call, DB read, or Redis lookup. |
| **Async Token Stream (`0..N`)** | **`Flux<ServerSentEvent<AgentEvent>>`** | `IAsyncEnumerable<T>` / `ReadableStream` | Streams live tokens, tool progress badges, and citations over `text/event-stream` (`SSE`). |
| **Parallel DAG Tool Wave** | **`Mono.zip(toolA, toolB, toolC)`** | `Task.WhenAll(a, b, c)` / `Promise.all` | Executes independent MCP tools concurrently and combines their typed results. |
| **Offloading Blocking Legacy Code** | **`.subscribeOn(Schedulers.boundedElastic())`** | `Task.Run(...)` / Worker Pool | **Golden Rule:** Never block a Netty event-loop thread! Offload any synchronous JDBC/CPU work to `boundedElastic`. |

---

### 2) Concurrency Under the Hood: Race Conditions, `AtomicLong` vs. `LongAdder`

Suppose 32 worker threads share an in-memory counter `totalTokensProcessed++` without synchronization. Why is the final count wrong?

Because `counter++` is **not atomic**—it compiles into three separate CPU steps (**Read-Modify-Write**):
1. **Read:** Load `counter` (`100`) from RAM into CPU register `EAX`.
2. **Modify:** Add `1` in register (`101`).
3. **Write:** Store `101` back to RAM.
If Thread A and Thread B both read `100` at the same nanosecond, both write `101`, and one increment is permanently lost!

Now, how do you fix this in production? Do **not** stop at saying *"use a lock or `AtomicLong`"*—explain the **3-level contention hierarchy** [2]:

| Synchronization Primitive | How It Works in Hardware / JVM | Behavior Under High Contention (64 Cores) | Best Use Case |
| :--- | :--- | :--- | :--- |
| **1. `synchronized` / `ReentrantLock` / `std::mutex`** | OS/JVM mutex; puts losing threads to sleep (context switch `~2–5 µs`). | Threads queue up and sleep; safe for multi-variable invariants. | Updating compound state (such as a `HashMap` + Doubly Linked List inside a thread-safe LRU Cache). |
| **2. `AtomicLong` / `std::atomic` (`CAS` Loop)** | Hardware CPU instruction (`LOCK CMPXCHG`): spins and retries if another core modified the value first. | **Cache-line ping-pong!** All 64 cores hammer the *exact same 64-byte L1/L2 cache line*, causing a storm of MESI cache invalidations and wasted CAS retries. | Low-to-moderate contention (`1–8 threads`) or atomic state-machine flags (`Compare-And-Swap`). |
| **3. `LongAdder` (Striped Cells)** | Maintains an array of cache-line-padded `Cell[]` counters. Threads hash to different cells and increment with **zero contention**; `.sum()` adds the cells on read. | **`8×–10×` higher throughput** than `AtomicLong` at 64 cores! | High-frequency telemetry counters (global token rate, QPS metrics, active stream gauges). |

---

### 3) Database Internals: Keyset Pagination, SQL `NULL` Traps & OLTP vs. OLAP

Let us lock down the three database design rules that appear in almost every backend engineering interview [3]:

1. **Why `OFFSET 2000000 LIMIT 20` Melts Databases (And the Composite Keyset Fix):**
   - When you run `SELECT * FROM agent_runs ORDER BY created_at DESC OFFSET 2000000 LIMIT 20`, a B-Tree index cannot teleport to row `#2,000,000`. PostgreSQL must walk, read, and discard **`2,000,000` rows** (`O(OFFSET + LIMIT)` time = seconds of disk/CPU waste).
   - **Keyset (Cursor) Pagination (`O(LIMIT)` = `< 1 ms` at any depth):** Pass the last row from the previous page (`last_ts`, `last_id`) and seek directly in the composite B-Tree index `(created_at DESC, id DESC)`:
     `SELECT id, created_at, status FROM agent_runs WHERE (created_at, id) < (:last_ts, :last_id) ORDER BY created_at DESC, id DESC LIMIT 20;`
   - **Why is the tie-breaker `id` mandatory?** Because if 4 agent runs finished in the exact same millisecond, filtering by `WHERE created_at < :last_ts` alone will **permanently skip** the remaining rows that shared that millisecond!
2. **SQL Three-Valued `NULL` Logic (`COUNT`, `AVG`, and `NOT IN`):**
   - `COUNT(*)` counts **every row** matching the `WHERE` clause (including rows with `NULL`s).
   - `COUNT(col)` counts only rows where `col IS NOT NULL`.
   - `AVG(col)` divides `SUM(col)` by `COUNT(col)`—completely ignoring `NULL` rows! (If 5 rows have ratings `[5, 5, NULL, NULL, NULL]`, `AVG(rating)` is **`5.0`**, not `2.0`!).
   - **The `NOT IN` Trap:** `WHERE id NOT IN (SELECT parent_id FROM runs)` returns **`0 rows`** if even a single row in the subquery has `parent_id = NULL` (because `id != NULL` evaluates to `UNKNOWN`). Always use `WHERE NOT EXISTS (...)` instead.
3. **OLTP (Row-Oriented) vs. OLAP (Columnar Storage):**
   - **OLTP (`PostgreSQL` / `MySQL`):** Stores all columns of a row together on an `8 KB` B-Tree page. Best for transactional point reads/writes (`get_session(id)`).
   - **OLAP (`ClickHouse` / `Apache Parquet` / `Snowflake`):** Stores each column (`input_tokens`, `cost_usd`, `model_id`) in a separate contiguous compressed file block. Aggregating `SUM(cost_usd) GROUP BY model_id` across 1 billion agent runs reads **only 2 columns** (`< 2%` of disk I/O) using vectorized SIMD instructions [3].

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **Blocking Thread-per-Request** is a waiter who takes Table 1's order, walks to the kitchen, and stands frozen in front of the oven for 10 minutes until the dish is cooked. **Reactive `WebFlux`** is a waiter who hands the ticket to the kitchen (`subscribe`) and immediately serves 40 other tables until the kitchen bell rings (`onNext`).
- **Where the analogy breaks:** If that reactive waiter suddenly stops at Table 4 to hand-carve an ice sculpture for 5 minutes (running a synchronous blocking JDBC call or heavy CPU loop directly on the Netty event-loop thread!), all 40 of their tables starve. In `WebFlux`, **never block the event loop**.
- **Real production system:** **Spring AI + Spring WebFlux** and **ClickHouse / Apache Iceberg Observability Lakes** power streaming agent gateways and billion-row token analytics pipelines across modern cloud platforms [1, 3].

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why does a blocking thread-per-request server (200 threads) collapse when serving an AI agent endpoint that streams for 10 seconds, and how does <code>Spring WebFlux</code> solve it?</strong></summary>
<p><strong>Answer:</strong> In thread-per-request, each 10-second stream occupies 1 dedicated OS thread waiting on network I/O, capping concurrency at <code>200 users</code> (<code>20 QPS</code>). <code>Spring WebFlux</code> uses non-blocking Netty event-loop threads (<code>Flux&lt;ServerSentEvent&gt;</code>) so idle streams consume zero threads while waiting for the next token, allowing a single node to multiplex <code>50,000+</code> open streams.</p>
</details>

<details>
<summary><strong>Q2: Both <code>AtomicLong</code> and <code>LongAdder</code> are thread-safe and lock-free. Why is <code>LongAdder</code> up to 10× faster when 64 threads increment a token counter simultaneously?</strong></summary>
<p><strong>Answer:</strong> <code>AtomicLong</code> updates a single volatile variable via a hardware <code>CAS</code> loop, causing all 64 CPU cores to invalidate each other's L1/L2 cache line (cache-line ping-ponging). <code>LongAdder</code> shards the counter across an array of padded <code>Cell</code>s so threads increment separate cache lines without contention, summing the cells only on read.</p>
</details>

<details>
<summary><strong>Q3: What bug occurs if you implement Keyset Pagination with <code>WHERE created_at &lt; :last_ts ORDER BY created_at DESC LIMIT 20</code>, and how do you fix it?</strong></summary>
<p><strong>Answer:</strong> If multiple rows share the exact same <code>created_at</code> timestamp at a page boundary, <code>created_at &lt; :last_ts</code> permanently skips the remaining rows with that timestamp. Fix it by adding a unique tie-breaker column in both the B-Tree index and the tuple predicate: <code>WHERE (created_at, id) &lt; (:last_ts, :last_id) ORDER BY created_at DESC, id DESC LIMIT 20</code>.</p>
</details>

<details>
<summary><strong>Q4: A table <code>agent_runs</code> has 5 rows with <code>csat_score = [5, 5, NULL, NULL, NULL]</code>. What do <code>COUNT(*)</code>, <code>COUNT(csat_score)</code>, and <code>AVG(csat_score)</code> return?</strong></summary>
<p><strong>Answer:</strong> <code>COUNT(*)</code> returns <strong><code>5</code></strong> (all rows), <code>COUNT(csat_score)</code> returns <strong><code>2</code></strong> (non-NULL rows only), and <code>AVG(csat_score)</code> returns <strong><code>5.0</code></strong> (<code>(5 + 5) / 2</code>, ignoring NULL rows rather than dividing by 5).</p>
</details>

<details>
<summary><strong>Q5: Why is a columnar database (ClickHouse / Parquet) 50× faster than an OLTP row-oriented database (PostgreSQL) at computing <code>AVG(input_tokens) GROUP BY model_id</code> over 500 million agent runs?</strong></summary>
<p><strong>Answer:</strong> A row-oriented B-Tree stores all 30 columns of each row together on disk pages, forcing the engine to read terabytes of irrelevant prompt/metadata columns. A columnar engine stores each column in its own compressed file block and reads <strong>only the 2 needed columns</strong> (<code>input_tokens</code> and <code>model_id</code>) using vectorized SIMD scans.</p>
</details>

---

### Sources & References
- **[1]** Spring AI & Spring WebFlux Reference — *Reactive `ChatClient`, `Flux` SSE Streaming, and `Schedulers.boundedElastic()`* — [docs.spring.io/spring-ai/reference](https://docs.spring.io/spring-ai/reference/)
- **[2]** Brian Goetz et al., *Java Concurrency in Practice* & JDK `java.util.concurrent.atomic.LongAdder` — CAS Contention vs. Striped Atomic Counters
- **[3]** Martin Kleppmann, *Designing Data-Intensive Applications (DDIA)*, Chapter 3: Storage and Retrieval (B-Trees, Keyset Scans & Column-Oriented OLAP Storage)
