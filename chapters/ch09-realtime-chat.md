# Chapter 9: Real-Time Chat & Presence (WhatsApp, Slack & Discord)

*Part II · Classic System Design Stories · 8 min read*

In most web systems, the client talks first (`HTTP GET/POST`), and the server answers.

In a **Real-Time Chat system** (WhatsApp, Slack, Discord), the problem flips upside down: Alice sends a message from New York, and **100 milliseconds later, Bob's phone in Tokyo must light up**—even though Bob's phone did not make an HTTP request.

Even trickier: you have **10 million users online simultaneously**, connected across **200 stateful Chat Gateway servers**. When Alice's message lands on **Gateway #1**, how does Gateway #1 figure out that Bob's open TCP wire is sitting on **Gateway #74**? [1, 2]

---

### 1) Why HTTP Polling Fails and Stateful WebSockets Win

Let us compare how a server can push a message to Bob's phone [1]:
- **Short Polling:** Bob's phone asks *"Any new messages?"* every 2 seconds. At 10M users, that is `5,000,000 useless HTTP requests/sec` when nobody is even talking!
- **Server-Sent Events (SSE):** A persistent **one-way** HTTP stream (Server -> Client). Great for streaming LLM tokens or live stock tickers, but unidirectional.
- **WebSockets:** A persistent **bi-directional TCP connection** (`ws://` / `wss://`). Both Alice and Bob keep an open WebSocket to a **Chat Gateway Server** so messages flow in both directions in milliseconds with zero HTTP header overhead [1].

---

### 2) The Core Routing Loop: How Gateway #1 Finds Bob on Gateway #74

Look at **Panel C** of the Core Case Studies diagram in Chapter 7. Let us trace a 1-on-1 message from Alice to Bob step by step [1]:

1. **Connection Registration:** When Bob's app connects to `Chat Gateway #74`, Gateway #74 writes Bob's location into a **Redis Session Registry** (a Redis Hash with a 60s heartbeat TTL):
   `HSET session:Bob gateway_id "gw-74" last_seen 1711800000`
2. **Alice Sends a Message:** Alice sends `"Hey Bob!"` over her open WebSocket to `Chat Gateway #1`.
3. **Assign ID & Persist:** Gateway #1 assigns a time-ordered **Snowflake `message_id`**, writes the message to the **Chat DB (Cassandra/ScyllaDB)** keyed by `PRIMARY KEY ((conversation_id, bucket), message_id)`, and acks Alice (`✓ Sent`).
4. **Route to Bob's Gateway:** Gateway #1 looks up `session:Bob` in Redis -> sees `"gw-74"`, and forwards the message directly to `Gateway #74` (via gRPC or **Redis Pub/Sub** channel `user:Bob`).
5. **Push or Fallback:**
   - If Bob is **online**, `Gateway #74` pushes the bytes down Bob's open WebSocket (`✓✓ Delivered`).
   - If Bob is **offline** (`session:Bob` expired), the service pushes a wakeup notification via **Apple APNs / Google FCM**. When Bob opens the app later, his client fetches all messages where `message_id > last_read_id` from Cassandra!

---

### 3) Why "Online / Offline Presence" Is Secretly the Hardest Part

If Bob is in a Slack workspace with `5,000 coworkers`, and every time Bob's network blips we broadcast `"Bob is offline / online"` to all 5,000 coworkers, `1,000 flapping connections` cause `5,000,000 presence fan-out events/sec`!

How do WhatsApp and Slack avoid the **presence storm**? [1]
1. **Heartbeat TTL in Redis:** Bob's client sends a tiny heartbeat every `10 seconds`, refreshing `SET presence:Bob "online" EX 30`. If Bob disconnects, the key simply expires after 30 seconds—no explicit "offline" database write needed!
2. **Lazy / Scoped Subscription:** Only push live presence updates for the **5–10 people currently visible on Alice's screen** (or inside small groups `< 50` members). For giant 10,000-person channels, fetch online counts lazily on demand.

---

### Quick Self-Check

<details>
<summary><strong>Q1: How many open WebSocket connections can a single modern Linux server (e.g., 64 GB RAM) hold simultaneously?</strong></summary>
<p><strong>Answer:</strong> Roughly <strong>50,000 to 100,000+ concurrent idle connections</strong> per server (each idle socket uses ~10–20 KB of kernel/app memory). Note: Inbound connections are NOT capped at 65,535 because TCP sockets are identified by the 4-tuple <code>(client_ip, client_port, server_ip, server_port)</code>.</p>
</details>

<details>
<summary><strong>Q2: In a group chat with 200 members, why do we order messages by a server-assigned Snowflake ID (or per-channel sequence number) instead of the sender's phone clock?</strong></summary>
<p><strong>Answer:</strong> Client phone clocks drift by seconds or minutes (<strong>clock skew</strong>). Using client timestamps would cause replies to appear <em>above</em> the question they are answering.</p>
</details>

<details>
<summary><strong>Q3: What happens when Chat Gateway #74 crashes while holding 50,000 open WebSockets?</strong></summary>
<p><strong>Answer:</strong> All 50,000 clients detect the broken TCP socket and must reconnect with <strong>randomized exponential backoff + jitter</strong> (e.g., waiting <code>rand(1, 15)</code> seconds) so they don't overwhelm the remaining gateways at the exact same millisecond.</p>
</details>

---

### Sources & References
- **[1]** Alex Xu, *System Design Interview (Vol. 1)*, Chapter 12: Design a Chat System — [ByteByteGo](https://bytebytego.com/)
- **[2]** Discord Engineering, *How Discord Handles Millions of Concurrent Voice and Chat Users (Elixir & ScyllaDB)* — [discord.com/blog](https://discord.com/blog)
- **[3]** Slack Engineering, *Flannel: An Application-Level Edge Cache to Make Slack Scale* — [slack.engineering](https://slack.engineering/)
