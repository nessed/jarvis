---
id: latency-spans
status: done
lane: AUTO
priority: 1
phase: 4
blocked-on: conversation-service-extract (same hot file; sequence, not a gate)
files: executor/conversation/service.py, executor/handlers/whatsapp.py (hot), executor/poller.py (hot), tools/reply_latency.py (new), tests/executor/, tests/tools/test_reply_latency.py (new), tests/live/test_text_reply_latency.py (new)
resources: none (live test needs meta-webhook awareness: it sends one real message)
---

# latency-spans — measure the reply path per stage, every job, automatically

## Why

The only reply-path numbers we have are one hand-run audit
(`docs/history/infra-audit-2026-09-04.md`, ~10 s text / 25-50 s voice).
Every task in this batch claims to make that faster; without per-stage
timing on every real job, "faster" is a guess. Astra §8 step 1 and Fable
§6 week 1 item 6 both make this the first deliverable. `ddfd7ed` recorded
a measurement in docs only — nothing in code emits timings today
(`grep -rn "span\|elapsed" executor/handlers/whatsapp.py` to confirm).

## Steps

1. In the service and handler, wrap each stage with a monotonic timer:
   `queue_wait` (job `created_at` → claim), `classify`, `recall`, `model`,
   `stt`, `tts`, `send`, `remember`, `total`. Emit **one** structured
   INFO line per job: `reply-latency job=<id> kind=<kind> total_ms=…
   queue_wait_ms=… classify_ms=… …`. No message text in the line, ever.
2. `tools/reply_latency.py`: reads the executor log(s), prints p50/p95 per
   stage over the last N jobs, `--json` for machines. Unit-tested on a
   fixture log.
3. `tests/live/test_text_reply_latency.py` (marked `live`): sends one real
   text via the existing live-probe path, waits for the reply, and
   **records** total and per-stage ms into its output. It asserts only
   that the line was produced. The threshold assertion (p50 < 3 s etc.) is
   `live-latency-acceptance`, gated on Q17-D13 — do not add it here.
4. Run the live test once with the stack up and cite the line. That is the
   baseline every later task compares against.

## Done when

A real job produces the `reply-latency` line; `tools/reply_latency.py`
summarises it; both cited in the Log with the offline suite green.

## Log

**8 Sep 2026 — done, with one step carried to U20 (lane-2).**

Premise re-verified: nothing emitted timings.

```
$ grep -rn "span\|elapsed" executor/handlers/whatsapp.py
$ echo $?
1
```

**Step 1 — spans.** New `executor/latency.py`: `ReplySpans`, a
`stage(name)` context manager, `mark_claimed`/`take_claimed_at`, and one
rendered line. The poller stamps the claim time (`poll_once`, right after
`claim_next`) so `queue_wait` means "how long it sat in the queue", not "how
long until the handler looked" — the checkpoint write sits between the two.
The handler times `cue`, `stt` (download + transcribe), `send`, `tts` and
`remember`; `classify`, `recall` and `model` come from
`ReplyResult.timings`, which `conversation-service-extract` already
produced. `cue` is measured beyond the specified list because it is a Graph
API round trip on the critical path and the next task targets it.

Only a job that replies emits a line. A status callback, a duplicate
webhook, a voice note that transcribed to nothing and a failed reply all
stay silent, because a no-op timed at 3 ms drags every percentile down.
**No message text ever reaches the line** — a test walks every field and
asserts it is a name or an integer.

**Step 2 — the tool.** `tools/reply_latency.py` reads the worker logs and
prints p50/p95/max per stage, `--json` for machines, `--last N` to window.
Percentiles are nearest-rank, so every number printed was observed; under
20 samples it says in words that its p95 is the slowest sample rather than
quietly printing one.

**Step 3 — the live test.** `tests/live/test_text_reply_latency.py`, marked
`live`. It enqueues one probe job, waits for that job's `reply-latency`
line, records every stage via `record_property`, prints them, and asserts
only that the line was produced. No threshold — that is
`live-latency-acceptance`, gated on Q17-D13.

**Step 4 — not run; carried as U20.** The test skips, correctly:

```
$ .venv/Scripts/python.exe -m pytest -q -m live tests/live/test_text_reply_latency.py -rs
SKIPPED [1] tests/live/test_text_reply_latency.py:97: JARVIS_LIVE_WHATSAPP_TO is not
set. It must be a number on the Meta app's test-recipient allow-list; it is not
stored in the repo on purpose.
1 skipped in 0.05s
```

Two gates, both the user's: no recipient number is configured (a phone
number is personal data and this file is committed), and the stack has been
down since 4 Sep — `tools/whatsapp-worker.out.log` last written
`2026-09-04 20:11:21`. Raised once as **U20**.

**What was measured instead.** The real handler, over
`tools/replay_job.build_replay_handler`, with real loopback Ollama recall
and real `route_sync` provider calls; only the Graph API send and the
memory write are faked, so `cue_ms`, `send_ms` and `remember_ms` read 0 by
construction. Three runs, synthetic probe text:

```
2026-09-09 00:25:50 reply-latency job=replay-from-file kind=whatsapp_webhook total_ms=40125 cue_ms=0 classify_ms=33191 recall_ms=2357 model_ms=4572 send_ms=0 remember_ms=0
2026-09-09 00:27:13 reply-latency job=replay-from-file kind=whatsapp_webhook total_ms=43203 cue_ms=0 classify_ms=8205  recall_ms=1349 model_ms=33640 send_ms=0 remember_ms=0
2026-09-09 00:27:23 reply-latency job=replay-from-file kind=whatsapp_webhook total_ms=6718  cue_ms=0 classify_ms=3834  recall_ms=1284 model_ms=1599  send_ms=0 remember_ms=0
```

```
$ .venv/Scripts/python.exe -m tools.reply_latency --log <replay log>
3 replied job(s)
p95 over fewer than 20 jobs is the slowest sample, not a percentile

stage             p50      p95      max     n
cue             0.00s    0.00s    0.00s     3
classify        8.21s   33.19s   33.19s     3
recall          1.35s    2.36s    2.36s     3
model           4.57s   33.64s   33.64s     3
send            0.00s    0.00s    0.00s     3
remember        0.00s    0.00s    0.00s     3
total          40.12s   43.20s   43.20s     3
```

**The first thing the numbers say.** The classifier is not a rounding
error. Its median call (8.2 s) is longer than the reply call it precedes
(4.6 s), and either call can spike past 30 s on `openrouter/free` — the
4 Sep audit's ~10 s text reply looks like a good day, not a typical one.
Two observations for the tasks behind this one: `recall` at ~1.3 s is real
but small next to the two provider calls, and the run-to-run spread says
`router-client-timeouts` (deadlines) and `single-call-classify-reply` (one
call instead of two) are aimed at the right thing, while
`hotpath-quick-wins` should not expect ~10 s → ~5 s from local levers
alone.

**Full offline suite.**

```
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-2
1503 passed, 10 deselected in 55.09s
```

1461 → 1503: 42 new tests across `tests/executor/test_latency.py`,
`tests/tools/test_reply_latency.py` and a `TestReplyLatencyLine` class in
the handler suite.

**One fix outside the plan.** `ReplySpans` accepts an ISO-string
`created_at` as well as a `datetime`. `tools/replay_job.py` rebuilds jobs
from captured JSON, where PostgREST's timestamps are strings, and the first
full-suite run failed 12 replay tests on `datetime - str`. A queue wait
that cannot be read is now a queue wait that is not reported, never a
crash on the reply path.
