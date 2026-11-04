# Chapter 18: Reactive Agent Backends (Spring WebFlux), High-Contention Concurrency & Keyset Pagination

*Part III · AI & LLM Engineering Systems · 8 min read*

An LLM is only 20% of a production agent platform. The other 80% is high-concurrency backend systems engineering:
1. Holding **50,000 open streaming connections** for 10 seconds each without exhausting OS threads.
2. Counting millions of tokens per second across 64 CPU cores without **race conditions** or cache-line lock contention.
3. Paginating through 50 million agent run logs in `< 1 ms` without melting your PostgreSQL primary.

Let us examine all three backend pillars in the bottom right of the diagram in Chapter 15 [1, 2, 3].

---

### 1) Why Streaming Agent Gateways Use `Spring WebFlux` (`Flux<SSE>`)

In a classic blocking **Thread-per-Request** server (Spring MVC on Tomcat with `200` worker threads), a `5 ms` DB read handles `200 / 0.005s = 40,000 QPS`.
Now replace that with an **AI Agent stream** that runs for **`10 seconds`**: each user locks up 1 OS thread (`~1 MB` stack) sitting idle `99%` of the time waiting on network I/O. Just **201 concurrent users freeze the server (`20 QPS` cap)**!

**Reactive Event Loops (`Spring WebFlux` / `Project Reactor`)** multiplex **50,000+ concurrent SSE streams** onto a tiny pool of non-blocking Netty event-loop threads (`1 per CPU core`) [1]:
- **`Mono<T>` (`0..1` async value):** Non-blocking single LLM call, Redis check, or DB lookup.
- **`Flux<ServerSentEvent<T>>` (`0..N` stream):** Streams live tokens, tool progress badges, and citations over HTTP `text/event-stream`.
- **`Mono.zip(toolA, toolB, toolC)`:** Dispatches a parallel DAG wave of independent MCP tools concurrently.
- **Golden Rule:** Never block a Netty event-loop thread! Offload any legacy blocking JDBC or CPU work via **`.subscribeOn(Schedulers.boundedElastic())`**.

---

### 2) Concurrency Under the Hood: `counter++`, `AtomicLong` vs. `LongAdder`

Why does `counter++` lose updates when 32 threads run it without synchronization? Because it compiles into three separate CPU steps (**Read -> Modify -> Write**); two threads reading `100` simultaneously both write `101`.

When interviewers ask how to fix a high-throughput shared counter (like a global token-rate meter across 64 cores), know the **3-level contention hierarchy** [2]:

| Primitive | Mechanism | Behavior Under 64-Core Contention | When to Choose It |
| :--- | :--- | :--- | :--- |
| **1. `synchronized` / `ReentrantLock`** | OS/JVM mutex; losing threads sleep (`~2–5 µs` context switch). | Threads queue and sleep; safe for multi-variable invariants. | Compound state mutations (e.g., `HashMap` + Doubly Linked List in a thread-safe LRU cache). |
| **2. `AtomicLong` (`CAS` loop)** | Hardware CPU `LOCK CMPXCHG` retry loop on one memory address. | **Cache-line ping-pong!** All 64 cores invalidate the *exact same 64-byte L1/L2 cache line*, wasting CPU cycles on failed CAS retries. | Low/moderate contention (`1–8` threads) or atomic state flags. |
| **3. `LongAdder` (Striped `Cell[]`)** | Shards the counter across cache-line-padded `Cell[]` slots; `.sum()` adds them on read. | **`8×–10×` higher throughput** than `AtomicLong` at 64 cores! | High-contention telemetry counters & token meters. |

---

### 3) Database Internals: Keyset Pagination, SQL `NULL` Traps & OLTP vs. OLAP

1. **Why `OFFSET 2000000 LIMIT 20` Is Slow (And the Composite Keyset Fix):**
   - `OFFSET 2000000` forces PostgreSQL to scan and discard **2,000,000 rows** (`O(OFFSET + LIMIT)`).
   - **Keyset Cursor (`O(LIMIT)` = `< 1 ms` at any depth):** Seek directly in the composite B-Tree index `(created_at DESC, id DESC)`:
     `WHERE (created_at, id) < (:last_ts, :last_id) ORDER BY created_at DESC, id DESC LIMIT 20`
   - Including the unique tie-breaker `id` is mandatory so rows sharing the exact same millisecond at a page boundary are never skipped [3].
2. **SQL Three-Valued `NULL` Logic (`COUNT` & `AVG`):**
   - On 10 rows where 3 have `email = NULL`: **`COUNT(*)` is `10`**, **`COUNT(email)` is `7`**, and `AVG(col)` divides `SUM(col)` by `COUNT(col)` (ignoring `NULL`s!). Also prefer `WHERE NOT EXISTS` over `NOT IN` (which returns `0 rows` if the subquery contains a single `NULL`).
3. **OLTP (Row Store) vs. OLAP (Columnar Store):**
   - **OLTP (`PostgreSQL`):** Stores entire rows on `8 KB` B-Tree pages for fast point lookups/writes.
   - **OLAP (`ClickHouse` / `Parquet`):** Stores each column in a separate compressed file block, reading **only the 2 needed columns** (`input_tokens`, `model_id`) with vectorized SIMD scans across billions of rows [3].

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **Blocking Thread-per-Request** is a waiter standing frozen at the kitchen window for 10 minutes waiting for Table 1's steak. **Reactive `WebFlux`** is a waiter who drops off the ticket (`subscribe`) and serves 40 other tables until the bell rings (`onNext`).
- **Where the analogy breaks:** If that reactive waiter stops at Table 4 to carve an ice sculpture for 5 minutes (running blocking I/O on the Netty event loop), all 40 tables freeze—so blocking calls must always move to `boundedElastic()`.
- **Real production system:** **Spring AI Gateways** (Netty `WebFlux` SSE) paired with **ClickHouse** columnar observability stores power high-concurrency enterprise agent platforms [1, 3].

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why is <code>LongAdder</code> up to 10× faster than <code>AtomicLong</code> when 64 threads increment a token counter concurrently?</strong></summary>
<p><strong>Answer:</strong> <code>AtomicLong</code> hammers a single memory address with hardware <code>CAS</code> retries, causing L1/L2 cache-line ping-ponging across cores. <code>LongAdder</code> stripes updates across cache-line-padded <code>Cell[]</code> slots and sums them on read.</p>
</details>

<details>
<summary><strong>Q2: Why must Keyset Pagination use <code>WHERE (created_at, id) &lt; (:last_ts, :last_id)</code> instead of just <code>WHERE created_at &lt; :last_ts</code>?</strong></summary>
<p><strong>Answer:</strong> If multiple rows share the exact same <code>created_at</code> timestamp across a page boundary, <code>created_at &lt; :last_ts</code> permanently skips the remaining rows with that timestamp. Adding the unique <code>id</code> tie-breaker guarantees lossless pagination.</p>
</details>

<details>
<summary><strong>Q3: If a table has 10 rows and 3 rows have <code>NULL</code> in <code>score</code> (with the other 7 rows all equal to <code>10</code>), what do <code>COUNT(*)</code>, <code>COUNT(score)</code>, and <code>AVG(score)</code> return?</strong></summary>
<p><strong>Answer:</strong> <code>COUNT(*) = 10</code>, <code>COUNT(score) = 7</code>, and <code>AVG(score) = 10.0</code> (dividing <code>70 / 7</code>, ignoring <code>NULL</code> rows).</p>
</details>

---

### Sources & References
- **[1]** Spring AI & Spring WebFlux Reference — *Reactive `ChatClient`, `Flux` SSE Streaming & `Schedulers.boundedElastic()`* — [docs.spring.io/spring-ai/reference](https://docs.spring.io/spring-ai/reference/)
- **[2]** Brian Goetz et al., *Java Concurrency in Practice* & JDK `LongAdder` — CAS Contention vs. Striped Counters
- **[3]** Martin Kleppmann, *Designing Data-Intensive Applications (DDIA)*, Chapter 3: B-Trees, Keyset Scans & Column-Oriented OLAP Storage
