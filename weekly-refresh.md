# Weekly Refresh Procedure (about 30 min, run at the end of each week)

1. **Answer Inline Line Questions (`line-question` GitHub Issues).** Pull issues with label `line-question` from `Rrishik/sd-interview-prep`. For any open question or unanswered follow-up comment in a thread, locate the paragraph (`<!-- anchor:chXX-bYY -->`) in `chapters/chXX-*.md`, post a concise first-principles answer directly as a comment on that GitHub Issue (`gh issue comment <num> --repo Rrishik/sd-interview-prep --body "..."`), and refine the chapter line if the question exposed an ambiguity.
2. **Process Shared Source Inbox (`inbox` GitHub Issues + `inbox/manual-drops.md`).** Pull open issues labeled `inbox` (created via the blog's **+ Add Source** button) and read any URLs or notes in [inbox/manual-drops.md](./inbox/manual-drops.md). Fetch links, fold key takeaways and `[N]` citations into the matching `chapters/chXX-*.md` **Sources & References** section, and close processed `inbox` issues.
2. **Harvest Web Sources.** Review every source in [sources.md](./sources.md) for posts from the last 7 days. Prioritize company-tagged, senior-level reports (Google, Meta, Microsoft, Amazon, Uber, Stripe). Capture the question, company, level, and stated feedback.
3. **Record.** Append to "Newly harvested" in [question-bank.md](./question-bank.md) and bump the tallies.
4. **Re-rank.** Priority = frequency tally x weakness (6 - score from the progress.md heat-map). Move the top items into next week's slots.
5. **Adapt the plan.** Swap or add a case in [00-plan.md](./00-plan.md) if something new is hot. Retire a case only if it is low-frequency and you scored >= 4 twice.
6. **Source hygiene.** Add up to 2 new sources and drop any that were stale or low-signal. Mark each as verified and note reliability.
7. **Re-quiz.** Run the spaced re-quiz of the missed-question log.
8. **Log.** Add an entry to the changelog below.

**Automation option (needs your approval):** a weekly scheduled Copilot task that runs steps 1-2 and 5, then produces a short "what's new" digest for you to review before steps 3-4.

## Changelog
- 2026-11-01: initial plan.
