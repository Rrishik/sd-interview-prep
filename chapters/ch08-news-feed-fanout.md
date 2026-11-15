# Chapter 8: News Feed & The Celebrity Fan-Out Problem (Meta & X)

*Part II · Classic System Design Stories · 8 min core · 13 min with deep dives*

Suppose you are designing the home timeline for X (Twitter), Instagram, or LinkedIn.

Your system has two jobs that look simple on paper:
1. **Write (`POST /post`):** A user publishes a post.
2. **Read (`GET /feed`):** A user opens the app and wants to see the latest 50 posts from the 500 people they follow, sorted newest-first, in **under `100 ms`** [1].

Why does a naive SQL `JOIN` (`SELECT * FROM posts WHERE author_id IN (SELECT followee_id FROM follows WHERE follower_id = 'Alice') ORDER BY created_at DESC LIMIT 50`) collapse at scale?
Because at `300,000 feed reads per second`, asking a database to look up 500 authors, gather all their posts from disk, and sort them on every single page load melts your database cluster [1, 2].

So engineers invented **Fan-Out on Write**—and immediately ran straight into the **Celebrity Fan-Out Problem**.

---

### 1) Push (Fan-Out on Write) vs. Pull (Fan-Out on Read)

Look at **Panel B** of our Core Case Studies diagram in Chapter 7. There are two opposite ways to build a timeline [1, 2]:

- **Approach 1: Fan-Out on WRITE (Push Model):**
  Every user has a pre-computed **Inbox List** of `post_id`s sitting in **Redis** (`LPUSH feed:user_id <post_id>`, trimmed to the latest 800 IDs with `LTRIM`).
  When Bob (who has **300 followers**) publishes a post, a Kafka worker looks up Bob's 300 followers and appends `post_id` to all 300 Redis lists in the background.
  - **Read speed:** **Blazing fast (`O(1)`, `< 5 ms`)**—when Alice opens the app, she just reads her pre-built Redis list!
  - **The Celebrity Problem:** What happens when Taylor Swift (who has **100 million followers**) posts a photo? Pushing 1 post into **100 million Redis lists** triggers 100 million writes, creating a massive queue lag and wasting RAM on millions of followers who haven't opened the app in months!

- **Approach 2: Fan-Out on READ (Pull Model):**
  When Taylor Swift posts, we write her post **once** to her own author timeline (`author_posts:Taylor`). We do **zero fan-out** on write.
  When Alice opens her app, the Feed Service fetches her pre-computed Redis list (which has posts from her normal friends) **AND** pulls the latest posts from the few celebrities Alice follows, merging the two sorted lists in memory in `< 15 ms`!

---

### 2) The Hybrid Fan-Out Architecture (How Production Feeds Actually Work)

Never pick pure Push or pure Pull—always combine them into the **Hybrid Fan-Out Architecture** [1, 2]:

1. **Normal Users (`< 10,000 followers`):** Use **Fan-Out on Write (Push)** via Kafka workers into followers' Redis `ZSET` / `List` caches (storing only lightweight `(post_id, author_id, timestamp)` tuples, never full post JSON!).
2. **Celebrities / Hot Accounts (`>= 10,000 followers`):** Use **Fan-Out on Read (Pull)**. Write once to the celebrity's cache; when an active follower loads their feed, merge the celebrity's recent posts at read time.
3. **Hydration via Two-Tier Cache:** Once the Feed Service has the final sorted list of 20 `post_id`s, it batch-fetches (`MGET`) the full post text, image CDN URLs, and like counts from a **Post & User Cache** [1, 3].

:::deepdive Modern AI Feed Ranking: The 4-Stage Retrieval-to-Re-Ranking Funnel | +5 min

No major social feed (`X "For You"`, `Instagram`, `YouTube`, `LinkedIn`) serves pure chronological order anymore—nor can you run a heavy neural network over `100 million` candidate posts inside a **`150 ms`** feed budget! Production AI feeds narrow candidates through a **4-Stage Funnel** [4, 5, 6]:

| Funnel Stage | Input -> Output | Latency Budget | Model & Systems Architecture |
| :--- | :--- | :--- | :--- |
| **1. Candidate Sourcing** *(In-Network + Out-of-Network)* | `100M+` -> **`~1,500` posts** | `~25 ms` | Parallel merge of **In-Network Hybrid Redis Fan-Out** (`~750` followed posts) + **Two-Tower User/Item Embedding ANN (`HNSW`)** (`~750` discovery posts) [4, 5]. |
| **2. Light Pre-Ranker** | `1,500` -> **`~250` posts** | `~15 ms` | Cheap **distilled GBDT / logistic / tiny MLP** using cached static features to prune obvious low-interest candidates before expensive feature hydration [5]. |
| **3. Heavy Multi-Task Ranker** *(`DLRM` / MaskNet)* | `250` -> **`~50` posts** | `~45 ms` | GPU-batched **Multi-Task Deep Network** [6] predicting calibrated probabilities for both positive and negative heads: `Score = w1·P(like) + w2·P(reply) + w3·E[dwell_sec] - w4·P(mute) - w5·P(report)` [4, 5]. |
| **4. Diversity, Fatigue & Exploration Re-Ranker** | `50` -> **`20`hydrated posts** | `~10 ms` | Deterministic heuristics: **author-diversity penalty** (never show 4 posts in a row from Bob), seen-post Bloom filter dedup, and a **`2%` cold-start creator exploration slot** [4, 5]. |

**Why Two-Tower Models Power Stage 1 (`100M -> 1,500`) [4]:** Because the **User Tower** `u(user_features)` and **Item Tower** `v(post_features)` only interact via a final dot product `u · v`, item embeddings for millions of posts can be **pre-computed offline/nearline** and indexed in `HNSW`—whereas the **Heavy Cross-Feature Ranker** (`Stage 3`) crosses user × author × real-time context features dynamically and can only afford `~250` items [4, 6]!

:::

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why should a user's Redis feed cache store only <code>post_id</code> integers instead of full post JSON objects?</strong></summary>
<p><strong>Answer:</strong> Two reasons: (1) <strong>RAM savings</strong> (an 8-byte ID is 100× smaller than a 1 KB JSON object duplicated across millions of followers), and (2) <strong>consistency</strong> (if an author edits a post or its like count changes, updating one central <code>post:id</code> cache entry immediately updates everyone's feed).</p>
</details>

<details>
<summary><strong>Q2: At what follower threshold do systems like X/Instagram typically switch from Push (fan-out on write) to Pull (fan-out on read)?</strong></summary>
<p><strong>Answer:</strong> Typically around <strong>10,000 to 50,000 followers</strong>, where fan-out write amplification begins to outweigh the tiny cost of merging a few celebrity timelines at read time.</p>
</details>

<details>
<summary><strong>Q3: How do you avoid wasting Redis RAM on the pre-computed feeds of 500 million inactive users who only open the app once a month?</strong></summary>
<p><strong>Answer:</strong> Put a <strong>TTL (e.g., 7 days)</strong> on Redis feed lists (or only push to users active in the last 7 days). If an inactive user logs in after a month, rebuild their feed on the fly from Cassandra/Postgres and warm the cache.</p>
</details>

---

### Sources & References
- **[1]** Alex Xu, *System Design Interview (Vol. 1)*, Chapter 11: Design a News Feed System — [ByteByteGo](https://bytebytego.com/)
- **[2]** Martin Kleppmann, *Designing Data-Intensive Applications (DDIA)*, Chapter 1: Twitter Timeline Fan-Out Case Study (`4.6k writes/sec` vs `300k reads/sec`)
- **[3]** Meta Engineering, *Serving Facebook Multifeed: Efficiency, Performance, and Fast Builds* — [engineering.fb.com](https://engineering.fb.com/)
- **[4]** Paul Covington, Jay Adams & Emre Sargin (Google), *Deep Neural Networks for YouTube Recommendations (Two-Stage Candidate Generation & Ranking)* (ACM RecSys 2016) — [research.google/pubs/45530](https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/45530.pdf)
- **[5]** X / Twitter Engineering, *The Recommendation Algorithm (`For You` Sourcing, Light Ranker, Heavy Ranker & Visibility Filters)* — [github.com/twitter/the-algorithm](https://github.com/twitter/the-algorithm)
- **[6]** Maxim Naumov et al. (Meta), *Deep Learning Recommendation Model for Personalization and Recommendation Systems (`DLRM`)* (2019) — [arxiv.org/abs/1906.00091](https://arxiv.org/abs/1906.00091)
