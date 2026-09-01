---
id: distill-chain-stall
status: ready
lane: AUTO
priority: 1
phase: 1
blocked-on: none
files: executor/handlers/distill.py (hot), memory/embeddings.py (hot), tests/executor/test_distill_handler.py, tests/memory/, docs/state.md
resources: ollama-extract (live repro), live-jobs-table (read-only unless re-queueing)
---

# distill-chain-stall — 98 dead-letters, then two days of nothing

## Goal

Batch distillation is the memory path. It is not running, and it has not
been running since 30 August 2026. Find out why, fix it, and get the chain
moving again.

Found 2 Sep 2026 by `db-maintenance` while reporting the orphaned probe
rows. Full evidence in that task's Log; the short version:

- **98 of the live queue's 103 dead-lettered rows are `distill_memory`**,
  all between 29 Aug 13:06 and 30 Aug 20:52 UTC.
  - 83 × `executor handler failed (EmbeddingError)`
  - 12 × `executor handler failed (LLMError)`
  - 3 × `exhausted after stale timeout`
- **The chain is alive but stalled.** Exactly one `distill_memory` row is
  `queued` — `dd853e77`, `run_after` 30 Aug 20:53. Ripe and unclaimed for
  over two days, which means no `background-worker` has polled in that
  window.
- By contrast `whatsapp_webhook` is 175 rows, **all `done`**. The reply path
  is healthy. This is specific to memory.

This settles `docs/audit/blueprint-drift.md` §4's first open question, which
asked whether the chain was alive or had dead-lettered out of existence. It
is neither.

## What is already ruled out

Ollama is running now and `nomic-embed-text:latest` is installed (checked
2 Sep 2026), so "the model was never pulled" is not the answer.

## Steps

1. **Separate the causes first.** `memory/embeddings.py` raises
   `EmbeddingError` for a timeout, a connect failure and a non-200 alike, so
   83 identical checkpoints hide up to three different failures. Give each
   its own message (or a `cause` field on the checkpoint) *before*
   diagnosing, or the next 83 will be just as opaque. This is worth doing
   even if the root cause turns out to be obvious.
2. Work out what was true on 29-30 Aug. `tools/background-worker.out.log`
   covers that window; the poller logs failures by type only, so pair it
   with the dead-lettered rows' `updated_at` values.
3. The obvious hypothesis to test, not assume: the distill handler holds
   Ollama for a 20-130s extraction while the same Ollama is asked to embed,
   and the embedding call times out behind it. `OLLAMA_EMBEDDING_TIMEOUT_SECONDS`
   and the extraction timeout are both configurable; `assert_timeouts_ordered`
   already exists for the extraction side.
4. Decide what happens to the 98 dead-lettered rows. **Do not delete them
   without asking** — Q9's carve-out on the probe rows is the precedent, and
   they are the only evidence of what broke. Re-queueing some of them is a
   different question from deleting them.
5. Get the chain moving: the one ripe row should be claimed and completed, or
   the reason it cannot be should be the finding.

## Done when

The chain has completed at least one `distill_memory` job live (cite the row
and the log), the `EmbeddingError` causes are distinguishable, and
`docs/state.md`'s distill rows say what actually happened.
