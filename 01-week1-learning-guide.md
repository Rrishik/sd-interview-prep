# Week 1 Async Learning Guide: Core Building Blocks & Mock 0 Fixes

Written using **ASD-STE100** rules (short sentences, active voice, real-world analogies, and where each analogy breaks).
Open the interactive Excalidraw whiteboards side-by-side in VS Code:
- [00-timeline.excalidraw](./diagrams/00-timeline.excalidraw) — 4-Week Study Plan
- [mock0-notification-system.excalidraw](./diagrams/mock0-notification-system.excalidraw) — Reference Notification + AI Digest Architecture
- [01-kafka-and-redis.excalidraw](./diagrams/01-kafka-and-redis.excalidraw) — Kafka Partitions, Hot Keys, and Redis Data Structures

---

## 1. Mock 0 Recap: 4 Fixes That Separate Mid-Level from Senior/SDE2-3

| Mid-Level Instinct (What Trips Candidates) | Senior / L5 Pattern (What Interviewers Expect) | Why It Matters at 30k QPS |
|---|---|---|
| Workers poll a DB table for `status = PENDING` and lock rows. | Producers write to **Kafka partitions**. Each partition has **1 assigned worker** (zero locks). | Polling and locking DB rows at 30k QPS causes lock contention and hot secondary indexes. |
| Deduplicate retries by hashing `(user_id + channel + content)`. | Caller sends a UUID **`idempotency_key`** stored in Redis (`SET idem:<uuid> 1 NX EX 86400`). | Content hashing drops valid repeat alerts (for example, two `"Build failed"` alerts 2 minutes apart). |
| Hardcode channel mappings or check user preferences only at the final worker. | Cache **User Preferences & Device Tokens** in Redis (`user_prefs:<user_id>`) and check at the **Ingestion Router**. | Checking preferences early avoids queuing and rendering millions of muted notifications. |
| Fail the digest if all LLM providers are down or rate-limited. | Trip a **circuit breaker** and send a **deterministic template summary** (*"12 new messages in #eng"*). | Core product reliability must never depend on external LLM availability. |

---

## 2. Building Block 1: Message Queues & Kafka Internals

**Visual:** Left half of [01-kafka-and-redis.excalidraw](./diagrams/01-kafka-and-redis.excalidraw).

### What It Is
**Kafka** is a distributed, append-only event log. A **topic** (such as `push.notifications`) is split into $N$ independent **partitions** (lanes), numbered `0` to $N-1$.

### How Work Distribution Works Without Locks
1. **Producer routing:** The producer picks a partition using a hash of the key: `partition = hash(user_id) % N`. All events for `user_42` land in the same partition, in exact arrival order.
2. **Exclusive ownership:** Inside a **consumer group**, Kafka assigns each partition to **at most one worker thread**.
   - If a topic has 8 partitions and 8 workers, **Worker 2 is the only reader of Partition 2**.
   - Because two workers never read the same partition, **no row locks are needed**.
3. **Offset tracking:** Each worker simply increments its own read pointer (**offset**): `offset = 1041, 1042, 1043...`.

### Real-World Analogy
A highway toll plaza with 16 lanes (partitions) and 16 toll booths (workers). Every car with license plate ending in `3` enters Lane 3 and is served only by Booth 3. Booths never coordinate or lock cars.
- **Where the analogy breaks:** On a highway, a driver can swerve into another lane if Lane 3 is jammed. In Kafka, `hash(user_id) % 16` always sends that user to Partition 3.

### What Breaks: The "Hot Partition" (Celebrity / Noisy Bot Key)
- **Scenario:** An enterprise bot receives 500,000 notifications in 1 minute.
- **What breaks:** `hash(bot_id) % 16` sends all 500,000 messages to **one partition** (say Partition 3). Worker 3 falls 20 minutes behind, while the other 15 workers sit idle.
- **How to fix it (2 steps):**
  1. **Key Salting:** Detect hot keys and append a random suffix `1..10` (`bot_id#1` through `bot_id#10`). Now the bot's traffic spreads evenly across 10 partitions and 10 workers. (Trade-off: you lose strict global ordering across those 10 sub-keys.)
  2. **Ingestion Rate Limiting:** Cap per-sender or per-user volume at the API gateway before messages enter Kafka.

### Kafka vs. SQS / RabbitMQ (When to Choose Which)
| Feature | Kafka (Log-based Stream) | SQS / RabbitMQ (Traditional Queue) |
|---|---|---|
| Ordering | Strict ordering per partition key | Best-effort (or lower-throughput FIFO) |
| Replayability | Retains messages for days; multiple services can replay | Message is deleted once ACKed |
| Best for | High-throughput event streams, fan-out to multiple consumers, ordered per-user processing | Simple background jobs where any free worker can grab the next task (e.g., video transcoding) |

---

## 3. Building Block 2: The 4 Essential Redis Data Structures

**Visual:** Right half of [01-kafka-and-redis.excalidraw](./diagrams/01-kafka-and-redis.excalidraw).

Most candidates only say *"use Redis as a cache."* Senior candidates name the **exact Redis data structure and command**:

| # | Redis Structure | Key Commands | Classic Interview Use Cases | Complexity |
|---|---|---|---|---|
| **1** | **String** (with atomic flags) | `SET key val NX EX 86400`, `INCR key` | **Idempotency keys** (`NX` = set only if not exists), **rate-limit counters**, short distributed locks. | $O(1)$ |
| **2** | **List** (doubly linked list) | `RPUSH key item`, `LRANGE key 0 -1`, `DEL key` | **Message buffers** (holding a user's messages during a 15-min AI digest window), recent activity feeds. | $O(1)$ push/pop |
| **3** | **Sorted Set (`ZSET`)** | `ZADD key score member`, `ZRANGEBYSCORE key -inf now` | **Delayed timers** (`score = trigger_timestamp`), **sliding-window rate limiters**, **live leaderboards**. | $O(\log N)$ |
| **4** | **Hash** (field-value map) | `HGETALL user:42`, `HSET user:42 push_opt_in 1` | **User preferences & device cache**, shopping carts, session metadata. | $O(1)$ per field |

### Deep Dive: How `List` + `ZSET` Solve the 15-Minute AI Digest Window
1. **When a low-priority message arrives for `user_42`:**
   - Append the message to a **Redis List**: `RPUSH digest:msgs:user_42 <msg_json>`.
   - If this is the *first* message in the window, schedule the flush time in a **Redis Sorted Set (`ZSET`)** where `member = "user_42"` and `score = current_unix_time + 900 + random_jitter(0..120)`:
     `ZADD digest:timers 1730459742 "user_42"` (`NX` flag so later messages don't push the deadline back).
2. **Every second, Timer Workers poll due timers:**
   - Run `ZRANGEBYSCORE digest:timers -inf <current_unix_time> LIMIT 0 100`.
   - Because `ZSET` keeps members sorted by `score` (timestamp), Redis returns **only expired users** in $O(\log N)$ time—never scanning all 10M users!
   - For each due `user_id`, read the list (`LRANGE digest:msgs:user_42 0 -1`). If length $\ge 10$, send batch to the LLM Digest Worker; if $< 10$, send normal push notifications. Delete the list and remove `user_42` from `digest:timers`.
3. **Bonus:** The exact same `ZSET` timer pattern solves **"Wait 15 minutes; if Push is still unread, send Email"**: schedule `notif_id` in `ZSET` at `now + 15m`; when due, check NoSQL `is_read` status and send Email if `false`.

---

## 4. Building Block 3: Database Choice, Sharding & Indexing

| Requirement | Pick SQL (PostgreSQL / MySQL / Spanner) | Pick Wide-Column / KV NoSQL (Cassandra / DynamoDB) |
|---|---|---|
| Access pattern | Complex joins, multi-row ACID transactions, balances/inventory | High-velocity writes/reads by a known key (`user_id` + `timestamp`) |
| Write scale | Up to ~5k–10k writes/sec per primary before sharding | Scales horizontally to 100k+ writes/sec across partitions |
| Classic cases | Payments, ledger, ticket booking, user accounts | Notification logs, chat messages, telemetry, activity feeds |

### How DynamoDB / Cassandra Keys Work (Partition Key + Sort Key)
In our Notification Log table:
- **Partition Key (`user_id`):** Determines **which storage node** holds the data (`hash(user_id)`).
- **Sort Key (`created_at_ts` + `notif_id`):** Keeps all notifications for `user_42` physically sorted by time on disk.
- **Why this is fast:** Fetching *"latest 20 notifications for `user_42`"* hits **one node** and reads a contiguous slice on disk in $< 5\text{ ms}$.
- **Why polling `WHERE status = 'PENDING'` is an anti-pattern:** `status` only has 3 values (`PENDING`, `SENT`, `FAILED`). Indexing `status` puts all 30,000 writes/sec into a single `'PENDING'` index partition—melting that node.

---

## 5. Building Block 4: Back-of-the-Envelope Cheat Sheet

Memorize these 4 anchors:
- **$1\text{ day} = 86{,}400\text{ seconds} \approx 10^5\text{ seconds}$.**
  - $100\text{M requests/day} \approx 1{,}000\text{ QPS}$.
  - $1\text{B requests/day} \approx 10{,}000\text{ QPS}$ (Peak $\approx 3\times = 30{,}000\text{ QPS}$).
- **Storage math:** $\text{Events/day} \times \text{Bytes/event} \times 365$.
  - $1\text{B notifications/day} \times 1\text{ KB} = 1\text{ TB/day} = 365\text{ TB/year}$.
- **LLM Token & Cost Math (AI Track A1):**
  - $1\text{ token} \approx 0.75\text{ English words}$ ($1{,}000\text{ tokens} \approx 750\text{ words} \approx 3\text{ KB text}$).
  - Always separate **Input Tokens** (prompt + retrieved context) from **Output Tokens** (generated text—usually $3\times$ to $5\times$ more expensive and the main driver of latency).
  - Example from Mock 0 Quiz Q4:
    - $10\text{M users} \times 20\% \text{ active} \times 4\text{ digests/day} = 8\text{M digests/day}$.
    - $\text{Average LLM QPS} = 8 \times 10^6 / 10^5\text{ s} = \mathbf{80\text{ QPS}}$.
    - $\text{Tokens/day} = 8\text{M digests} \times (1{,}000\text{ in} + 200\text{ out}) = 8\text{M} \times 1{,}200 = \mathbf{9.6\text{ Billion tokens/day}}$.

---

## 6. Quick Self-Check (For When You Return)

When you are back, reply with your 1-line answers to these 3 questions and we will move straight into **Case Study #1 (URL Shortener) & Case Study #2 (Rate Limiter)**:

1. **Kafka Ownership:** If a Kafka topic has 8 partitions and a consumer group has 8 workers, how many workers read from Partition 2 at the same time—and why does that eliminate DB row locks?
2. **Hot Partition Fix:** Why did the noisy enterprise bot overload a single Kafka worker, and how does **key salting** (`bot_id#1..10`) fix it?
3. **Redis `ZSET` Timer:** In `ZADD digest:timers <score> <member>`, what value do we store as `<member>` and what value do we store as `<score>` to fire a 15-minute timer?
