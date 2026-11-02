# System Design Interview Prep: 4-Week Plan (Senior SDE / SDE2-3)

**Profile:** 6.5 yrs. Chromium C++, TS/React, Python, .NET backend for AI services on Edge. Strong coding bar; focusing now on leveling up distributed systems and AI architecture for Senior SDE / SDE2-3 roles across Big Tech and top product companies.
**Budget:** 4 weeks x 6-8 hrs (about 28 hrs). **Mix:** about 90% core design, about 10% AI/LLM systems (about 3 hrs).
**Format:** Conversational. I play the interviewer. Each topic ends with a quiz. Everything is tracked in this folder and revised weekly.

## Senior / SDE2-3 calibration (hypotheses to test in Mock 0)
Moving from client-heavy + service development to Senior/SDE2-3 interviews across Google, Meta, Microsoft, Amazon, and top product companies usually requires sharpening four areas:
1. Pinning functional/non-functional requirements and back-of-envelope numbers before drawing boxes.
2. Going 2 levels deeper on backend internals (storage engine choice, partitioning/sharding, replication, consistency, and failure modes).
3. Defending trade-offs with concrete numbers ("why X over Y at this QPS/latency, and what breaks first").
4. Demonstrating senior ownership: observability, graceful degradation, cost, and rollout safety.
-> Mock 0 on Day 1 is a baseline diagnostic. We will re-weight the plan every week based on your progress.

## 80/20: the topics that cover most questions
Recent sources show the same ~12 problems recurring across Amazon, Google, Meta and Microsoft, so they are the core set.

**Building blocks (Week 1):** the 8-step answer framework, back-of-envelope estimation, API + data modeling, SQL vs NoSQL and indexing, sharding/replication/consistency (CAP/PACELC), caching (aside/through/back, invalidation, stampede), queues/streams (Kafka/SQS, at-least-once, idempotency, DLQ), load balancing/CDN, rate limiting, and reliability/observability (SLOs, retries, backoff, circuit breakers, multi-region).

**Core case studies (ordered by frequency x teachable patterns):**
| # | Case | Patterns it drills |
|---|------|--------------------|
| 1 | URL shortener | ID generation, read-heavy caching, DB choice |
| 2 | Rate limiter | Token bucket, distributed counters, Redis |
| 3 | Notification system | Fan-out, queues, retries, idempotency, priority |
| 4 | News feed | Fan-out on write vs read, ranking, hot keys |
| 5 | Chat (WhatsApp) | WebSockets, ordering, presence, delivery guarantees |
| 6 | Distributed cache / KV store | Consistent hashing, replication, quorum |
| 7 | File storage / video upload+stream | Chunking, blob store, CDN, async processing |
| 8 | Ticketing / e-commerce order + payments | Inventory contention, sagas, idempotency, exactly-once illusions |
| 9 | Typeahead / search | Tries, inverted index, ranking |
| 10 | Ride-sharing (Uber) | Geospatial index, matching, real-time location |
| 11 | Web crawler / job scheduler | Queues, politeness, dedup, leases |
| 12 | Collaborative doc editing | OT/CRDT, conflict resolution (stretch) |
| Bonus (your edge) | Browser sync across devices / telemetry pipeline | Leverages your Edge experience. Good "tell me about a system you built" material. |

**Company-style rotation (across mocks):**
We rotate interviewer styles so you are ready for any top company:
- **Google style:** deep storage/distributed-systems internals, custom data structures, scale bottlenecks.
- **Meta style:** product-driven API design, real-time fan-out, caching at massive read scale.
- **Microsoft / AI-product style:** pragmatic end-to-end architecture, multi-tenant SaaS, hybrid cloud + LLM/RAG integration.
- **Amazon / Uber / Stripe style:** operational rigor, idempotency, failure recovery, and senior ownership trade-offs.

**AI track (about 10%):**
| # | Topic |
|---|-------|
| A1 | LLM app fundamentals: tokens, context, latency/cost, streaming, prompt vs fine-tune vs RAG |
| A2 | RAG internals: chunking, embeddings, hybrid retrieval (BM25 + dense), reranking, vector DB choice |
| A3 | Design an enterprise RAG chatbot: scale, latency, security (ACLs), caching |
| A4 | LLM gateway/platform: routing, semantic cache, rate limits, cost controls, fallbacks |
| A5 | Agents: tool use, planning, memory, failure modes, guardrails, prompt injection |
| A6 | Evaluation: offline/online evals, LLM-as-judge, hallucination detection, regression testing |

## Weekly schedule (about 7 hrs/week)
| Week | Theme | Sessions | AI slice (about 45 min) |
|------|-------|----------|-------------------------|
| **1** | Foundations + diagnostic | Mock 0 (diagnostic, 45 min), building blocks 1-5 with quizzes, cases #1-2 | A1 |
| **2** | Data-heavy and fan-out systems | Cases #3-6 (mini-mock each: 25 min), weekly cumulative quiz | A2 |
| **3** | Transactional, geo, media, search | Cases #7-10, one full 45-min mock, weekly cumulative quiz | A3, A4 |
| **4** | Interview simulation | 3 full mocks (random case from the bank, curveballs), weak-spot drills, A5 and A6 mock, final scorecard + next-steps plan | A5, A6 |

## Session protocol (conversational)
**Topic session (about 60-75 min):** (1) 10-min primer from me with the "why", (2) you answer a guided design with me probing, (3) I reveal a reference design and trade-offs, (4) **quiz (5 questions)**.
**Quiz format:** 3 conceptual, 1 estimation, 1 "what breaks?" failure scenario. Scored 0-4 per question. Misses go to `progress.md`, and are re-quizzed after 2 days and again a week later.
**Full mock (45 min simulated):** I act as interviewer with an ambiguous prompt. Phases: requirements (5 min), estimation (5), API + data (5), HLD (10), deep dive (15), wrap-up & senior trade-offs (5). I inject curveballs ("traffic 10x", "region fails", "cut cost by 50%"). Afterwards you get a scorecard.

**Scorecard (1-5 each):** requirements and scoping, estimation, API/data model, HLD clarity, deep-dive depth, trade-offs (with numbers), reliability/ops, communication, senior ownership signal. Targets: >= 4 in all by Mock 4.

## Continuous improvement loop (weekly, about 30 min)
See [weekly-refresh.md](./weekly-refresh.md). In short, every week we:
1. **Harvest:** pull fresh interview experiences from the sources in [sources.md](./sources.md) (Reddit, Blind, LeetCode Discuss, IGotAnOffer, Design Gurus, etc.).
2. **Extract** the questions into [question-bank.md](./question-bank.md) with company, level, date and a frequency tally.
3. **Re-rank** topics by frequency x your weakness score from `progress.md`.
4. **Update** the next week's plan (add, swap or retire cases) and log the change in the changelog.
5. **Refresh** sources: add new ones, drop stale or low-signal ones.
This can be automated as a scheduled Copilot task once you approve it (see the confirmations list).

## Timeline

**Flow:** `Week 1 (Mock 0 + Foundations + Cases 1-2 + AI A1) -> Week 2 (Cases 3-6 + AI A2) -> Week 3 (Cases 7-10 + AI A3-A4 + Full Mock #1) -> Week 4 (3 Full Mocks + AI A5-A6 + Final Scorecard)`

Interactive whiteboard diagram: [00-timeline.excalidraw](./diagrams/00-timeline.excalidraw) (open in VS Code with the Excalidraw extension).

## Why this order
1. Mock 0 first: it shows your real gaps before you invest time.
2. Building blocks before cases: every case reuses them.
3. Simple cases (URL, rate limiter) before fan-out and transactional cases: difficulty grows step by step.
4. Mocks last: you need the patterns in memory before you test under time pressure.

## Files
- [01-week1-learning-guide.md](./01-week1-learning-guide.md): Async reading guide (Mock 0 fixes, Kafka partitions & hot keys, Redis data structures, DB keys, estimation & LLM math)
- [sources.md](./sources.md): vetted source registry
- [question-bank.md](./question-bank.md): questions seen, tallied by frequency
- [progress.md](./progress.md): quiz and mock scores, missed-question log
- [weekly-refresh.md](./weekly-refresh.md): refresh procedure and changelog
- [inbox/manual-drops.md](./inbox/manual-drops.md): drop URLs or raw pasted interview posts here anytime
