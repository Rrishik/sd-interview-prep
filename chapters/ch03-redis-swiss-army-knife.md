# Chapter 3: Redis & The Four In-Memory Swiss Army Knives

*Part I · Core Building Blocks · 8 min core · 18 min with deep dives*

When engineers first hear about **Redis**, they usually hear a three-word summary: *"It's a fast cache."*

Calling Redis "just a cache" is like calling a Swiss Army knife "a toothpick." Yes, it has a toothpick—but the reason Redis powers so many distributed architectures is that it gives you **shared, atomic data structures in RAM** (`Strings`, `Lists`, `Sorted Sets`, and `Hashes`) that execute one command at a time on a **single-threaded event loop** [1, 2].

Let us unpack why that single thread is a superpower.

---

### 1) Why a Single Thread Beats 64 Threads (In RAM)

Suppose two Kafka workers accidentally receive the same notification (`notif_id = 999`) at the exact same microsecond because of a network retry. You want to make sure Alice's phone only buzzes **once**.

If both workers run two separate steps—first `GET notif:999` ("Does it exist? No!"), then `SET notif:999`—both workers will see "No" at the same time and send Alice two notifications. That is a classic **check-then-act race condition** [3].

Because Redis processes commands sequentially on a single main thread in RAM (taking ~`1 microsecond` per command), it provides single-command atomic operations like:

`SET notif:999 "SENT" NX EX 86400`

Let us translate every piece of that command:
- **`NX` (Not Exists):** Only set this key if it does *not* already exist, and return `1` (Success). If it already exists, do nothing and return `0` (Duplicate!).
- **`EX 86400`:** Automatically delete this key from RAM after `86,400` seconds (24 hours) so your memory never fills up with old IDs.

Because `SET ... NX` runs as a single atomic step inside Redis's single thread, Worker A gets `1` and sends the push; Worker B gets `0` a microsecond later and drops the duplicate. **Zero database locks, sub-millisecond latency** [1].

---

### 2) The Four Redis Data Structures You Must Know Cold

Look back at the lower half of the **Kafka & Redis** diagram in Chapter 2. Almost every high-scale coordination problem maps to one of these four Redis types [1, 2]:

| Redis Structure | What It Actually Is in RAM | Core Commands & Complexity | When to Use It |
| :--- | :--- | :--- | :--- |
| **1. String** | Key -> single value (text, integer, bytes) | `GET`, `SET key val NX EX ttl`, `INCR` — **`O(1)`** | **Idempotency locks** (`SET NX`), **rate-limit counters** (`INCR`), **ticket seat holds** (`SET seat:9A u1 NX EX 300`). |
| **2. List** | Doubly-linked list / quicklist of items | `RPUSH`, `LPOP`, `LRANGE 0 -1`, `DEL` — **`O(1)`** per item | **Batch buffers** (append Alice's AI digest notifications with `RPUSH`), **recent 100 News Feed IDs**. |
| **3. Sorted Set (`ZSET`)** | Unique members ordered by a `64-bit float score` (Skip List + Hash Table) | `ZADD key score member`, `ZRANGEBYSCORE key -inf NOW` — **`O(log N)`** | **Delayed timers** (`score = unix_timestamp`), **sliding-window rate limiters**, **live gaming leaderboards** (`ZREVRANGE`). |
| **4. Hash** | Key -> mini dictionary of `field: value` pairs | `HSET`, `HGET`, `HINCRBY` — **`O(1)`** | **User profiles / session metadata**, **WebSocket gateway routing table** (`user_42 -> {gateway: "gw-7", status: "online"}`). |

---

### 3) How to Build a 15-Minute Timer Without Scanning Million-Row Tables

Consider a classic scheduling problem: *"Alice wants an AI summary of her low-priority notifications every 15 minutes. How do you know when Alice's 15-minute window is up?"*

If you store `due_at` in a SQL table and run `SELECT * FROM digests WHERE due_at <= NOW()` every second, or if you scan all keys in Redis (`KEYS *`), your server will grind to a halt once millions of keys exist.

Instead, combine a **Redis List** with a **Redis Sorted Set (`ZSET`)** [2]:
1. When Alice's *first* low-priority notification arrives at `10:00`, append the payload to her Redis List: `RPUSH digest_items:Alice "{msg_1}"`.
2. Check if Alice already has a timer scheduled in the Sorted Set `digest_timers`. If not, register her with a **score equal to `NOW + 900 seconds` (`10:15`)**:
   `ZADD digest_timers 1711800900 "Alice"` (`O(log N)`).
3. If 5 more low-priority notifications arrive for Alice at `10:03` and `10:08`, simply `RPUSH` them onto `digest_items:Alice`. Do not touch her timer!
4. Every second, a lightweight scheduler worker asks the Sorted Set: *"Who has a score `<= NOW`?"*
   `ZRANGEBYSCORE digest_timers -inf 1711800900 LIMIT 0 100`
5. Because a `ZSET` keeps members sorted by score in a Skip List, Redis hands back **only the users whose timers just expired**, in `O(log N + M)` time, without ever looking at the 999,900 users whose timers are still in the future!

:::deepdive Meta Memcache Leases: Defending Against Cache Stampedes, Stale Sets & Hot Keys | +5 min

In Meta's landmark *Scaling Memcache at Facebook* (`NSDI 2013` [5]) paper, look-aside caching (`GET cache -> miss -> SELECT DB -> SET cache`) broke in three subtle ways at `billions of QPS`:

| Production Failure | Exact Race / Bottleneck | How Meta's Lease & L1 Pattern Solves It [5] |
| :--- | :--- | :--- |
| **1. Thundering Herd (Cache Stampede)** | Popular key `feed:viral` expires; **`5,000` app threads miss simultaneously** and stampede the same MySQL/Postgres row! | **Cache Leases (`SET lock:k NX EX 5` / `singleflight`):** On miss, Redis grants a `64-bit` **lease token** to the *first* client only; the other `4,999` clients wait `10 ms` or serve slightly stale value while 1 query refreshes DB [5]. |
| **2. Stale-Set Race Condition** | Reader A misses (`v1`), Writer B updates DB (`v2`) and `DEL`s cache, then slow Reader A wakes up and writes **stale `v1` into cache forever**! | When `DEL` runs on a write, Redis **invalidates any active lease token** for that key—so Reader A's delayed `CAS/lease-set` is deterministically rejected [5]! |
| **3. Single-Shard Hot Key (`500k QPS`)** | Even 1 Redis shard tops out around `~100k–200k ops/s`; `1M` reads/sec on one celebrity key melts the shard's NIC & single CPU core. | **Tiny In-Process L1 LRU Cache (`1–2s` TTL + Redis `RESP3` Client-Side Tracking invalidations)** or **Key Read-Replication** (`key#1..key#10` across 10 shards) absorbs `99%` of hot reads in app RAM [1, 5]. |

:::

---

### 4) What If Redis Crashes? (Why RAM Needs a Backup Plan)

Redis lives in volatile RAM. What happens if your Redis node reboots at `10:14`, one minute before Alice's 15-minute AI digest fires?

Redis offers two persistence mechanisms, plus replication [1]:
- **RDB (Snapshotting):** Periodically forks and writes a compact point-in-time snapshot to disk (e.g., every 5 minutes). Fast, but a crash loses up to 5 minutes of writes.
- **AOF (Append-Only File):** Logs every write command to disk (`appendfsync everysec`). A crash loses at most **1 second** of data, and Redis Sentinel / Cluster fails over to a warm replica in seconds.
- **The Production Rule:** Never treat Redis as your *only* copy of financial or user-critical data. Keep the raw events durable on disk in **Kafka** (or your database), and use Redis for fast in-memory coordination, timers, and deduplication.

:::deepdive Redis Cluster `16,384` Hash Slots, Async Failover & Why `Redlock` Fails Safety | +5 min

1. **How Redis Cluster Shards RAM (`CRC16(key) mod 16384`) [6]:**
   - Instead of dynamic token rings, **Redis Cluster** partitions the keyspace into **16,384 fixed hash slots** (`Node A: 0–5460`, `Node B: 5461–10922`, `Node C: 10923–16383`) [6]. Smart clients cache the slot map (`<2 KB`) for **1-hop routing** (`MOVED` redirects update stale maps).
   - **Multi-Key Hash Tags (`{...}`):** Multi-key commands or Lua scripts (`EVAL`) fail with `CROSSSLOT` unless all keys live on the same shard! Wrapping the shared entity in braces—`{user_42}:profile` and `{user_42}:cart`—forces Redis to hash **only `user_42`**, co-locating related keys on one slot (never put a low-cardinality tag like `{us_east}` or you create a massive hot shard!) [6].
2. **Async Replication Split-Brain & Kleppmann's `Redlock` Critique [6, 7]:**
   - Redis replication is **asynchronous** by default: Client 1 acquires `SET lock:99 owner1 NX PX 10000` on Primary A, Primary A crashes *before* replicating `lock:99` to Replica A', Replica A' promotes to Primary, and **Client 2 acquires `lock:99` simultaneously**!
   - As Martin Kleppmann proved [7], even `Redlock` across 5 Redis nodes relies on wall-clock/pause assumptions that **GC pauses break**: use Redis locks for **efficiency** (preventing duplicate work), never as your sole **correctness** guard—always pair mutations with a **monotonic fencing token** checked by the storage engine (see Chapter 18) [7]!

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** A database on disk is a **warehouse across town** with forklifts and safety paperwork; **Redis** is a **whiteboard on the wall right behind the receptionist**. One receptionist (single thread) can erase a number, add 1, or check the top name on a ranked list in half a second without two people ever grabbing the marker at the same time.
- **Where the analogy breaks:** If the building loses power, a whiteboard is tiny compared to a warehouse (`RAM costs ~10× more per GB than SSD`), and unless someone photographs the whiteboard every second (`AOF`), a sudden crash can wipe the last second of scribbles.
- **Real production system:** **Stripe** uses Redis (with atomic Lua scripts) to power its distributed API rate limiters and idempotency keys (`Idempotency-Key` header) so retrying a network-timed-out credit card charge never double-charges a customer [4].

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why is <code>GET key</code> followed by <code>SET key</code> in your application code NOT safe for deduplication, while <code>SET key val NX EX 86400</code> IS safe?</strong></summary>
<p><strong>Answer:</strong> Two separate commands (<code>GET</code> then <code>SET</code>) allow a race window where two concurrent workers both read <code>nil</code> before either writes. <code>SET ... NX</code> executes the check and write as a <strong>single atomic command</strong> on Redis's single-threaded event loop.</p>
</details>

<details>
<summary><strong>Q2: Which Redis data structure lets you fetch all scheduled tasks where <code>due_time &lt;= NOW()</code> in <code>O(log N + M)</code> time?</strong></summary>
<p><strong>Answer:</strong> A <strong>Sorted Set (<code>ZSET</code>)</strong>, using the Unix timestamp as the numeric <code>score</code> and polling with <code>ZRANGEBYSCORE key -inf NOW</code>.</p>
</details>

<details>
<summary><strong>Q3: If you need 4 operations (read token count, calculate refill, decrement, save new count) to execute atomically in Redis without race conditions, what feature do you use?</strong></summary>
<p><strong>Answer:</strong> A <strong>Redis Lua script</strong> (<code>EVAL</code> / <code>EVALSHA</code>). Redis executes the entire Lua script atomically on its single thread without interleaving any other client's commands.</p>
</details>

---

### Sources & References
- **[1]** Josiah L. Carlson, *Redis in Action* (Manning) — Core Data Structures & Atomic Operations — [redis.io/docs/latest/develop/data-types/](https://redis.io/docs/latest/develop/data-types/)
- **[2]** Alex Xu, *System Design Interview (Vol. 1 & 2)*, Rate Limiter, Leaderboard & Notification Systems — [ByteByteGo](https://bytebytego.com/)
- **[3]** Martin Kleppmann, *Designing Data-Intensive Applications (DDIA)*, Chapter 7: Transactions & Race Conditions
- **[4]** Brandur Leach (Stripe), *Implementing Stripe-like Idempotency Keys & Rate Limiters with Redis* — [stripe.com/blog/rate-limiters](https://stripe.com/blog/rate-limiters)
- **[5]** Rajesh Nishtala et al. (Meta), *Scaling Memcache at Facebook (Leases, Thundering Herds & Regional Pools)* (USENIX NSDI 2013) — [usenix.org/conference/nsdi13/nishtala](https://www.usenix.org/conference/nsdi13/technical-sessions/presentation/nishtala)
- **[6]** Redis Official Specification, *Redis Cluster Specification (16,384 Hash Slots, Hash Tags & Failover)* — [redis.io/docs/cluster-spec](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/)
- **[7]** Martin Kleppmann, *How to do distributed locking (Why Redlock Is Unsafe Without Fencing Tokens)* (2016) — [martin.kleppmann.com/distributed-locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)
