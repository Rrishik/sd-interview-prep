# Chapter 5: Global Notification System + AI Smart Digest (30k QPS)

*Part II · Classic System Design Stories · 10 min core · 15 min with deep dives*

It is 9:00 AM on Black Friday. Within three seconds, 100,000 merchants trigger flash-sale alerts, payment receipts, and security OTP codes across your platform.

Your notification service is suddenly hit with **30,000 requests per second**. At the same time:
- Apple APNs is taking `400 ms` per call.
- A third-party SMS gateway in Europe is returning `503 Service Unavailable`.
- And your new **AI Smart Digest** feature needs to summarize low-priority marketing and social alerts every 15 minutes using an LLM without bankrupting the company on GPU tokens.

If your API server tries to call Apple, Twilio, or OpenAI synchronously inside the HTTP request handler, all 30,000 worker threads block on slow network sockets within two seconds, and your entire company's API goes dark.

Let us build the production architecture that survives this without dropping a single critical alert [1, 2].

{{diagram:03-notification-system.excalidraw}}

---

### 1) Step 1: Decouple Ingestion from Delivery (The 50 ms Rule)

Look at the left side of the diagram above. When an internal service (like Billing or Auth) calls `POST /v1/notify`, our **Notification Ingestion Service** does only three fast things before returning `202 Accepted` in under `50 ms`:

1. **Validate & Enrich (Cached):** Fetch the user's device tokens and opt-in preferences from **Redis** (backed by PostgreSQL on cache miss). Never hit PostgreSQL on every request at 30k QPS!
2. **Write the Initial Status Log:** Append a `PENDING` record with `(user_id, created_at)` into our sharded **Notification Log DB (Cassandra)** so users can see their in-app inbox.
3. **Publish to Priority-Isolated Kafka Topics:** Route the event to `notif.high` (OTP, fraud alerts, receipts) or `notif.low` (likes, promos, digest candidates), keyed by `user_id` [1].

**Why separate `notif.high` and `notif.low` topics?** Because if a marketing campaign dumps 50 million promo emails into `notif.low`, a password-reset OTP on `notif.high` has its own dedicated conveyor belt and worker pool—it never waits behind a promo backlog (**head-of-line blocking isolation**) [1].

---

### 2) Step 2: Deduplication, Retries & The Dead-Letter Queue (DLQ)

Now follow the top path (`notif.high` -> Delivery Workers). Because network timeouts happen, Kafka gives us **at-least-once delivery**—meaning a worker might see `notif_id = 999` twice.

Before calling Apple APNs, Firebase FCM, or Twilio SMS, the worker executes one atomic command in **Redis**:

`SET dedup:notif_999 "1" NX EX 86400`

- If Redis returns `0` (`nil`), this notification was already sent in the last 24 hours. The worker drops it and commits the Kafka offset.
- If Redis returns `1` (`OK`), the worker calls the external provider (APNs/FCM/Twilio).

**What if Twilio returns `503`?** The worker does **not** sleep and block the Kafka partition! Instead, it publishes the failed message to a **Retry Topic** (`notif.retry.1m` -> `notif.retry.5m` -> `notif.retry.30m`) with exponential backoff + jitter. After 5 failed attempts, the message moves to a **Dead-Letter Queue (DLQ)** and pages the on-call engineer [1, 2].

---

### 3) Step 3: The 15-Minute AI Smart Digest & Circuit Breaker

Now trace the bottom path (`notif.low` -> **Redis Digest Buffer**). If Alice receives 12 low-priority social alerts between `10:00` and `10:15`, calling an LLM 12 separate times wastes `12×` the system prompt tokens and sends Alice 12 annoying buzzes.

Instead, we use the **Redis List + Sorted Set (`ZSET`) pattern** from Chapter 3:
1. Append each low-priority alert to Alice's Redis List: `RPUSH digest_items:Alice "{event}"`.
2. Set Alice's 15-minute window expiration in a Redis Sorted Set: `ZADD digest_timers <now+900> "Alice"` (`NX`).
3. Every second, the **Digest Scheduler** polls `ZRANGEBYSCORE digest_timers -inf <now>`, pops Alice's buffered list (`LRANGE` + `DEL`), and sends **one combined prompt** to the **LLM Digest Worker** [3].

**What if the LLM API times out or returns `429 Rate Limit`?**
You wrap the LLM call in a **Circuit Breaker** (`2,000 ms` timeout):
- **Primary path:** Call the fast small model (`GPT-4o-mini` / `Haiku`) to produce a 2-sentence summary (`"3 teammates commented on PR #42 and 2 build checks passed"`).
- **Fallback path (when circuit is OPEN or times out):** Immediately fall back to a **deterministic template** (`"You have 5 new updates from GitHub and Slack"`). The user still gets their digest on time, and the system never stalls on an LLM outage!

:::deepdive AI Smart Digest Trade-Offs: Urgency Routing, Batch APIs & Anti-Hallucination | +5 min

When an interviewer pushes deeper on *"How do you design the AI Smart Digest without delaying urgent alerts, hallucinating status, or blowing GPU budgets?"*, walk through **Options A -> B -> C** [3, 4, 5]:

| Design Option | Architecture | Cost & Latency | Where It Breaks or Wins |
| :--- | :--- | :--- | :--- |
| **Option A: Per-Event LLM Rewrite** | Summarize every notification immediately on arrival. | `12×` system-prompt overhead; `$` explodes at `30k QPS`. | **Fails:** Defeats digest batching and still spams the user's lock screen [3]. |
| **Option B: Blind `15m` Cron Batch** | Hold *all* non-OTP events in Redis `ZSET` for `15 min`, then call online LLM. | `10×` cheaper than Option A. | **Fails on semi-urgent events:** A `"Prod build broken on release branch"` Slack ping gets trapped for `15 minutes`! |
| **Option C: Urgency Classifier + Adaptive `ZSET` + Async Batch Lane** | `<5 ms` lightweight classifier routes `P0` immediately, `P1` into `15m` online `ZSET`, and `P2` daily digests into **`50%`-off Async Batch APIs** [4, 5]. | Lowest cost + `<1s` `P0` delivery. | **Wins:** Matches latency and GPU spend to true user urgency [4, 5]. |

**Three Production Guardrails Specific to AI Notification Digests [3, 5]:**
1. **Cross-Channel Incident Deduplication Before Prompting:** A single outage often emits 1 PagerDuty alert, 3 Slack mentions, and 2 Jira emails. Cluster events by `(entity_id / incident_key)` *before* calling the LLM so the user sees **1 consolidated item** instead of 6 repetitive bullets.
2. **Strict `[event_id]` Grounding & Polarity Check:** Require structured JSON output `{summary_bullet, source_event_ids: [...]}` where every `event_id` must exist in the user's Redis window—preventing the #1 digest hallucination (*summarizing `"Alice requested changes on PR #42"` as `"Alice approved PR #42"`*) [3, 5]!
3. **Timezone Quiet Hours & Mute-Rate Feedback Loop:** Schedule `ZSET` flush scores in the recipient's local waking window, and track **notification mute / disable rate** as your primary counter-metric against over-eager urgency promotion [5].

:::

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why must OTP codes and marketing digests use separate Kafka topics and worker pools?</strong></summary>
<p><strong>Answer:</strong> To prevent <strong>head-of-line blocking</strong>. A 10-million-message marketing blast would otherwise fill the queue and delay time-critical 2FA OTP codes past their 60-second expiration window.</p>
</details>

<details>
<summary><strong>Q2: Why shouldn't a Kafka worker call <code>Thread.sleep(30000)</code> inside its consumer loop when Twilio returns HTTP 503?</strong></summary>
<p><strong>Answer:</strong> Because sleeping inside the consumer loop blocks the entire Kafka partition for 30 seconds, halting thousands of other healthy notifications sitting behind that message on the same partition.</p>
</details>

<details>
<summary><strong>Q3: How do you guarantee that an LLM outage never drops or delays a user's 15-minute notification digest?</strong></summary>
<p><strong>Answer:</strong> Enforce a strict timeout (e.g., 2s) and a <strong>Circuit Breaker</strong> that falls back to a deterministic count/title template (e.g., <em>"You have 6 new notifications in 2 channels"</em>) whenever the LLM is slow or unavailable.</p>
</details>

---

### Sources & References
- **[1]** Alex Xu, *System Design Interview (Vol. 1)*, Chapter 10: Design a Notification System — [ByteByteGo](https://bytebytego.com/)
- **[2]** AWS Builders' Library, *Timeouts, Retries, and Backoff with Jitter* — [aws.amazon.com/builders-library](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
- **[3]** Chip Huyen, *AI Engineering* (2025) — Latency Fallbacks, Batching & Deterministic Guardrails
- **[4]** OpenAI Platform Documentation, *Batch API: Asynchronous High-Throughput Workloads at 50% Lower Cost* — [platform.openai.com/docs/guides/batch](https://platform.openai.com/docs/guides/batch)
- **[5]** Rohit Ghumare et al., *AI Engineering from Scratch — Production LLM Cost, Batching & Guardrail Trade-Offs* — [aiengineeringfromscratch.com/interviews](https://aiengineeringfromscratch.com/interviews)
