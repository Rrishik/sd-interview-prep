# Chapter 27: Structured Concurrency, Bounded Channel Backpressure & Pure Agent Reducers

*Part V · LLM Internals, Harnesses & Multimodal · 8 min core · 18 min with deep dives*

In Chapter 18 we designed the **external gateway** holding `50,000` reactive SSE connections. Now step *inside* a single agent worker executing 6 parallel MCP tool calls, streaming `500 chunks/sec` from an LLM, and writing durable state checkpoints.

Three subtle language-level bugs routinely take down production agent runtimes: **orphan background tasks** burning GPU quota after an exception, **unbounded in-memory stream queues** OOM-crashing pods on slow mobile clients, and **tangled async I/O state machines** that require flaky network mocks just to unit-test a retry rule [1, 4, 5].

{{diagram:15-structured-concurrency-runtime.excalidraw}}

---

### 1) Structured Concurrency & Scoped Cancellation (`TaskGroup` / `StructuredTaskScope`)

Launching parallel tool calls with unstructured fire-and-forget primitives (`asyncio.create_task`, detached `Task.Run`, bare `go func()`) breaks **lexical lifetime discipline**: if Tool Call #2 throws a `PermissionError` at `50 ms`, Tool Calls #1 and #3 keep running as **orphan tasks** in the background—leaking open sockets and burning paid API/LLM quota [1]!

**Structured Concurrency** enforces one ironclad invariant—**a parent scope may never exit until every child task spawned inside it has completed, failed, or finished cancellation cleanup** [1, 2, 3]:

| Runtime / Language | Structured Primitive | Automatic Failure & Cancellation Behavior |
| :--- | :--- | :--- |
| **Python `3.11+`** | `async with asyncio.TaskGroup() as tg:` [3] | First unhandled child exception cancels all sibling tasks, awaits their `finally` blocks, and raises an `ExceptionGroup` [3]. |
| **Java `21+`** | `StructuredTaskScope.ShutdownOnFailure` (`JEP 453`) [2] | Short-circuits sibling virtual threads on first failure; `scope.join()` guarantees zero leaked threads on block exit [2]. |
| **C# / C++20** | Linked `CancellationTokenSource` / `std::jthread + std::stop_token` | Parent token cancellation propagates cooperatively down the entire call tree; RAII destructors join before stack unwind. |

:::deepdive Bulkhead Semaphores & Shielding Critical Checkpoint Writes on Cancel | +5 min

Two edge cases bite engineers the first time they wire `TaskGroup` cancellation into an agent loop [3]:
1. **Bounded Fan-Out Bulkheads (`Semaphore(max_parallel)`):** If an LLM emits `25` parallel `search_logs` tool calls in a single turn, spawning `25` unconstrained coroutines inside a `TaskGroup` can still starve the downstream DB connection pool. Wrap each child inside `async with run_semaphore:` (`e.g., max_parallel = 5`) so concurrency stays bounded while preserving structured failure propagation [3].
2. **Preventing Torn Checkpoints (`asyncio.shield` & `BaseException`):**
   - In Python `3.8+`, `asyncio.CancelledError` inherits from **`BaseException`** (not `Exception`) so `except Exception:` never accidentally swallows cancellation [3]!
   - However, if a user clicks **Stop** at the exact millisecond your worker is half-way through committing `checkpoint.save(step_4)` to Postgres, aborting that socket mid-flight can leave inconsistent run state. Wrap critical durability flushes and compensating Saga rollbacks in **`await asyncio.shield(checkpoint.save())`** (or pass `CancellationToken.None` with a short `2s` cleanup timeout in C#/Java) so the commit finishes cleanly before the task exits [3]!

:::

---

### 2) Async Streaming Pipelines: Lossless Backpressure vs. Conflated Ring Buffers

What happens when an upstream LLM or log-tail tool produces **`500 chunks/sec`** while a user's cellular SSE connection on a train drains **`30 chunks/sec`**?
An unbounded `asyncio.Queue()` buffers `470 chunks/sec` in RAM per user—multiply by `2,000` concurrent streams and the worker crashes with `OutOfMemoryError` in under a minute [4]!

Choose your channel policy explicitly based on **whether every frame is load-bearing** [4]:
1. **Lossless Content Streams (`BoundedQueue(maxsize = 64)`):**
   - Used for **assistant text deltas, code diffs, and `tool_call` JSON fragments** where dropping 1 chunk corrupts the output!
   - When all `64` slots fill up, `await queue.put(chunk)` **suspends the producer coroutine**, which stops reading from the upstream socket, which shrinks the OS **TCP receive window (`rwnd = 0`)**—propagating deterministic backpressure all the way back to the inference server with strictly **`O(capacity)` memory** [4].
2. **Lossy Telemetry & Progress Streams (`Conflated / Drop-Oldest Ring Buffer, maxlen = 1`):**
   - Used for transient UI status badges (`"Scanning file 42/200..."`, token-per-second gauges). A slow mobile UI only cares about the **latest** progress percentage—blocking the agent's execution loop just to deliver `"41%"` before `"42%"` is an anti-pattern! Use a `collections.deque(maxlen=1)` + `asyncio.Event` signal so new status frames overwrite unread stale frames in `O(1)` [4].

---

### 3) Functional Core, Imperative Shell & Single-Source Schema Reflection

How do you unit-test a `12-state` agent orchestrator (retries, `429` model fallback, `WAITING_APPROVAL` human gates, duplicate-call loop detection, budget exhaustion) in **`<10 milliseconds`** without spinning up Docker, Redis, or brittle LLM mocks?

Factor the runtime using **Functional Core, Imperative Shell** (*Gary Bernhardt* [5]):
1. **Pure Deterministic State Reducer (*Functional Core*):** Write a pure, zero-I/O function `(state: RunState, event: AgentEvent) -> tuple[RunState, list[Effect]]`. Given `RunState(step=3, retries=2)` and `ToolFailed(status=503)`, it deterministically returns `(RunState(status=DEGRADED), [TripCircuitBreaker(), EmitFallbackReply()])`—100% testable with plain `assert` statements and replayable from an append-only event log [5]!
2. **Thin Async Effect Interpreter (*Imperative Shell*):** A `<100-line` async loop that executes each `Effect` (`CallModel`, `RunMcpTool`, `SaveCheckpoint`) inside a structured `TaskGroup` and feeds the resulting `AgentEvent` back into the pure reducer [3, 5].

:::deepdive Zero-Drift Tool Contracts via Single-Source Schema Reflection | +4 min

Hand-maintaining a Python/TypeScript function signature in one file and a separate `200-line` MCP JSON Schema dict in another file guarantees **schema drift**—within two sprints, an engineer renames `limit` to `max_results` in code, forgets the JSON Schema, and every LLM call fails at runtime [6]!

- **Compile Everything From One Typed Declaration:** Define each tool's input/output once as a strongly typed model (`Pydantic v2` in Python, `Zod` in TypeScript, `System.Text.Json` compile-time source generators in C#).
- **Three Artifacts Generated Automatically:** At startup/build time, reflect that single type into (1) the **MCP `tools/list` JSON Schema (`Draft 2020-12` [6])**, (2) the **constrained-decoding grammar mask** sent to the LLM, and (3) the **runtime input validator**—which catches domain violations (`start_date > end_date`) and returns structured `{isError: true, retryable_by_model: true, field_errors: [...]}` hints instead of raw stack traces!

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** Unstructured `create_task` concurrency is sending three hikers into a blizzard with no check-in rope; **Structured Concurrency (`TaskGroup`)** is roping the team together so nobody leaves base camp until every climber is accounted for. **Lossless vs. Conflated Channels** is the difference between a **bank statement** (every line item must arrive in order) and a **car speedometer** (you only ever want the current speed, never a 30-second backlog of old speeds!).
- **Where the analogy breaks:** If `TCP rwnd = 0` backpressure pauses an upstream LLM stream for **too long** (`>60s` on a dead client tunnel), holding a `70B` GPU KV-cache slot hostage hurts cluster Goodput—so pair bounded queues with a **per-chunk write-stall timeout** that detaches slow clients onto durable Redis/Postgres stream replay (Chapter 19) [4]!
- **Real production system:** **Python `Trio` / `AnyIO` (`asyncio.TaskGroup`)**, **Java 21 Virtual Threads (`StructuredTaskScope`)**, and **Pydantic / Zod MCP SDKs** standardize structured cancellation, bounded stream backpressure, and single-source schema reflection across modern agent runtimes [1, 2, 3, 6].

---

### Quick Self-Check

<details>
<summary><strong>Q1: What bug happens when parallel tool calls are spawned with bare <code>asyncio.create_task()</code> instead of <code>asyncio.TaskGroup()</code> and one tool raises an exception?</strong></summary>
<p><strong>Answer:</strong> Under bare <code>create_task()</code>, the caller unwinds on the first exception while sibling tasks keep running as untracked orphans—leaking sockets, mutating external state unexpectedly, and burning downstream API/GPU quota. <code>TaskGroup</code> automatically cancels all siblings and awaits their cleanup before exiting the block.</p>
</details>

<details>
<summary><strong>Q2: Why should critical checkpoint commits use <code>asyncio.shield()</code> when handling user-initiated stream cancellation?</strong></summary>
<p><strong>Answer:</strong> Because <code>CancelledError</code> interrupts <code>await</code> points immediately; interrupting a database/journal write mid-flight can leave torn or half-committed run state. Shielding with a bounded cleanup timeout lets the atomic checkpoint write finish cleanly before propagating cancellation.</p>
</details>

<details>
<summary><strong>Q3: When streaming from an agent worker to a slow mobile client, why use a bounded lossless queue for text tokens but a <code>maxlen=1</code> drop-oldest buffer for progress spinners?</strong></summary>
<p><strong>Answer:</strong> Dropping a text/JSON token corrupts the response (requiring bounded lossless TCP backpressure), whereas progress indicators (<em>"42% complete"</em>) are ephemeral state snapshots where overwriting stale unread percentages avoids stalling worker execution.</p>
</details>

<details>
<summary><strong>Q4: How does the "Functional Core, Imperative Shell" pattern let you unit-test complex agent retry, fallback, and human-approval transitions in &lt;1 ms?</strong></summary>
<p><strong>Answer:</strong> All branching logic lives inside a pure, side-effect-free reducer <code>(State, Event) -&gt; (NewState, list[Effect])</code> with zero network, clock, or LLM dependencies—so tests assert exact state transitions and emitted effect structs directly in memory without mocks.</p>
</details>

---

### Sources & References
- **[1]** Nathaniel J. Smith, *Notes on Structured Concurrency, or: Go Statement Considered Harmful* (Trio Design Essay, 2018) — [vorpus.org/blog/structured-concurrency](https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/)
- **[2]** OpenJDK JEP 453, *Structured Concurrency (`StructuredTaskScope` in Java 21)* — [openjdk.org/jeps/453](https://openjdk.org/jeps/453)
- **[3]** Python Software Foundation, *`asyncio` — Task Groups, Cancellation & Shielding (`asyncio.TaskGroup`, `asyncio.shield`)* — [docs.python.org/3/library/asyncio-task](https://docs.python.org/3/library/asyncio-task.html)
- **[4]** Reactive Streams Initiative, *Reactive Streams Specification (Asynchronous Bounded Backpressure)* — [reactive-streams.org](https://www.reactive-streams.org/)
- **[5]** Gary Bernhardt, *Boundaries: Functional Core, Imperative Shell* (SCNA / Destroy All Software) — [destroyallsoftware.com/talks/boundaries](https://www.destroyallsoftware.com/talks/boundaries)
- **[6]** IETF / JSON Schema Specification, *JSON Schema: A Media Type for Describing JSON Documents (Draft 2020-12)* — [json-schema.org/draft/2020-12](https://json-schema.org/draft/2020-12/json-schema-core)
