---
id: action-worker
status: done
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

**2 Sep 2026 — done.**

Shipped as specified: `--kind` now takes `nargs="+"` (still validated against
`DEFAULT_HANDLERS`), `poll_once` accepts one kind or a set, and
`tools/start_jarvis.py` spawns a third `action-worker` restricted to the four
action kinds. No schema change, no re-scope.

One thing the Steps did not anticipate. `claim_next_job` filters on a single
kind, so a worker that owns four asks four times and takes the first claim. A
fixed ask-order would have made the earlier kinds a de facto priority tier — a
`system_control` backlog holding every `zoom_join_meeting` behind it — which is
the same starvation the two-worker split exists to prevent, just moved inside
one worker. The poll loop therefore rotates the starting kind each turn
(`rotate_kinds`), bounding the wait to one cycle through the set.

Interface check (Step 4): nothing widened for implementers. `poll_once`'s
`kind_filter` widened to `str | Sequence[str] | None`, but `JobRepository`'s
`claim_next(kind_filter: str | None)` is untouched — the set is unrolled into
one single-kind call per ask. The three test doubles that implement it
(`tests/db/test_jobs.py`, `tests/db/test_jobs_integration.py`,
`tests/executor/test_distill_handler.py`) needed no edit and were not edited.

Death semantics (Step 3): optional, mirroring `whisper-server`. A dead
action-worker leaves desktop actions unclaimed; text and voice replies are
untouched, so it must not take bus/tunnel/reply-path down with it.
`--no-heartbeat` like `whatsapp-worker`, because no action handler drives
Ollama — a grep for `ollama|request_completion|route(` across
`system_control/handler.py`, `app_automation/handler.py` and `flp/sort.py`
returns nothing — so marking the executor live would only block the batch
tools that guard on it.

### Offline suite

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp
993 passed, 9 deselected, 2 warnings in 57.21s
```

976 before this task; +17 tests here.

### Live proof

The action-worker child was started with the exact argv and log path
`spawn_workers()` builds for it, captured from the real function:

```
argv: ...\.venv\Scripts\python.exe -m executor.poller --kind flp_sort system_control
      zoom_join_meeting whatsapp_desktop_send_message --no-heartbeat --interval 3
log: C:\Users\Ali\Desktop\jarvis\tools\action-worker.out.log
optional: True
```

The other two workers were deliberately not started: `background-worker` would
seed the distill chain and hold Ollama, and a full `start_jarvis.py` run mints
a Quick Tunnel and re-points Meta's webhook, which is not something to do to
prove a poller while a second agent is working. What the launcher does with all
three is covered by `tests/tools/test_start_jarvis.py`.

Enqueued by hand, read-only (`netsh wlan show interfaces`):

```
enqueued f7b3e7ba-d543-4ae1-83a8-9a74a1180809 system_control queued
```

`tools/action-worker.out.log`, claim -> checkpoint -> handler -> complete:

```
00:40:19 ... rpc/checkpoint_job "HTTP/2 200 OK"
00:40:20 INFO executor.system_control.handler: system_control action
         wifi.list_interfaces completed (job=f7b3e7ba-d543-4ae1-83a8-9a74a1180809)
00:40:26 ... rpc/complete_job "HTTP/2 200 OK"
```

Row read back from the live table:

```
{'id': 'f7b3e7ba-d543-4ae1-83a8-9a74a1180809', 'kind': 'system_control',
 'status': 'done', 'attempts': 1, 'checkpoint': {'phase': 'executor_started'}}
```

First time any of the four action kinds has been claimed by a running poller.
The worker was stopped afterwards; the `live-jobs-table` claim was released.

### Unblocks

`enqueue-classifier` was waiting only on this task.
