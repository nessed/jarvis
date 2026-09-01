---
id: voice-command-ingress
status: blocked
lane: AUTO
priority: 2
phase: 3
blocked-on: Q7, voice-loop
files: bus/main.py (hot), tests/bus/, voice/loop.py, tests/voice/test_loop.py
resources: none offline
---

# voice-command-ingress — the desk loop reaches the queue

## Gate

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
