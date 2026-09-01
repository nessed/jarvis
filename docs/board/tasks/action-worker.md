---
id: action-worker
status: ready
lane: AUTO
priority: 1
phase: 2
blocked-on: none
files: tools/start_jarvis.py, tests/tools/test_start_jarvis.py, executor/poller.py (hot), tests/executor/test_poller.py, docs/state.md
resources: none offline; live proof claims live-jobs-table
---

# action-worker — a poller that can actually claim the action kinds

## Gate

**Answered 1 Sep 2026 — Q2 = A.** Third worker, as written. No re-scope,
no schema change. The gate text below is kept for context.

Q2. Written assuming answer A (third worker). If Ali picks B (priority
column), this task is re-scoped by whoever processes the answer — B also
needs Q9's migration machinery first.

## Goal

`flp_sort`, `system_control`, `zoom_join_meeting`,
`whatsapp_desktop_send_message` are registered in `DEFAULT_HANDLERS` but
no running poller ever claims them: `--kind` takes exactly one value and
the two live workers are pinned to `whatsapp_webhook` and
`distill_memory`. Add a third supervised worker claiming only the action
kinds — fast jobs must never queue behind a 130s Ollama extraction.

## Steps

1. Extend `executor/poller.py`'s `--kind` to accept multiple values
   (`nargs="+"`, still validated against `DEFAULT_HANDLERS`) — the
   narrowest change that lets one worker own a set. Single-value callers
   keep working.
2. `tools/start_jarvis.py`: spawn `action-worker` beside the existing two,
   restricted to the four action kinds; it must NOT seed the distill chain
   nor touch the batch heartbeat (only background-worker does). Follow the
   existing supervisor pattern, including per-child logs.
3. Only background-worker's death semantics change nothing: decide
   optional-vs-fatal for the new child the way whisper-server was decided
   (optional; its death degrades actions, not replies) — mirror that.
4. Name every implementer if any Protocol/signature widens (see plan.md's
   cross-lane test-doubles section — `--kind` parsing touches
   `test_poller.py`'s fakes).
5. Tests: kind-set restriction honored (worker never claims outside its
   set), launcher spawns three workers, `--once` unaffected.
6. Update `docs/state.md`'s Executor-topology row and blueprint §3's
   worker sentence if Q2's answer amends it (record as decided by Ali).
7. Live proof: start the stack, enqueue one `system_control` no-op-ish job
   (e.g. wifi enumerate) by hand, watch it claim → done in
   `tools/action-worker.out.log`. Serialize on the live jobs table per
   plan.md rules.

## Done when

Live log shows an action job claimed and completed by the new worker
(cite); full suite green.

## Log

_(empty)_
