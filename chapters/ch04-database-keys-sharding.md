# Chapter 4: Database Keys, Sharding & Where Your Data Actually Lives

*Part I · Core Building Blocks · 9 min read*

Every software engineer knows how to write `PRIMARY KEY (id)` in a SQL migration.

Yet when a table grows to 50 billion rows, a simple question changes everything: *"Alice opens her Notification Inbox to view her 20 newest alerts out of 50 billion total rows. How does your database find those 20 rows in 3 milliseconds without scanning the whole cluster?"*

If your primary key is just `notification_id = UUID()`, your database has **no idea which machine holds Alice's rows**. It has to send a **"scatter-gather" query to every single database shard in your cluster**, wait for the slowest shard to respond, and merge the results. At 30,000 QPS, scatter-gather kills your cluster [1].

To fix this forever, you only need to understand **two keys** and **two storage engines**.

{{diagram:02-database-sharding-keys.excalidraw}}

---

### 1) The Composite Primary Key: Partition Key vs. Sort Key

In distributed databases (like Cassandra, DynamoDB, ScyllaDB, or sharded PostgreSQL), a table's primary key is actually a **two-part physical address** [1, 2]:

`PRIMARY KEY ( (user_id), created_at )`

1. **The Partition Key (`user_id`) — *"Which Machine?"***
   When a write or read arrives, the database runs a fast hash function on `user_id` (`Murmur3("user_42") -> Token 74`). That hash points to **one exact storage node** (`O(1)` network hop). Every single notification belonging to `user_42` lives on that same node.
2. **The Sort / Clustering Key (`created_at DESC`) — *"Where on Disk?"***
   Inside that storage node, all rows for `user_42` are physically sorted on disk by `created_at` from newest to oldest.

Now trace what happens when Alice opens her inbox and runs:
`SELECT * FROM notifications WHERE user_id = 'user_42' ORDER BY created_at DESC LIMIT 20;`

- **Step 1:** Hash `user_42` -> hop straight to **Shard #3** (1 machine, not 50!).
- **Step 2:** Seek to the start of `user_42` on disk and read **20 contiguous rows** sitting right next to each other (`1 disk seek`, `< 3 ms` latency!).

---

### 2) B-Trees vs. LSM-Trees: Why Postgres and Cassandra Make Opposite Trade-Offs

Once your request reaches Shard #3, how does the database actually write and read bytes on the SSD? Almost every database on earth uses one of two storage engines under the hood [1]:

| Feature | **B-Tree** (PostgreSQL, MySQL InnoDB, SQLite) | **LSM-Tree** (Cassandra, ScyllaDB, DynamoDB, RocksDB) |
| :--- | :--- | :--- |
| **How Writes Work** | Finds the exact `16 KB` page on disk and **overwrites it in place** (plus a WAL log). | Appends sequentially to a disk log (`WAL`) and inserts into a sorted **in-memory tree (`MemTable`)**. Never overwrites disk in place! |
| **What Happens When RAM Fills Up** | Flushes dirty `16 KB` pages back to their scattered locations on disk (random I/O). | Flushes the sorted `MemTable` to disk as a brand-new, immutable **SSTable (Sorted String Table)** file; background **Compaction** merges old SSTables. |
| **Read Speed** | **Faster & more predictable (`O(log N)`)** — there is only 1 canonical B-Tree to traverse. | **Slightly slower on cold reads** — may need to check the `MemTable` plus several SSTables on disk (uses **Bloom Filters** in RAM to skip SSTables that don't have the key). |
| **Write Speed** | **Good (`~5k–10k/sec` per node)** — limited by random disk I/O, page splits, and row locks. | **Massive (`~50k–100k+/sec` per node)** — every write is a pure sequential append + RAM insert with zero row locks. |
| **Best Use Case** | User accounts, billing, orders, permissions, ACID transactions. | High-write event logs, chat messages, notification history, IoT time-series. |

---

### 3) Consistent Hashing: How to Add a Database Shard Without Moving 99% of Your Data

Earlier we saw how Kafka hashes `Hash(key) % N`. That works when `N` is a fixed number of logical partitions.

But what if `N` is a set of **physical cache or database servers**, and Server #4 suddenly crashes (changing `N` from `10` to `9`)?
If you use `Hash(key) % N`, changing `N` from `10` to `9` changes the remainder of **90% of all keys in your system**! Every cache lookup misses at the exact same second, causing a **thundering herd** that crushes your backend database [2].

**Consistent Hashing** fixes this by bending the hash space (`0` to `2^32 - 1`) into a **circle (ring)** [2, 3]:
1. You place each server at multiple points around the circle (**Virtual Nodes / vnodes**).
2. To find which server owns `user_42`, you hash `user_42` onto the circle and walk **clockwise** until you hit the first server.
3. If **1 server out of 10** crashes (or you add an 11th server), only the keys on that immediate arc—**`1 / N` (`~10%`) of the keys**—move to their clockwise neighbor. The other **90% of keys stay untouched!**

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** A **Composite Primary Key** `(user_id, created_at)` is like an **encyclopedia set** where `user_id` tells you **which volume (`Volume M`)** to pull off the shelf, and `created_at` tells you **which page inside Volume M** has today's entries in chronological order.
- **Where the analogy breaks:** If one customer (`Celebrity_X`) writes 500 million entries, `Volume M` grows to the size of a truck (**wide-partition problem**). In Cassandra/DynamoDB, if a single partition grows past ~`100 MB` / `100,000 items`, you must **time-bucket** the partition key: `PRIMARY KEY ((user_id, '2026-03'), created_at)` [4].
- **Real production system:** **Discord** originally stored chat messages in Cassandra keyed by `(channel_id, message_id)`. When massive public channels grew too wide, they bucketed the partition key into 10-day windows: `((channel_id, bucket_10d), message_id)` so no single partition ever grew unbounded [4].

---

### Quick Self-Check

<details>
<summary><strong>Q1: You design a Chat Messages table that must fetch the latest 50 messages in a channel in &lt;5 ms. What should your Partition Key and Sort Key be?</strong></summary>
<p><strong>Answer:</strong> Partition Key: <code>(channel_id, time_bucket)</code> (so all recent messages for one channel live on one node without growing infinitely wide). Sort Key: <code>message_id DESC</code> (using a time-sortable Snowflake/ULID ID) or <code>created_at DESC</code>.</p>
</details>

<details>
<summary><strong>Q2: Why does an LSM-Tree database (like Cassandra or RocksDB) use Bloom Filters in RAM?</strong></summary>
<p><strong>Answer:</strong> Because an LSM-Tree periodically flushes immutable SSTable files to disk, a key might exist in any of several SSTables. A <strong>Bloom Filter</strong> is a tiny bit-array in RAM per SSTable that can say with 100% certainty <em>"Key X is NOT in this file,"</em> avoiding unnecessary disk reads.</p>
</details>

<details>
<summary><strong>Q3: In a 10-node cluster using Consistent Hashing with Virtual Nodes, roughly what fraction of keys must move when you add an 11th node?</strong></summary>
<p><strong>Answer:</strong> Only <strong><code>1 / 11</code> (~9%)</strong> of the keys move to the new node, compared to ~90% with naive <code>Hash(key) % N</code>.</p>
</details>

---

### Sources & References
- **[1]** Martin Kleppmann, *Designing Data-Intensive Applications (DDIA)*, Chapter 3: Storage and Retrieval (B-Trees vs. LSM-Trees) & Chapter 6: Partitioning
- **[2]** Alex Xu, *System Design Interview (Vol. 1)*, Chapter 5: Design Consistent Hashing & Chapter 6: Design a Key-Value Store — [ByteByteGo](https://bytebytego.com/)
- **[3]** Giuseppe DeCandia et al. (Amazon), *Dynamo: Amazon's Highly Available Key-Value Store* (SOSP 2007) — [allthingsdistributed.com](https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf)
- **[4]** Discord Engineering, *How Discord Stores Billions/Trillions of Messages* — [discord.com/blog/how-discord-stores-trillions-of-messages](https://discord.com/blog/how-discord-stores-trillions-of-messages)
