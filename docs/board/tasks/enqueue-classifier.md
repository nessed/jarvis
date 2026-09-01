---
id: enqueue-classifier
status: blocked
lane: AUTO
priority: 1
phase: 2
blocked-on: Q1, Q2, action-worker
files: executor/handlers/whatsapp.py (hot), tests/executor/test_whatsapp_handler.py, docs/state.md
resources: none offline; live proof uses the live inbound route
---

# enqueue-classifier — WhatsApp text becomes real action jobs

## Gate

Q1 (consent + which kinds are allowlisted) and `action-worker` landed —
shipping a producer whose jobs queue forever is the failure mode plan.md
explicitly warned about. **The allowlist is exactly what Ali's Q1 answer
says.** No kind joins it by agent judgment; `flp_sort` stays out while the
convention gap stands (PARKED).

## Scope note

plan.md characterized this job as "writes three of the hot files plus a
live migration". This board deliberately narrows it: classification lives
in the handler (one hot file), and the migration machinery moved to
`db-maintenance`. If implementation forces a second hot file, claim it
and say so — don't inherit the old scope silently.

## Goal

Blueprint 4.4's classifier, laptop-era scope: inbound WhatsApp text that
is a command ("join my zoom meeting", "turn wifi off") enqueues the
matching action job and replies with what it did/queued; everything else
continues down the existing conversational path unchanged.

## Steps

1. Classification happens in the handler (executor side), not the bus —
   the webhook stays validate/dedup/enqueue-only per blueprint §3.
2. Start deterministic: intent parsing via the routed model with a
   constrained JSON verdict (allowed kinds enum + args + confidence), fall
   back to conversation on low confidence. The verdict prompt treats
   message text as data — it rides inside the same fenced discipline the
   recall path uses; a message cannot name a kind outside the allowlist.
3. Destructive/irreversible actions (per Q1's answer): reply asking for an
   explicit confirm; only a confirming reply enqueues. Store pending
   confirmations like the dedup stores do (sqlite, injected, tested).
4. Every enqueued action gets a reply naming the job and, on completion
   (poll or later), its outcome — silence is failure here.
5. Tests against fakes for: allowlisted kind → job enqueued with right
   payload; non-command → conversation unchanged; disallowed kind
   requested → refusal reply, no job; confirm flow; low confidence →
   conversation.
6. Live proof end-to-end for one harmless kind (wifi status or zoom join
   with a test link), from Ali's phone or replay-harness.

## Done when

Live (or replayed-live) proof cited; suite green; state.md updated.

## Log

_(empty)_
