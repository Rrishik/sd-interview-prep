# Progress Tracker

## Scorecards (1-5; target >= 4 by Mock 4)
| Date | Session | Reqs | Estimation | API/Data | HLD | Deep-dive | Trade-offs | Reliability | Comms | Ownership | Notes |
|------|---------|------|------------|----------|-----|-----------|------------|-------------|-------|-----------|-------|
| 2026-11-01 | Mock 0 (diagnostic: Notification + AI Digest) | 3.5 | 3.5 | 2.5 | 2.5 | 2.0 | 2.5 | 3.5 | 3.5 | 3.0 | Good QPS math, backoff/DLQ, jitter & multi-LLM instincts. Key gap: used DB row locks/polling instead of Kafka partitions + Redis ZSET delayed timers. |

## Quiz scores (each question 0-4, total /20)
| Date | Topic | Score | Weakest area |
|------|-------|-------|--------------|
| 2026-11-01 | Mock 0 Diagnostic Quiz | 6 / 20 | Kafka partitions & hot keys (Q1, Q5) + Redis Lists & ZSET timers (Q3) |

## Missed-question log (re-quiz after 2 days, then 1 week)
| Date | Topic | Question | Correct idea | Re-quiz 1 | Re-quiz 2 |
|------|-------|----------|--------------|-----------|-----------|
| 2026-11-01 | Mock 0 | How to distribute 30k tasks/sec to workers without DB polling or row locks? | Partition Kafka topics by `user_id`; consumer group assigns 1 worker per partition (zero locks). Use NoSQL only for inbox/state log. | Due 2026-11-03 | Due 2026-11-08 |
| 2026-11-01 | Mock 0 | How to execute "after 15m if unread, send Email" and "15m AI digest window" at scale? | Use a Redis Sorted Set (`ZSET`) keyed by `trigger_timestamp` (or delayed queue) + Redis List/counter for message buffering. | Due 2026-11-03 | Due 2026-11-08 |
| 2026-11-01 | Mock 0 | How should idempotency keys be generated, and what if all LLMs fail? | Caller generates a UUID `idempotency_key` (stored in Redis `SET NX EX`), not a content hash. If all LLMs fail, degrade to a deterministic template summary. | Due 2026-11-03 | Due 2026-11-08 |

## Weakness heat-map (updated weekly; feeds the refresh ranking)
| Area | Score 1-5 (1 = weak) | Last updated |
|------|----------------------|--------------|
| Estimation | 3.5 | 2026-11-01 |
| DB / sharding / replication | 2.0 | 2026-11-01 |
| Caching | 2.5 | 2026-11-01 |
| Queues / streaming | 2.0 | 2026-11-01 |
| Consistency / transactions | 2.5 | 2026-11-01 |
| Reliability / observability | 3.5 | 2026-11-01 |
| Geospatial / search | 2.5 | 2026-11-01 |
| LLM / RAG / agents | 3.0 | 2026-11-01 |
| Communication / structure | 3.5 | 2026-11-01 |
| Senior trade-offs & ops | 2.5 | 2026-11-01 |
