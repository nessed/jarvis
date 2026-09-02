---
id: backfill-run
status: blocked
lane: AUTO
priority: 1
phase: 1
blocked-on: Q14 (the blocker's fix contradicts Ali's own Q10a blueprint amendment)
files: docs/tasks/backfill-run-report.md (run artifacts only; code changes only if Q3=B)
resources: ollama-extract (EXCLUSIVE — executor stopped, whole window), test-workspace
---

# backfill-run — finish blueprint 1.3

## Gate

**Answered 1 Sep 2026 — Q3 = A, Q4 = go.** Checkpoints stay content-hash
and the blueprint was amended to match, so **there is no conform step**:
the code is correct as it stands. Corpus confirmed: `ingest/data/` as it
stands is the whole opt-in, nothing outside it is read.

Window: **overnight, and explicitly not Saturday morning.** Hold
`ollama-extract` for the full run and expect JARVIS to be text-dumb
throughout.

Q3 (checkpoint semantics settled — if B, conform the code first as its own
step with tests) and Q4 (corpus confirmed + a no-replies window). The
window matters: this run monopolises Ollama for its whole duration; JARVIS
cannot reply while it runs.

## Steps

1. In Ali's window: stop the executor (`Ctrl+C` on the launcher window or
   confirm no heartbeat), claim `ollama-extract`.
2. `python tools/run_backfill.py --dry-run` first; sanity-check the file
   list is exactly `ingest/data/` as Ali confirmed, and the checkpoint
   state (one prior partial run exists: chunk index 1 from 26 Aug —
   resumes, not restarts, if Q3=A).
3. Run for real. It is checkpointed and resumable; if the window ends
   before it finishes, stop cleanly and report progress — do not run into
   live hours.
4. Restart the stack; confirm both workers reach steady-state polling.
5. Report: chunks processed, facts extracted, duration, failures, where it
   stopped. Then U5 (Ali's ten-question review) becomes actionable — say
   so in the handoff, once.

## Done when

Backfill complete over the confirmed corpus (or cleanly parked at a
checkpoint with the remainder scheduled), stack back up, report cited.
Phase 1's remaining gate is then U5, which is Ali's.

## Log

**2 Sep 2026 — attempted in the approved window, blocked.** Three runs, each
failing further along: extraction timeout (90s default), then embedding
timeout (15s default, queued behind the 8B generation), then unusable JSON
from the model. Root cause and the one-line unblock:

    docs/blockers/mem0-extraction-not-schema-constrained.md

Blueprint 1.3 specifies constrained JSON-schema decoding; `mem0_wrapper.py`
validates after the fact instead. Schema-constrained decoding was verified to
hold at every real chunk size (4/4 valid, 26-29s each) on synthetic input.

Fixing it means editing `memory/mem0_wrapper.py`, which this task's own gate
excludes (`code changes only if Q3=B`; Ali answered Q3=A). Needs its own task.

**Nothing was left half-done.** Checkpoint unchanged at `next_chunk_index: 1`,
memory unchanged at 230 facts, nothing written to `ingest/data/`. The run
resumes cleanly once unblocked.
