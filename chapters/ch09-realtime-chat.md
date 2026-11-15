# Chapter 9: Real-Time Chat & Presence (WhatsApp, Slack & Discord)

*Part II · Classic System Design Stories · 8 min core · 17 min with deep dives*

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
2. **Lazy / Scoped Subscription:** Only push live presence updates for the **5–10 people currently visible on Alice's screen** (or inside small groups `< 50` members). For giant 10,000-person channels, fetch online counts lazily on demand or via edge caches [3].

:::deepdive Streaming AI Copilots in Chat: Multi-Device Fan-Out, Stop-Button Cancel & ACLs | +5 min

Modern chat interviews (`Slack AI`, `Discord Bots`, `ChatGPT Multi-Device Sync`) frequently add: *"Now embed a streaming `@AI` assistant inside 1-on-1 and group channels—what changes?"* [4, 5]:

1. **Never Write Every Streamed Token to Cassandra/ScyllaDB (`100×` Write Amplification Trap) [4]:**
   - A `400-token` LLM answer emits `~120` SSE chunks over `4 seconds`. Writing `120` updates to ScyllaDB melts disk compactions!
   - Instead: (a) Persist **1 placeholder row** (`status = STREAMING, message_id = snow_99`) at `t = 0`, (b) fan out ephemeral `delta` frames (`{message_id, seq, token_chunk}`) every `40 ms` (`~25 Hz` coalesced) over **Redis Pub/Sub -> WebSocket Gateways** so Alice's **phone and laptop both render smooth live typing**, and (c) write the **final assembled text once** (`status = COMPLETED` or `STOPPED`) when generation ends [4, 5].
2. **End-to-End `"Stop Generating"` Cancellation (`< 50 ms`) [5]:**
   - Clicking **Stop** on Alice's phone sends `{"op": "cancel_stream", "message_id": "snow_99"}` over WebSocket -> publishes to Redis control channel `cancel:snow_99` -> triggers the LLM worker's `AbortController` to close the upstream GPU stream immediately, flushing partial text to ScyllaDB so GPU tokens stop burning immediately [5].
3. **Group-Chat `@AI` Context & ACL Scoping Bug:**
   - When Alice invokes `@AI summarize project Phoenix` inside a `50-person` public Slack channel, **do NOT run retrieval using Alice's personal `1:1` DM permissions!** Intersect retrieval ACLs strictly with **the channel's membership scope** (`acl == channel_id OR public`), or `@AI` will leak Alice's private executive DMs to all 50 channel members [5]!

:::

:::deepdive Discord's `ScyllaDB` Request Coalescing & Multi-Device `E2EE` (`Signal Sesame`) | +4 min

1. **Case Study — How Discord Survived Hot-Channel Reads Across Trillions of Messages [4]:**
   - When `100,000` users in a live-event Discord channel scrolled up simultaneously, Cassandra suffered `200 ms+` JVM GC pauses and hot-partition disk stalls.
   - Discord migrated to **`ScyllaDB` (C++ thread-per-core LSM)** *and* inserted a Rust **Data Services layer running `singleflight` request coalescing** sorted by `channel_id` via consistent hashing—so `5,000` concurrent reads for `(channel_99, bucket_42)` collapse into **1 single ScyllaDB query**, dropping `p99` read latency from `40–125 ms` to **`<15 ms`** [4]!
2. **Multi-Device Sync & End-to-End Encryption (`Signal Sesame` / WhatsApp) [6]:**
   - How does Alice see identical chat history across her **Phone, Laptop, and Web tab** when the server cannot read E2EE plaintext? Under **`Signal Sesame`** [6], each *device* (not just each user) publishes its own Identity/PreKey bundle; sending a 1-on-1 message encrypts separate pairwise Double-Ratchet envelopes for Bob's `M` active devices *plus* Alice's own `N - 1` companion devices (or encrypts payload once with a symmetric **Sender Key** in large groups), while each device tracks its own local `last_synced_seq_id` watermark [1, 6].

:::

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
- **[4]** Discord Engineering, *How Discord Stores Trillions of Messages (ScyllaDB Partitioning & Request Coalescing)* — [discord.com/blog/how-discord-stores-trillions-of-messages](https://discord.com/blog/how-discord-stores-trillions-of-messages)
- **[5]** Rohit Ghumare et al., *AI Engineering from Scratch — Streaming LLM Delivery, Cancellation & Multi-Tenant Safety* — [aiengineeringfromscratch.com/interviews](https://aiengineeringfromscratch.com/interviews)
- **[6]** Signal Foundation, *The Sesame Algorithm: Session Management for Asynchronous Multi-Device Message Encryption* — [signal.org/docs/specifications/sesame](https://signal.org/docs/specifications/sesame/)
