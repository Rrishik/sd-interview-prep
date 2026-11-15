# Chapter 22: Agent Harnesses ("Workbenches"), Portable Skills & Multi-Session Delegation

*Part V · LLM Internals, Harnesses & Multimodal · 9 min core · 19 min with deep dives*

Drop a frontier coding model into a real monorepo with nothing but a chat prompt—*"Add rate-limit headers to the checkout API"*—and watch how it fails:

It edits four files, quietly modifies an unrelated auth config, floods its own context window with `60 KB` of raw test output, declares `"All done!"` while two integration tests are still red, and leaves zero structured state for the next session [1, 2].

The model did not fail at writing code—**the harness failed at framing engineering work**. Production teams separate *model intelligence* from **Harness ("Workbench") Engineering** and **Portable Agent Skills (`SKILL.md`)** [1, 2, 3].

{{diagram:10-agent-harness-and-skills.excalidraw}}

---

### 1) The 7 Surfaces of a Production Agent Harness ("Workbench")

An orchestration framework (`LangGraph`, `Agents SDK`) runs the step loop; a **Workbench** is the deterministic operating environment around that loop—making **versioned repository files**, never volatile chat history, the system of record [1, 2]:

| Workbench Surface | Artifact / Mechanism | Failure Mode When Missing |
| :--- | :--- | :--- |
| **1. Router Instructions** | Concise (`<150-line`) root `AGENTS.md` map + machine-checkable rules (startup, forbidden ops, definition of done). | Monolithic `3,000-word` instruction manuals rot and drown attention [1]. |
| **2. Schema-First Repo State** | `agent_state.json` & `task_board.json` persisted via JSON Schema validation + atomic `tmp -> rename()` writes. | Next session restarts from zero or trusts hallucinated chat summaries [1]. |
| **3. Idempotent Init Probe** | Fast startup script probing runtime versions, build cache, and baseline test health into `init_probe.json`. | Agent wastes 5 turns per session rediscovering broken local dependencies [1]. |
| **4. Glob Scope Contract** | `allowed_globs`, `forbidden_globs` (`.github/workflows/**`), acceptance proofs, and rollback plan checked against `git diff`. | Unbounded scope creep and drive-by edits in unrelated subsystems [1]. |
| **5. Bounded Feedback Runner** | Executes commands and records `{cmd, exit_code, head, tail, log_uri}` with deterministic byte truncation. | `80 KB` build logs blow token budgets, or agent ignores non-zero exit codes [1, 2]. |
| **6. Verification Gate** | Deterministic function over lint + targeted tests + scope diff -> `verification_report.json` (**blocks on any red check**). | `"Looks good to me"` ships broken builds to `main` [1]. |
| **7. Read-Only Reviewer Role** | Separate **Reviewer** pass (with **zero edit tools**) grading the diff + verification report against an explicit rubric. | Builder grades its own homework and rationalizes subtle regressions [1, 6]. |

---

### 2) Portable Agent Skills (`SKILL.md`) & 3-Tier Progressive Disclosure

Suppose your engineering platform ships **200 domain skills** (`db-migration`, `incident-triage`, `k8s-rollout`, `openapi-lint`). Injecting all 200 full playbooks into every prompt burns `250,000+` tokens; injecting none forces engineers to memorize file paths [3, 4].

Production runtimes treat **Skill Discovery and Disclosure as a 3-Tier Compiler Pipeline** [3, 4]:
1. **Scope Precedence & Collision Policy:** Scan `Workspace (.agents/skills) -> User -> Org Policy -> Built-in` with an explicit precedence rank, logging rejected packages and shadowing collisions deterministically [4].
2. **Three-Tier Context Budgeting:**
   - **Tier 1 — Compact Catalog (`~60–100` tokens/skill):** Only `name` + sharp routing `description` (*"Use when X. Do NOT use for Y."*) enters the initial prompt—budgeted independently from working context [3, 4].
   - **Tier 2 — Active `SKILL.md` Body:** Loaded into context **only after** explicit user (`/skill`) or implicit model selection [3].
   - **Tier 3 — On-Demand Branch Resources & Scripts:** Specific reference files (`postgres.md` vs `mysql.md`) and deterministic validation scripts are read only when the active workflow branch needs them—canonicalizing paths via `realpath()` inside the skill root to block `..` traversal and symlink escapes [3, 4].
3. **Security Invariant — Skills Are Context, Not Authority:** Activating a `SKILL.md` package **never grants tool permissions, creates a sandbox, or trusts untrusted repository data**; host capability policies, command allowlists, and OS sandboxing remain strictly independent layers [3, 4].

:::deepdive Skill Routing Evals (Near-Misses & Abstention), 2x2 Invocation & Voyager Libraries | +5 min

1. **The `2 × 2` Human-vs-Model Invocation Policy [4]:**
   - Model `user_invocable` (slash-menu visibility) and `model_invocable` (auto-routing eligibility) as independent booleans: high-consequence workflows like `/cut-release` set `user_invocable: true, model_invocable: false`, while background `repo-style-guide` sets `model_invocable: true` [4].
2. **Testing Skills Across 6 Independent Layers [4]:**
   - Production skill CI gates test: (1) Package structure & YAML frontmatter schema, (2) **Trigger routing** across *positives*, *clear negatives*, **near-misses**, and **explicit abstention** (verifying the router picks *zero* skills when none apply!), (3) Artifact/instruction adherence, (4) Deterministic helper-script unit tests, (5) Path/command containment, and (6) **With-Skill vs. No-Skill A/B pass-rate delta** across repeated trials [4].
3. **Executable Skill Libraries (`Voyager`, Wang et al.) [5]:**
   - Rather than re-deriving primitive tool sequences from scratch, lifelong agents index **verified executable skill programs** by description embeddings—composing complex behaviors hierarchically once each new skill passes automated sandbox verification [5].

:::

---

### 3) Parallel Worktree Delegation, Multi-Session Handoffs & The Feedback Ratchet

- **Wave Isolation via `git worktree`:** Delegate subtasks in parallel **only** when their write scopes are provably disjoint! Compute dependency waves from the task DAG, assign each worker an isolated **`git worktree`** plus exclusive `allowed_globs`, and require a green `verification_report.json` from every worker before the integrator merges—never having the integrator rewrite worker code from scratch [1, 6].
- **7-Field Machine-Generated Handoff Packets:** When a long task spans multiple sessions or hits `75%` context fullness, generate a structured handoff directly from workbench files—`(1) goal, (2) completed_ids, (3) base_sha & diff_stat, (4) latest_verification_verdict, (5) active_blockers, (6) architectural_decisions, (7) deterministic_first_next_step`—eliminating prose drift across compactions [1].

:::deepdive The Feedback Ratchet: Promoting Every Agent Failure to the Earliest Deterministic Layer | +4 min

When an agent makes a production mistake, appending *"IMPORTANT: Never do X!"* to `AGENTS.md` is the **weakest possible fix**. Over months, prose patches accumulate into contradictory prompt bloat [1].

Instead, run a **Feedback Ratchet** that promotes every recurring correction to the **earliest deterministic layer** capable of preventing it [1]:

| Layer (Strongest -> Weakest) | Mechanism | Reliability & Cost | Example Promotion |
| :--- | :--- | :--- | :--- |
| **1. Tool / State Schema** | Remove unsafe arg or tighten JSON Schema `enum` | **`100%`** (`0` tokens) | Remove `force: boolean` from `git_push` tool schema. |
| **2. Pre-Execution Hook / Linter** | AST / regex / path-glob check in `<5 ms` | **`100%`** (`0` LLM hops) | Block edits touching `migrations/` without `migration-approved` label. |
| **3. Verification Gate** | Deterministic unit/integration/diff assertion | **`100%` pre-merge** | Fail gate if public API changes lack OpenAPI snapshot update. |
| **4. CI Golden / Adversarial Eval** | Saved replay trace in regression suite | **Catches model/prompt drift** | Add failing customer trace to pre-deploy eval gate. |
| **5. `SKILL.md` / `AGENTS.md` Prose** | Scoped workflow judgment rule + **retirement condition** | **Probabilistic** (costs tokens) | Keep prose only where human/model judgment is genuinely required—and prune rules once upstream layers enforce them [1]! |

:::

---

### Analogy, Where It Breaks & Real System

- **Real-world analogy:** A frontier LLM without a harness is a brilliant surgeon operating in a dark room with no chart, no sterile field boundary, and no post-op vitals checklist. The **7-Surface Harness** is the operating theater, instrument tray (`SKILL.md` progressive trays), surgical boundary drape (`Scope Contract`), and independent pathology sign-off (`Verification Gate + Read-Only Reviewer`).
- **Where the analogy breaks:** Hospital checklists rely on human discipline; software harnesses can enforce **100% deterministic refusal in code**—literally making it impossible for an agent to mark a task complete while `verification_report.json` has `exit_code != 0` [1].
- **Real production system:** **SWE-agent's Agent-Computer Interface (ACI)**, **Claude Code / Codex `SKILL.md` & `AGENTS.md` harnesses**, and **GitHub Copilot Coding Agent** pair worktree isolation, bounded command viewers, progressive skill loading, and mandatory CI verification gates [1, 2, 3].

---

### Quick Self-Check

<details>
<summary><strong>Q1: Why should root <code>AGENTS.md</code> act as a short routing map (&lt;150 lines) rather than a 3,000-word encyclopedia of every team rule?</strong></summary>
<p><strong>Answer:</strong> Every line in root <code>AGENTS.md</code> taxes every single turn of every task, diluting attention on rules that actually apply and quickly rotting out of sync with code. A compact router points the agent to subsystem docs and progressive <code>SKILL.md</code> files only when relevant.</p>
</details>

<details>
<summary><strong>Q2: How does 3-Tier Progressive Disclosure let an agent support 200 installed skills without blowing its context window?</strong></summary>
<p><strong>Answer:</strong> Tier 1 loads only compact <code>name + trigger description</code> metadata (~80 tokens/skill) into the catalog; Tier 2 loads the selected <code>SKILL.md</code> body only upon activation; Tier 3 loads branch-specific reference files or scripts strictly on demand.</p>
</details>

<details>
<summary><strong>Q3: Why must the Reviewer Agent in a coding workbench have zero file-editing tools?</strong></summary>
<p><strong>Answer:</strong> Separating Builder from Marker prevents self-licensing bias and silent scope drift: a read-only Reviewer inspects the diff, scope report, and deterministic test results against a rubric and emits structured findings without silently mutating code past the verification gate.</p>
</details>

<details>
<summary><strong>Q4: According to the Feedback Ratchet, why shouldn't every agent bug postmortem end by adding another bullet to the system prompt?</strong></summary>
<p><strong>Answer:</strong> Prose rules are probabilistic and consume context tokens forever. Promoting fixes to schema constraints, pre-execution path/command hooks, or deterministic verification gates guarantees <code>100%</code> prevention at zero token cost.</p>
</details>

---

### Sources & References
- **[1]** Rohit Ghumare et al., *AI Engineering from Scratch — Phase 14: Agent Workbench Engineering, Scope Contracts, Verification Gates & Feedback Ratchet* — [aiengineeringfromscratch.com/learn/agent-engineering/the-agent-loop](https://aiengineeringfromscratch.com/learn/agent-engineering/the-agent-loop)
- **[2]** John Yang et al., *SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering* (NeurIPS 2024) — [arxiv.org/abs/2405.15793](https://arxiv.org/abs/2405.15793)
- **[3]** Agent Skills Open Specification, *Portable `SKILL.md` Package Format, Progressive Disclosure & Trust Boundaries* — [agentskills.io/specification](https://agentskills.io/specification)
- **[4]** Rohit Ghumare et al., *AI Engineering from Scratch — Phase 13: Skill Discovery, Trigger Routing, Permissions & 6-Layer Evals* — [aiengineeringfromscratch.com/learn/tools-and-protocols/the-tool-interface](https://aiengineeringfromscratch.com/learn/tools-and-protocols/the-tool-interface)
- **[5]** Guanzhi Wang et al., *Voyager: An Open-Ended Embodied Agent with Large Language Models* (TMLR 2024) — [arxiv.org/abs/2305.16291](https://arxiv.org/abs/2305.16291)
- **[6]** Anthropic Engineering, *Building Effective Agents* (2024) — [anthropic.com/research/building-effective-agents](https://www.anthropic.com/research/building-effective-agents)
