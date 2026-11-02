# Chapter 8: News Feed & The Celebrity Fan-Out Problem (Meta & X)

*Part II · Classic System Design Stories · 8 min read*

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
3. **Hydration via Two-Tier Cache:** Once the Feed Service has the final sorted list of 20 `post_id`s, it batch-fetches (`MGET`) the full post text, image CDN URLs, and like counts from a **Post & User Cache** [1].

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
