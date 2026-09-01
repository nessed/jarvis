---
id: voice-command-ingress
status: blocked
lane: AUTO
priority: 2
phase: 3
blocked-on: voice-loop
files: bus/main.py (hot), tests/bus/, voice/loop.py, tests/voice/test_loop.py
resources: none offline
---

# voice-command-ingress — the desk loop reaches the queue

## Gate

**Answered 1 Sep 2026 — Q7 = A, narrowed.** `POST /command`, bearer-authed,
**enqueue-only**: it writes a job and returns its id. It must not execute
inline, and must not grow a synchronous execution path later. The worker
stays the only thing that runs jobs. Still blocked on `voice-loop`.

Q7 (endpoint vs direct enqueue) and `voice-loop` landed (it leaves the
seam this fills).

## Steps (assuming Q7=A, `POST /command`)

1. Bearer-authed `POST /command` on the bus: body = command text + source
   tag; validates, enqueues `whatsapp_webhook`-shaped work or (once
   `enqueue-classifier` exists) rides the same classification path so
   voice and WhatsApp commands behave identically. Enqueue-only, like the
   webhook.
2. Wire `voice/loop.py`'s command seam to POST it; spoken acknowledgment
   from the reply.
3. Tests: auth required, malformed rejected loudly, enqueue payload shape,
   loop-side fake-transport coverage.
4. If Q7=B instead, scope shrinks to the loop calling `db.jobs.enqueue`
   directly — note that this dies at Phase 4 cutover and record Ali chose
   it anyway.

## Done when

A spoken command lands in the queue and gets executed + spoken reply,
proven live or via replay-harness (cite); suite green.

## Log

_(empty)_
