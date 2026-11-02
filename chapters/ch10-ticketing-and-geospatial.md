# Chapter 10: High-Contention Flash Sales (Ticketmaster) & Geospatial Matching (Uber)

*Part II · Classic System Design Stories · 9 min read*

What do **buying a concert seat on Ticketmaster** and **matching a rider with the closest Uber driver** have in common?

Both are **high-contention coordination problems** where thousands of users are competing for or updating the exact same physical resource in the real world at the exact same second [1, 2].

Let us solve both side by side.

---

### Part A: Ticketmaster & The 5-Minute Seat Hold Pattern

Picture **Seat 9A** at a stadium. At `10:00:00 AM`, **50,000 fans** click Seat 9A at the exact same millisecond.
We have two strict requirements:
1. **Zero double-booking:** Seat 9A can be sold to **at most one person**.
2. **The 5-minute checkout timer:** Once Alice clicks Seat 9A, she gets **5 minutes** to type her credit card number. During those 5 minutes, nobody else can take Seat 9A—*unless* Alice abandons checkout, in which case Seat 9A must automatically become available again at `10:05:00`!

#### Why Database Transactions Alone Fail
You *cannot* keep a PostgreSQL `BEGIN ... SELECT FOR UPDATE` transaction open for **5 minutes** while a human types their credit card—holding row locks and database connections open for 5 minutes exhausts the database connection pool in 2 seconds!

#### The Two-Phase Reservation Architecture (Look at Panel D in Chapter 7)
1. **Phase 1 — Instant Atomic Hold in Redis (or Optimistic DB Status with `expires_at`):**
   When 50,000 fans click Seat 9A, the API executes one atomic command in Redis:
   `SET hold:event_1:seat_9A "Alice" NX EX 300`
   - **Alice (1st microsecond):** Gets `1 (OK)`! Seat 9A is locked for Alice for exactly `300 seconds` (5 minutes).
   - **The other 49,999 fans:** Get `0 (Taken)` in `< 1 ms` without ever touching PostgreSQL!
2. **Phase 2 — Payment & ACID Database Commit:**
   When Alice submits her credit card at `10:02:15`, the Checkout Service verifies that `hold:event_1:seat_9A` still belongs to `"Alice"` and commits the final purchase in PostgreSQL using **Optimistic Concurrency Control**:
   `UPDATE seats SET status = 'BOOKED', owner_id = 'Alice' WHERE seat_id = '9A' AND status = 'AVAILABLE';`
   If `rows_updated == 1`, we charge/capture payment and delete the Redis hold key. If Alice closes her browser and never pays, the Redis TTL (`EX 300`) expires automatically at `10:05:00`, freeing the seat with zero cron-job lag [1].

---

### Part B: Uber Geospatial Matching (Why `WHERE lat BETWEEN ...` Fails)

Now switch to **Uber / DoorDash**: 1 million active drivers send a GPS ping `(latitude, longitude)` every **4 seconds** (`250,000 location writes/sec`). When a rider opens the app, how do you find the **10 closest drivers within 2 km** in `< 10 ms`? [2]

#### Why 2D SQL Indexes (`B-Tree on lat, lon`) Are Slow
A B-Tree index can only sort in **one dimension (`1D`)**. If you index `(lat, lon)`, the database can filter the latitude band (`lat BETWEEN 37.77 AND 37.79`), which spans a strip **all the way around the Earth**, and then has to scan every longitude inside that strip!

#### How Geohash, Quadtrees & Uber H3 Turn `2D` into `1D`
To make 2D map lookups `O(1)`, geospatial systems divide the Earth's surface into **discrete grid cells**, where every cell has a single **1D string or 64-bit integer ID** [2, 3]:

| Grid System | How It Divides the Map | Best For | Trade-off |
| :--- | :--- | :--- | :--- |
| **Geohash** (Base32 string, e.g. `9q8yyk`) | Recursively splits rectangles into 32 sub-rectangles. Shared prefix = nearby! | Simple Redis `GEOADD` / `GEORADIUS` lookups. | Cells distort near the poles; two points `10 meters` apart across a cell border can have totally different prefixes (always query the **center cell + 8 neighbors**!). |
| **Quadtree** (In-Memory Tree) | Recursively splits a square into **4 child squares** whenever a square has `> K` (e.g. 100) drivers. | **Dense vs. sparse cities** (tiny cells in Manhattan, huge cells in the desert). | Tree rebalancing on high write rates requires care (partition the tree across regions). |
| **Uber H3** (Hexagonal Hierarchical Index) | Covers the globe in **hexagons** at 16 resolutions. | **Ride matching & surge pricing** (used by Uber). | In a hexagon grid, **all 6 neighbor cells are the exact same distance from the center** (unlike squares, where diagonal corners are `1.41×` farther!). |

**The Uber Live Location Pipeline:**
1. Driver pings `(lat, lon)` every 4s -> server converts `(lat, lon)` to **H3 Hexagon ID (`res 9`)** in nanoseconds.
2. Update Redis in memory: move driver to `SADD h3:cell_8928308280fffff driver_42` and update `HSET driver_loc:42 lat ... lon ... EX 15`.
3. When a rider requests a ride, compute the rider's H3 cell + its **6 adjacent hexagon ring (`kRing(cell, 1)`)**, fetch all active drivers in those 7 cells from Redis in `< 2 ms`, and rank by ETA [2].

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why is holding a PostgreSQL <code>SELECT ... FOR UPDATE</code> lock while waiting 5 minutes for a user to enter credit card details an anti-pattern?</strong></summary>
<p><strong>Answer:</strong> Long-lived database locks tie up scarce database connections and worker threads for minutes; a few hundred concurrent checkouts will exhaust the connection pool and freeze the entire database.</p>
</details>

<details>
<summary><strong>Q2: Why do geospatial queries always check the user's grid cell PLUS its 6 (H3) or 8 (Geohash) neighboring cells?</strong></summary>
<p><strong>Answer:</strong> Because of the <strong>boundary problem</strong>: a rider standing 5 meters from the edge of Cell A is much closer to a driver just across the border in Cell B than to a driver on the far side of Cell A.</p>
</details>

<details>
<summary><strong>Q3: Why did Uber choose Hexagons (H3) over Squares (Geohash/Quadtree) for surge pricing and ETA matching?</strong></summary>
<p><strong>Answer:</strong> Every neighbor of a hexagon shares an edge and has the <strong>exact same center-to-center distance</strong> in all 6 directions, eliminating the corner-vs-edge distance distortion of squares.</p>
</details>

---

### Sources & References
- **[1]** Alex Xu, *System Design Interview (Vol. 2)*, Chapter 1: Proximity Service, Chapter 2: Nearby Friends & Chapter 7: Hotel/Ticket Reservation System — [ByteByteGo](https://bytebytego.com/)
- **[2]** Uber Engineering, *H3: Uber's Hexagonal Hierarchical Spatial Index* — [uber.com/blog/h3](https://www.uber.com/blog/h3/)
