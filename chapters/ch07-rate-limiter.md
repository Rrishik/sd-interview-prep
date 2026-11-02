# Chapter 7: Distributed Rate Limiter (Token Bucket, Redis Lua & LLM Token Caps)

*Part II · Classic System Design Stories · 8 min read*

Imagine a bug in a customer's retry loop causes their script to call your `POST /checkout` endpoint `50,000 times per second`.

Without a shield at the front door, that single runaway script starves every other customer on your platform. That front-door shield is a **Distributed Rate Limiter** [1, 2].

{{diagram:03-core-case-studies.excalidraw}}

---

### 1) The Four Classic Algorithms (And Why Token Bucket Wins)

Look at **Panel A** in the diagram above. When comparing rate-limiting algorithms, you only need to contrast four behaviors [1]:

| Algorithm | How It Works | Pros | The Fatal Flaw / Trade-off |
| :--- | :--- | :--- | :--- |
| **1. Token Bucket** | A bucket holds up to `B` tokens (burst size) and refills at `R` tokens/sec. Every request costs `1` token. | **Allows short legitimate bursts** while enforcing average rate; tiny memory (`2 numbers` per user!). | Requires atomic read-refill-decrement in Redis (`Lua script`). |
| **2. Leaky Bucket** | Requests enter a FIFO queue of size `B` and drip out to workers at a strictly constant rate `R`. | **Smooths traffic into a flat line** for fragile downstream databases. | A burst of traffic sits waiting in queue instead of finishing immediately. |
| **3. Fixed Window Counter** | `INCR user_42:10_01` with `EXPIRE 60`. Max 100 requests per minute window. | **Simplest (`1 integer` in Redis).** | **Boundary 2× burst bug:** A user sends 100 requests at `10:00:59` and 100 more at `10:01:01` (`200 requests in 2 seconds`!). |
| **4. Sliding Window Log** | Store every request's timestamp in a Redis Sorted Set (`ZSET`), drop timestamps older than `NOW - 60s`, count remaining (`ZCARD`). | **100% mathematically accurate** across any rolling window. | **High RAM cost** (`O(N)` timestamps stored per user—bad if limit is 10,000 req/min). |

**The Verdict:** Default to **Token Bucket** for almost all API rate limiting (used by Stripe and Amazon AWS) because real users naturally click in short bursts [1, 2].

---

### 2) How to Avoid Race Conditions Across 20 API Gateways (Redis Lua)

Suppose your Token Bucket allows `10 requests/sec`, and `user_42` currently has `1` token left. Two requests from `user_42` hit **API Gateway #1** and **API Gateway #2** at the exact same millisecond.

If both gateways read `tokens = 1` from Redis, compute `1 - 1 = 0` in application code, and write `0` back to Redis, **both requests succeed** even though only 1 token existed!

How do Stripe and Cloudflare make Token Bucket 100% atomic across 20 gateways without slow locks?
They send a **5-line Lua script (`EVALSHA`)** to Redis [2]:
1. Read `{tokens, last_refill_ts}` from the user's Redis Hash.
2. Calculate newly earned tokens: `tokens = min(capacity, tokens + (now - last_refill_ts) * refill_rate)`.
3. If `tokens >= cost`, subtract `cost`, save `{tokens, now}`, and return `1 (ALLOWED)`. Else return `0 (HTTP 429 Too Many Requests)` with `Retry-After` header.

Because Redis runs the entire Lua script inside its **single thread** in ~`50 microseconds`, no two gateways can ever interleave!

---

### 3) AI Engineering Twist: Request Rate Limiting vs. Token Rate Limiting (TPM)

If you are building an **LLM Gateway** (wrapping OpenAI, Anthropic, or internal vLLM GPU clusters), counting **HTTP Requests Per Minute (RPM)** is not enough [3]:
- User A sends `10 requests` with `20 tokens` each = `200 tokens` (costs 1 millisecond of GPU time).
- User B sends `10 requests` with `100,000 tokens` each = `1,000,000 tokens` (saturates the entire GPU cluster!).

How do you rate-limit an LLM Gateway fairly?
You run a **Dual Token Bucket** in Redis Lua:
1. **Bucket 1 (RPM):** Deduct `1` request token.
2. **Bucket 2 (TPM — Tokens Per Minute):** Estimate input tokens (`len(prompt) / 4` + `max_output_tokens`) upfront and deduct from the user's **TPM bucket**; once the streaming response finishes, refund any unused output tokens back into the bucket [3].

---

### Quick Self-Check

<details>
<summary><strong>Q1: What is the "boundary burst bug" in a Fixed Window Counter rate limiter?</strong></summary>
<p><strong>Answer:</strong> A user can send the full quota right at the end of minute 1 (e.g., <code>10:00:59</code>) and another full quota at the start of minute 2 (<code>10:01:00</code>), pushing <strong><code>2×</code> the allowed traffic</strong> through in 2 seconds.</p>
</details>

<details>
<summary><strong>Q2: What should your API Gateway do if the Redis Rate Limiter cluster temporarily becomes unreachable?</strong></summary>
<p><strong>Answer:</strong> Discuss <strong>Fail-Open vs. Fail-Closed</strong>: most consumer/payment APIs <strong>fail open</strong> (allow traffic through while falling back to a local in-memory per-gateway token bucket) so a Redis blip doesn't take down the whole company.</p>
</details>

<details>
<summary><strong>Q3: When returning HTTP 429, what HTTP headers should your rate limiter include?</strong></summary>
<p><strong>Answer:</strong> <code>X-RateLimit-Limit</code>, <code>X-RateLimit-Remaining</code>, and <code>Retry-After</code> (seconds until the bucket refills enough tokens).</p>
</details>

---

### Sources & References
- **[1]** Alex Xu, *System Design Interview (Vol. 1)*, Chapter 4: Design a Rate Limiter — [ByteByteGo](https://bytebytego.com/)
- **[2]** Paul Tarjan (Stripe), *Scaling your API with rate limiters (Redis Token Bucket + Lua)* — [stripe.com/blog/rate-limiters](https://stripe.com/blog/rate-limiters)
- **[3]** Cloudflare Engineering, *How we built Cloudflare's Distributed Rate Limiting* — [blog.cloudflare.com](https://blog.cloudflare.com/)
