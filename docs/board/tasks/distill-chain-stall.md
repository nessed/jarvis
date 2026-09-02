---
id: distill-chain-stall
status: done
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

## Log

### 2 September 2026 — done. Two faults, neither in the chain's own logic.

**The chain is running.** Seven live jobs completed back-to-back, seven turns
distilled, zero failures, each link enqueued by the one before it:

```
pass -: dd853e77-e269-4497-aaab-69c01ddbb447 -> done attempts=2 in 44.6s
pass 0: 2d2d6c1c-4821-44d0-b112-9df3ff0a9995 -> done attempts=1 in 45.9s
pass 1: adcb7574-9792-4660-8e3e-bdb93142bae1 -> done attempts=1 in 75.5s
pass 2: b2ace2a9-47b6-461c-91d3-8ba691279242 -> done attempts=1 in 42.8s
pass 3: cf8c4b91-2ee8-40ba-a83f-5ad387e278e3 -> done attempts=1 in 29.0s
pass 4: 9e3e1e57-3740-4c97-bb51-f2e8aafb9eae -> done attempts=1 in 26.0s
pass 5: 3e9471b1-adb3-4ebe-9688-116dd5bea03c -> done attempts=1 in 44.8s
```

`dd853e77` is the row the task was written about — ripe and unclaimed since
30 Aug. Run through the real `poll_once(handlers=DEFAULT_HANDLERS,
kind_filter="distill_memory")` against the live queue, not a fake:

```
INFO executor.handlers.distill:   distilled in 32.7s  Hi! ... What can I help you with today?
INFO executor.handlers.distill: distilled 1 turn(s), 0 failed, backlog remaining: True
--- poll_once returned in 44.6s
id = dd853e77-e269-4497-aaab-69c01ddbb447   status = done   attempts = 2
```

Extraction runs 14-46s per turn against `llama3.1:8b`, comfortably inside the
90s default. The backlog was 26 undistilled turns and is now 19.

### What actually happened, 29-31 August

**Fault 1: Ollama stopped, and the failure was invisible.** The last
extraction in `tools/background-worker.out.log` is line 202, 31 Aug 00:35:26
local — `Local Ollama fact extraction is unavailable`. It is also the last
`mem0` line in the file. Everything after it is a ~55s cycle with no
extraction in it at all:

```
01:49:38  claim_next_job
01:49:38  checkpoint_job          (executor_started)
01:49:39  GET jobs?select=status  (_status_at_entry)
01:49:41  GET jobs?...kind=neq.distill_memory   (the yield check)
01:49:44  retry_or_dead_letter_job
01:49:46  POST /jobs  ->  "seeded the distill_memory chain"
```

Three seconds from claim to failure, and nothing between the yield check and
the failure. That places the raise inside `_distill_one_chunk`'s
`open_extractor()` — `open_mem0_memory` (`memory/mem0_wrapper.py:304`) runs an
embedding **dimension probe** before anything else, and with nothing listening
on 11434 that is a `ConnectError` in milliseconds. Hence `EmbeddingError`, not
`LLMError`, for a failure that never reached the model.

**Fault 2: the process was killed and never restarted.** The log ends at
31 Aug 01:53:30 local = 30 Aug 20:53 UTC, which is exactly `dd853e77`'s
`run_after`. "Ripe and unclaimed for over two days" was not a bug — there was
no `background-worker`. Nothing in the code was waiting on anything.

`docs/audit/blueprint-drift.md` §4's first open question is settled: the chain
was neither healthy nor dead-lettered out of existence. It had no worker.

### Step 1 — the causes are now distinguishable

`memory/embeddings.py` raised `EmbeddingError` for a timeout, a connect
failure, a 404 and eleven other things alike, and `executor/poller.py` stored
only `type(exc).__name__`. 84 live rows say `executor handler failed
(EmbeddingError)` and nothing more.

- `EmbeddingError` now carries a `cause`, from a published 15-name vocabulary
  (`EMBEDDING_FAILURE_CAUSES`) plus `http_<status>`. 404 in particular means
  the model was never pulled, which is the failure most often mistaken for
  "Ollama is down".
- `executor/poller.py::_describe_failure` appends it:
  `executor handler failed (EmbeddingError: unavailable)`.
- **The slug shape is a privacy boundary, not tidiness.** The checkpoint is
  written to the *hosted* jobs table, so a cause is admitted only if it
  matches `[a-z0-9_]{1,40}`; a prompt, a turn, a URL or a key cannot pass
  that, and anything else falls back to the bare type name. Tested with eight
  unsafe shapes.

Generic on purpose, so `LLMError` can publish one without touching the poller.
It does not yet — its 16 live rows are all the one known invalid-JSON failure
already filed at `docs/blockers/mem0-extraction-not-schema-constrained.md`.

### Scope added: the amplifier that turned one outage into 84 rows

Not in the task's Steps, and reported as an addition. The seed is idempotent,
which says nothing about *rate*: when the chain dead-letters the executor
re-seeds on its very next poll, so a broken Ollama produced a row every ~55s
for 78 unattended minutes. Every one of those rows carried
`{"reason": "seed"}` — no work, and nothing lost.

`seed_distill_chain` now seeds at most once per `SEED_RESEED_COOLDOWN_SECONDS`
(900s, deliberately equal to the idle cooldown: a chain that died costs no
more than one with nothing to do). A live chain returns early without spending
the allowance, and a fresh process always seeds immediately, so a restart is
never delayed. The test drives the real 78-minute loop and counts 6 rows where
the incident produced 84.

### Step 4 — the 98 dead-lettered rows: not deleted, not re-queued

Their payload is scheduling metadata only; the backlog lives in the local
conversation store and was still intact, which is where today's seven turns
came from. **Re-queueing them would achieve nothing.** Deletion is a
destructive write to the live table, so it is **Q13**, with A (leave them)
recommended and Q9's orphan-row carve-out as the precedent.

### Verification

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-lane-1
1297 passed, 9 deselected, 10 warnings in 67.71s
```

First run of that command showed `4 failed, 1293 passed` — all four in
`tests/tools/test_context_status.py`, all `fatal: detected dubious ownership`.
`.git` is owned by a different Windows account, so every `git` call in the
repo fails. Unrelated to this task, filed as **U13**, and worked around per
command with `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory
GIT_CONFIG_VALUE_0=...` rather than by writing global git config, which
`agents.md` reserves for Ali.

Live queue after this task: 383 rows, `distill_memory` 63 `done` (was 56),
98 `dead_letter` (unchanged), 1 `queued` — the chain's next link, not a stall.
