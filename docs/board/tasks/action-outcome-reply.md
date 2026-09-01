---
id: action-outcome-reply
status: ready
lane: AUTO
priority: 2
phase: 2
blocked-on: none
files: executor/system_control/handler.py, executor/app_automation/handler.py, executor/handlers/whatsapp.py (hot), db/jobs.py (hot), tests/executor/, docs/state.md
resources: live-jobs-table (live proof)
---

# action-outcome-reply — say what the action did, not just that it queued

## Goal

Since 2 Sep 2026 a WhatsApp command enqueues a real job and replies "On it:
turn wifi off. Queued as job a8b4785b." Nothing ever says whether it worked.

`enqueue-classifier`'s own Step 4 asked for the outcome reply and it was
**deliberately not built there**: doing it properly means the action job
carrying a `reply_to`, and the *action* handlers sending — which changes
`system_control`'s documented payload contract and touches two more
components than that task's Scope note allowed. Filed rather than improvised.

Silence is not the current failure mode — every branch already ends in a
reply — so this is completeness, not a bug.

## Steps

1. Decide where the reply comes from, and write down why. Two shapes:
   - the action payload carries `reply_to` and the action handler sends; or
   - a small completion watcher in the WhatsApp worker polls the job it
     enqueued.
   The first couples the action handlers to WhatsApp; the second keeps them
   pure but needs a watcher that survives a restart. This is a real design
   choice — consult on it rather than picking by convenience.
2. Whichever wins, the reply must carry the *result*, not just "done":
   `wifi.list_interfaces` returns a list, and "done" would be useless for a
   question the user actually asked.
3. A failed or dead-lettered action must reply too. That is the case where
   silence is worst.
4. Do not let this path re-enter the classifier: an outcome reply is
   outbound, and nothing about it should look like a new command.
5. Tests against fakes for success, failure, and dead-letter.

## Done when

A live `system_control` job enqueued from a WhatsApp message produces two
replies — queued, then the outcome — cited from logs; suite green.
