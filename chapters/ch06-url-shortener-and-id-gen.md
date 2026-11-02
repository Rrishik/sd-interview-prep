# Chapter 6: URL Shortener & Distributed ID Generation (TinyURL & Snowflake)

*Part II · Classic System Design Stories · 7 min read*

At first glance, a URL shortener (`https://tinyurl.com/2b9kLp1` -> `https://very-long-site.com/...`) sounds almost too simple.

Then you add two production constraints:
1. *"You are generating **10,000 new short URLs per second** across 50 servers in 3 regions, and no two servers can ever pick the same 7-character code."*
2. *"And when a celebrity posts one short link, **200,000 people click it per second**, and every redirect must finish in under `10 ms`."*

Suddenly, this problem tests two foundational skills that show up in almost every distributed system: **collision-free distributed ID generation** and **read-heavy caching** [1, 2].

---

### 1) Why Base62 + 7 Characters Is the Magic Number

A short URL needs characters that are safe inside a web address without percent-encoding:
- `a–z` (26 letters) + `A–Z` (26 letters) + `0–9` (10 digits) = **62 characters (`Base62`)**.

How many characters long should our short code be? Let us check powers of `62`:
- `62^6` = `56.8 billion` IDs.
- **`62^7` = `3.52 trillion` IDs** (at `1,000 writes/sec`, that lasts **111 years**!) [1].

---

### 2) Why MD5 Hashing Collides (And Why Base62(Snowflake ID) Wins)

How do you generate a unique 7-character Base62 string at 10,000 writes/sec without two servers colliding?

- **Trap 1: Random 7-char string or `MD5(long_url)[:7]`:**
  An MD5 or SHA-256 hash is 128–256 bits long. If you chop off the first 7 characters (42 bits), the **Birthday Paradox** guarantees you will hit collisions constantly, forcing you to do a database round-trip (`INSERT ... ON CONFLICT`) and retry loop on every write [1].
- **Solution A: Twitter Snowflake 64-Bit Distributed ID Generator:**
  Every server generates a globally unique **64-bit integer** locally in RAM—with **zero network coordination between servers**—and converts that integer into Base62 [2]:
  - `1 bit`: Sign (`0`)
  - `41 bits`: Milliseconds since custom epoch (~69 years)
  - `10 bits`: Datacenter ID (5 bits) + Machine Worker ID (5 bits = 1,024 servers)
  - `12 bits`: Per-millisecond local counter (`4,096 IDs per millisecond per server`!)
- **Solution B: Range-Allocating Key Generation Service (KGS) / Redis Counter Ranges:**
  If you strictly require **7 characters (`<= 3.5 trillion`)**, a central coordinator (ZooKeeper / etcd / Redis `INCRBY counter 100000`) hands each API server a reserved block of `100,000` numbers at startup (e.g., Server 1 gets `1,000,000–1,099,999`). Server 1 hands them out from local RAM in `O(1)` time and converts each integer to Base62. If Server 1 crashes, you lose at most 100,000 numbers out of 3.5 trillion (`0.000003%`) [1].

---

### 3) `301` vs. `302` Redirects & Surviving the Read Stampede

When a user clicks `https://sho.rt/2b9kLp1`, your read path looks up `2b9kLp1` in **Redis** (`99% cache hit rate`, `< 1 ms`), falls back to the database on a miss, and returns an HTTP redirect [1]:

- **`HTTP 301 (Moved Permanently)`:** The browser caches the redirect forever. Next time the user clicks the link, the browser goes straight to the destination without even asking your server. **Lowest server load**.
- **`HTTP 302 (Found / Temporary Redirect)`:** The browser hits your server every single time so you can track **click analytics** (country, device, referrer) by publishing a click event to Kafka.

**What if a malicious user requests millions of fake short codes (`sho.rt/zzzzzzz`) that do not exist?**
Every request misses Redis and hits your database (**cache penetration attack**). Fix: Keep a **Bloom Filter** in RAM (or cache negative `NOT_FOUND` entries with a short 60s TTL) so nonexistent codes are rejected before touching the database [1].

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** **Range Allocation (KGS)** is like handing each ticket booth at a carnival its own **pre-printed roll of 10,000 numbered raffle tickets** (`#10,000–#19,999` for Booth A, `#20,000–#29,999` for Booth B). Neither booth ever has to walk over and ask the other booth what number they are on.
- **Where the analogy breaks:** Sequential integers (`10001`, `10002`, `10003`) make it easy for competitors to guess the next URL (**enumeration vulnerability**). In production, you obfuscate the integer with a fast reversible **Feistel cipher** or bit-shuffle before Base62 encoding so consecutive IDs look completely random.
- **Real production system:** **Twitter (X)** open-sourced **Snowflake** so thousands of microservices could generate time-ordered 64-bit IDs locally without a single central database bottleneck, a pattern also adopted by **Discord** and **Instagram** [2, 3].

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why is Base62 used for short URLs instead of Base64?</strong></summary>
<p><strong>Answer:</strong> Base64 includes <code>+</code> and <code>/</code>, which have special meanings in URLs and require percent-encoding (<code>%2B</code>, <code>%2F</code>), breaking the clean short link.</p>
</details>

<details>
<summary><strong>Q2: How can 50 servers generate unique IDs at 100,000 IDs/sec without calling a central database on every request?</strong></summary>
<p><strong>Answer:</strong> Either use <strong>Snowflake IDs</strong> (combining timestamp + worker_id + local sequence in 64 bits) or <strong>Range Allocation</strong> (each server leases a block of 100,000 integers in memory and increments locally).</p>
</details>

<details>
<summary><strong>Q3: When should you return HTTP 301 vs HTTP 302 on a short URL redirect?</strong></summary>
<p><strong>Answer:</strong> Return <strong>301</strong> when minimizing server load is the priority (browsers cache it permanently). Return <strong>302</strong> when accurate click analytics or dynamic A/B destination routing is required.</p>
</details>

---

### Sources & References
- **[1]** Alex Xu, *System Design Interview (Vol. 1)*, Chapter 7: Design Unique ID Generator & Chapter 8: Design a URL Shortener — [ByteByteGo](https://bytebytego.com/)
- **[2]** Twitter Engineering, *Announcing Snowflake (64-bit Time-Ordered ID Generation)* — [blog.x.com/engineering](https://blog.x.com/engineering/en_us/a/2010/announcing-snowflake)
- **[3]** Instagram Engineering, *Sharding & IDs at Instagram* — [instagram-engineering.com](https://instagram-engineering.com/sharding-ids-at-instagram-1cf5a71e5a5c)
