# Handoff — 9 September 2026

Five board tasks done. The reply path got measurably faster, gained a real
deadline, and gained an identity check it did not have.

**One thing needs you before the bot works at all again:** paste
`JARVIS_OWNER_WA_ID` into `.env` (**U18**). The new owner check is live and
fail-closed, so until that line exists JARVIS answers every message —
including yours — with "Sorry, I can't help with that." The worker says so
once at startup, naming the variable.

## What landed

| Commit | Task |
|---|---|
| `d7c19ef` | `router-client-timeouts` |
| `305a2eb` | `hotpath-quick-wins` |
| `75034ac` | router deadline follow-up |
| `673636a` | `owner-identity-check` |
| `ca95383` | `single-call-classify-reply` |

**Recall stopped costing 1.2 s on every message.** It is 0.10 s now, and it
runs beside the classifier instead of after it, so on the reply path it costs
nothing. Measured both sides the same way — a worktree at the pre-change
commit, same laptop, same prompt, same database. Per-message `recall_ms`
before: 1333, 1283, 1240, 1211, 1311, 1212. After: 1238, 101, 103, 85, 82. The
first message in a process pays; nothing after it does.

**The router now has a deadline it can actually hit.** The OpenAI SDK was on
its defaults — two retries and a 600 s timeout, which is twice the worker's own
job timeout, so it could never be the thing that fired. Now: no SDK retries,
20 s per call on the interactive path, and a whole-cascade budget of one
attempt plus one fallback.

**JARVIS checks who is messaging it.** The webhook signature proved Meta sent
the request; it never proved you did, and that path recalls your private
memory and enqueues actions on your laptop. A stranger now gets one flat line,
no recall, no action, and nothing written into memory.

**One model call instead of two is built, evaluated, and still off.**

## What needs you

- **U18 — paste `JARVIS_OWNER_WA_ID`.** One line. Everything else on the
  reply path is blocked behind it in practice, because the bot is currently
  refusing you.
- **Q17-D4 — flip the single-call default?** The evaluation table you asked
  for is now pasted under D4 in `QUESTIONS.md`. 23 fixtures, both modes,
  against the live router: **100% agreement on every axis** — action, refusal,
  and confirm-first. Your bar was ≥95% on the first two. Recommend flipping
  it; it is a one-line default change plus a test.
- **U20 — the live latency probe.** Two tasks now have a deferred half
  waiting on it. It needs the stack up and a recipient number, and it sends a
  real WhatsApp message, so it is yours to trigger.

Everything else outstanding is unchanged in `USER-TASKS.md` and `QUESTIONS.md`.
Nothing there was silently answered.

## What was found along the way, and not asked about

Three things turned up mid-task that were fixed or recorded rather than
raised as questions:

- **A timeout used to abort the whole provider cascade.** It carries no HTTP
  status, so `route()` read it as a malformed request. Survivable while the
  SDK retried internally; with retries off it would have made things worse.
- **The deadline was not a wall clock.** A `latency` call was measured at
  **92.3 s** on a tree that already had the new deadlines: httpx timeouts are
  per-operation, so a slow-dripping response never trips one. Each attempt is
  now bounded for real (`75034ac`).
- **A stranger's words could still be written into your memory.** The owner
  check in the service did not cover the WhatsApp path, which calls
  `remember_turn` directly. Both call sites now ask the same predicate.

## What was deliberately not done

- **The sqlite handles are still opened per message.** The task asked for them
  to be cached. Measured: the Ollama probe is 463-674 ms and both sqlite opens
  are 7 ms, and caching a connection would need `check_same_thread=False` plus
  a lock in two modules the task does not own, in the path of the poller's
  known abandoned-thread bug. Consulted before deciding, not after —
  `docs/consults/2026-09-09-jarvis-board-task-hotpath-quick-wins`.
- **The single-call default was not flipped.** That is D4, and D4 is yours.
- **No live probe was run.** It sends a real WhatsApp message and needs a
  number that is not in the environment. That is U20, and it is named in both
  affected task logs rather than quietly skipped.
- **The poller still abandons a timed-out handler thread.** The router
  deadlines make it far less likely to fire and do not fix it. Recorded in
  `router-client-timeouts`' log as the remaining gap.

## Verification

```
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1
1575 passed, 10 deselected in 60.02s (0:01:00)
```

Every commit went through the pre-commit gate, which runs the same full suite
and refuses a red tree. Per-task evidence, including the before/after latency
tables and the two-mode evaluation, is in each task's `## Log` under
`docs/board/tasks/`.
