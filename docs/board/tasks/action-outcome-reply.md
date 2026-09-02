---
id: action-outcome-reply
status: done
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

## Log

### 2 September 2026 — done. The outcome travels as a job, not as a send.

### Step 1: the design choice, consulted rather than picked

`docs/consults/2026-09-02-action-outcome-reply-shape/` — **verdict C,
confidence high**, against the two shapes this task proposed.

Neither proposed shape won:

- **A (the action handler sends)** is disqualified by *retry semantics*, not
  by coupling. A Graph send that raises inside
  `executor/system_control/handler.py` propagates to `poll_once`, which
  retries the whole job — so a failed notification would re-run
  `wifi.set_enabled` or `process.kill` in order to redeliver a message about
  it. It also spreads the Graph token into `action-worker`, which needs none.
- **B (a watcher in whatsapp-worker)** is the sound fallback: it sees any
  terminal state with no poller change. Its cost is a second scheduling
  mechanism plus a local job-id-to-recipient map to survive a restart.

**C: the action handler enqueues a durable `whatsapp_outcome` job.** The
side effect and the message about the side effect get separate retry
lifecycles from machinery that already exists. `whatsapp-worker` already
owns the Graph client and token; it claims the new kind and sends. There is
no watcher state, because the queue is the state.

The verdict named two observations that would flip it to B. **Both were
checked, and neither holds:**

1. *"If this lane cannot touch `executor/poller.py`'s terminal paths."* It
   can — no peer lane is live and the file is claimed.
2. *"If the raw Meta payload is stripped before enqueue, constraint 4's
   weight rises sharply."* It is not. Against the live table:

   ```
   inbound messages in hosted payloads: 49
   message types: {'text': 46, 'audio': 3}
   carry sender phone number: 49
   carry inbound text body  : 46
   ```

   The bus is enqueue-only and enqueues Meta's raw payload, so the sender's
   number and the message body are already in that hosted table on every
   WhatsApp row. B's privacy advantage is one field the table already holds.

That does not make the hosted table a free-for-all, and it did not. What an
outcome payload may carry is bounded at the source: a status word, the
action's own name, and a truncated mechanical rendering of a known return
shape. Never model output, never conversation text, and on the failure side
never more than the exception type plus the fixed-vocabulary slug the poller
already admits.

### What was built

- `executor/notify.py` — the whole seam. `notify_descriptor` /
  `enqueue_outcome`, a 400-char bound, and `enqueue_outcome` **never raises**:
  an action that ran and then could not be reported on is not an action that
  needs re-running.
- `executor/handlers/outcome.py` — the `whatsapp_outcome` kind and
  `render_outcome`. Registered in `DEFAULT_HANDLERS` and added to
  `whatsapp-worker`'s `--kind` list, not `action-worker`'s.
- `executor/system_control/handler.py` — **stopped discarding the action's
  return value** (Step 2). `registry[action](args)` dropped it on the floor,
  and half these actions are questions. `render_result` turns lists, mappings,
  strings and `None` into one bounded line; a setter returning `None` renders
  to nothing, because "Done: turn wifi off. wifi.set_enabled done." is the
  same sentence twice.
- `executor/app_automation/handler.py` — both UIA kinds confirm they
  happened without echoing the chat name or message text back at the user.
- `executor/poller.py` — `_settled_failure` notifies on a **terminal** status
  only (Step 3). Never per retry: three attempts would otherwise be three
  messages for one action. The poller reads a payload field and still does not
  know WhatsApp exists.
- `executor/handlers/whatsapp.py` — the one place that knows who is waiting
  attaches the descriptor, at both enqueue sites (direct and post-confirmation).

**Step 4 is structural, not a flag.** `whatsapp_outcome` is its own kind with
its own handler that only sends; the module imports neither `classify_command`
nor `parse_inbound_message`, and a test asserts that of the source itself. An
outcome cannot re-enter the classifier because there is no path back into it.

### Step 5: tests

21 new, against fakes. Success, failure, dead-letter, no-descriptor,
malformed descriptor, an unenqueueable notification, the length bound, every
return shape `render_result` can meet, both UIA kinds, and a failing UIA
action notifying nothing itself.

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-lane-1
1318 passed, 9 deselected, 10 warnings in 68.43s
```

Four existing `test_whatsapp_handler.py` assertions changed: they pinned the
enqueued payload exactly, and it now carries the descriptor. They were
rewritten through one `_enqueued()` helper that still asserts the action
fields survive untouched, rather than loosened.

### Live proof

The machine half, end to end, against the live queue:

```
INFO executor.system_control.handler: system_control action wifi.list_interfaces completed (job=30215ad3-ee85-426c-bb06-f09951627e60)
INFO executor.notify: enqueued whatsapp_outcome outcome 3388acea-9ba8-4071-8d6d-9e7e31bb2e25 for job 30215ad3 (status=ok)
action job -> ('30215ad3-...', 'done')

outcome 3388acea payload:
  {"action": "wifi.list_interfaces", "detail": "Wi-Fi (connected)",
   "status": "ok", "summary": "list wifi interfaces", "reply_to": "..."}
  would send: 'Done: list wifi interfaces. Wi-Fi (connected).'
```

And the failure half, with `max_attempts=1` so one pass is terminal:

```
INFO executor.notify: enqueued whatsapp_outcome outcome 227e7b90-... for job c156e895-... (status=failed)
c156e895 -> dead_letter, {'message': 'executor handler failed (UnknownSystemControlActionError)'}

outcome 227e7b90 payload:
  {"action": "nonexistent.action", "detail": "UnknownSystemControlActionError",
   "status": "failed", "summary": "do something impossible", "reply_to": "..."}
  would send: "That didn't work - do something impossible failed (UnknownSystemControlActionError)."
```

Both outcome rows were settled with `fail()` and a reason rather than sent:
their `reply_to` is the literal string `PROOF-NOT-A-REAL-NUMBER`, so neither
could ever have reached anyone, and neither is left sitting `queued` against
a recipient that does not exist.

### What is specified and not done

**"Cited from logs" for the inbound half.** The Done-when asks for a live
`system_control` job *enqueued from a WhatsApp message* producing two replies.
Everything downstream of the message is proved above against the live queue.
The message itself is not: it needs the tunnel up and Ali to send one, and
`agents.md` reserves sensory checks for him. Filed as **U14** with the exact
message to send and the exact two replies to expect, rather than sending him
an unprompted "Done:" out of context.
