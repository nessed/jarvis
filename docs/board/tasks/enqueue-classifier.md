---
id: enqueue-classifier
status: done
lane: AUTO
priority: 1
phase: 2
blocked-on: none  # action-worker landed 2 Sep 2026 (0ff4e1a)
files: executor/handlers/whatsapp.py (hot), executor/handlers/command_intent.py (new),
  tests/executor/test_whatsapp_handler.py, tests/executor/test_command_intent.py (new), docs/state.md
resources: none offline; live proof uses the live inbound route
---

# enqueue-classifier — WhatsApp text becomes real action jobs

## Gate

**Answered 1 Sep 2026 — Q1 = yes, Q2 = A.** The allowlist is fixed and
closed:

- `system_control` — allowed
- `zoom_join_meeting` — allowed
- `flp_sort` — **excluded** (no convention yet)
- `whatsapp_desktop_send_message` — **excluded**

Anything classified destructive replies with a confirm-first message and
enqueues nothing. Adding a kind to this list needs a new Q, not judgment.
Still blocked on `action-worker` landing — a producer without a consumer is
the failure mode this gate exists to prevent.

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

**2 Sep 2026 — built and live-verified. Commit held, see "Not done" below.**

WhatsApp text can now enqueue action jobs. The classifier lives in a new
module, `executor/handlers/command_intent.py`, called from the handler before
recall and routing — so a *spoken* command works too, because by that point a
voice note is already a transcript.

### What the classifier will and will not do

The model proposes; constants dispose. Every verdict is re-checked against
data before anything is enqueued:

- **The allowlist is a closed tuple.** `system_control` and
  `zoom_join_meeting`, exactly as Q1 answered. `flp_sort` and
  `whatsapp_desktop_send_message` are named as *excluded with a reason*, so
  asking for one gets a real answer rather than being misread as chat.
- **A `system_control` action must exist in the real dispatch table.** The
  classifier keeps its own action table and a test asserts it equals
  `_build_action_registry(SystemControlDeps())`. An action it does not know is
  refused, never enqueued — a job whose action does not exist can only
  dead-letter, and refusing says so in one message instead of three retries.
- **Confirmation is decided by that table, not by the model.** The model's
  `destructive` flag may only *raise* the bar, never lower it. The split is
  reversibility: `wifi.set_enabled` and `power.set_plan` go straight through
  (Ali's own example of a command is "turn wifi off"), while `process.kill`,
  the three `file.*` actions, both `scheduled_task` mutations and both
  printing actions ask first.
- **Unparseable, low-confidence, empty, or over-length input is
  conversation.** The confidence floor is 0.7. A false conversation costs a
  slightly off-topic reply; a false action does something to the laptop.
- **Message text is fenced as data** in its own user turn, markers stripped,
  same discipline as the recalled-context fence beside it.

Confirmations persist in sqlite next to the memory database
(`*.pending-actions.db`), one row per sender, 10-minute TTL. Any message that
is not a plain yes/no retires an outstanding confirmation, so a "yes" later in
a conversation cannot reach back and fire something Ali had moved on from.
Yes/no matching is a word list, not another model call — "did he say yes" is
not a judgment worth a round trip, and a classifier that could mistake a
sentence for a yes is the exact thing a confirmation step exists to rule out.

`JARVIS_WHATSAPP_COMMANDS=0` turns the whole producer off without touching the
allowlist. Default on, per Q1.

### Scope

Per the Scope note: one new module plus the one hot file, as narrowed. The new
module and its test file were claimed and are named here rather than folded
into `whatsapp.py`, which is already 417 lines.

### Offline suite

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp
1126 passed, 1 failed, 9 deselected in 70.04s
```

The one failure is **not this lane's code** and is not in git — see "Not done".
Everything this lane owns is green:

```
tests/executor/test_command_intent.py      54 passed
tests/executor/test_whatsapp_handler.py    50 passed  (36 before, +14 command tests)
```

The 20 pre-existing handler tests now pass `handle_commands=False` with a
comment saying why: they exercise the conversational path, which now runs only
after the classifier declines, and leaving commands on would add a second
routed call and make "the completion call" ambiguous in each of them.

### Live proof

Real handler, real classifier, real router, real `db.jobs.enqueue`, real live
queue, real `action-worker` consuming. The only stubs are the two Graph API
calls — the typing cue and the outbound send — so proving the producer did not
put unsolicited WhatsApp messages on Ali's phone. Both of those are separately
live-verified (`docs/state.md`).

Three runs of "what wifi interfaces does this laptop have?":

```
reply: On it: list wifi interfaces. Queued as job a8b4785b.
reply: On it: list wifi interfaces on laptop. Queued as job d581f3cd.
reply: On it: list wifi interfaces. Queued as job a63ba76b.
```

All three claimed and completed by `action-worker`, read back from the live
table:

```
a63ba76b done attempts=1 {'args': {}, 'action': 'wifi.list_interfaces'}
d581f3cd done attempts=1 {'args': {}, 'action': 'wifi.list_interfaces'}
a8b4785b done attempts=1 {'args': {}, 'action': 'wifi.list_interfaces'}
```

The confirm-first gate and the refusal path, live:

```
inbound: 'kill the chrome process'
reply:   kill chrome process — that one I'd rather confirm first. Reply yes and I'll do it.
inbound: 'no'
reply:   Cancelled — I won't kill chrome process.
inbound: 'sort out the mixer in my FLP project'
reply:   I can't do that one — sorting an FL Studio project is off until there's
         an agreed mixer convention.
```

Nothing destructive ran, and the queue proves it rather than the transcript:

```
process.kill jobs ever enqueued: 0
flp_sort / zoom_join_meeting / whatsapp_desktop_send_message jobs ever enqueued: 0
total system_control jobs: 4   (1 from action-worker's proof, 3 from this one)
```

### A real reliability finding, and it is not this code

The first end-to-end attempt fell through to conversation. Probing the
classifier directly against the live router showed why: the current top rung
is `openrouter/openrouter/free`, and it does not always answer the prompt.
Twice out of four probes it returned the string

```
User Safety: safe
```

instead of JSON — an auto-router handing the request to a moderation model.
The fallback did the right thing (unparseable → conversation, no action), so
the failure mode is "a command is silently treated as chat", never a wrong
action. But it means commands work only as reliably as the rung serving them.

This is **U2's gap, not a classifier bug**: Ali's five model IDs are still
absent as key names in `.env`, so the router falls back to the free
auto-route. It will settle when U2 lands, and `live-routing-probe` is the task
that will confirm it.

### Not done, and named rather than quietly dropped

1. **Step 4's outcome reply.** An enqueued action gets an immediate reply
   naming the job; it does **not** yet get a second reply with the outcome
   once the action worker finishes. Doing it properly means the action job
   carrying a `reply_to` and the *action* handlers sending — which changes
   `system_control`'s documented payload contract and touches two more
   components. That is a wider scope than this task's own Scope note allows,
   so it is filed for `board-audit` as `action-outcome-reply` rather than
   improvised here. Silence is not the failure mode meanwhile: every branch
   already ends in a reply.
2. **The commit.** Held, not skipped. This lane's change broke one test in the
   `replay-harness` lane's *uncommitted* files, which that lane holds a claim
   on and which `agents.md` says to report and leave alone. The pre-commit
   hook runs the whole suite over the working tree, so it refuses. Details and
   the one-line fix: `docs/tasks/enqueue-classifier-crosslane-note.md`.
   Nothing in git is red — the failing file has never been committed.
