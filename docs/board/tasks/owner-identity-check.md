---
id: owner-identity-check
status: done
lane: AUTO
priority: 2
phase: 4
blocked-on: conversation-service-extract (goes in the service, not the closure)
files: executor/conversation/service.py, executor/handlers/whatsapp.py (hot), .env.example (one line), tests/executor/test_conversation_service.py, docs/state.md (one line)
resources: none
---

# owner-identity-check — HMAC proves Meta sent it, not that Ali did

## Why

Astra §5.1: the webhook signature check verifies the sender is Meta;
nothing in the reply path checks that the WhatsApp sender is Ali before
recalling private memory or enqueueing a laptop action. Today the Meta app
is in dev mode with one allow-listed number, which is what keeps this from
being live-exploitable — and it is the one control that vanishes the day
the app is published (PARKED, but not forever). Verified 8 Sep:
`grep -n "allowlist\|owner" bus/main.py executor/handlers/whatsapp.py`
finds only the *command-kind* allowlist, no sender check.

## Steps

1. `JARVIS_OWNER_WA_ID` (the sender id Meta puts in the payload — key name
   only in `.env.example`; the value is Ali's to paste, **U18**).
2. In the service, before recall and before any action proposal: if the
   sender is not the owner, answer with a fixed generic line, do no
   recall, enqueue nothing, log the sender id at INFO. Fail closed: if the
   variable is unset, every sender is treated as not-owner and the worker
   logs one WARNING at startup saying why replies are generic.
3. Tests for owner / non-owner / unset.
4. `docs/state.md`: one line under the bus/executor component saying the
   check exists and what it gates.

## Done when

Offline suite green with the three cases; Log cites it. The paste (U18) is
what turns it on for real — say so in the Log rather than waiting.

## Log

### 2026-09-09 — done (lane-1); it is **on** and currently refusing everyone until U18

**What it does.** `ConversationService.reply` checks the sender against
`JARVIS_OWNER_WA_ID` before anything else — before the classifier, before
recall, before any action proposal. A sender who is not the owner gets a
fixed line (`NOT_THE_OWNER_REPLY`, "Sorry, I can't help with that."), one
INFO log naming the sender id, and nothing else happens: no recall, no routed
call, no action.

**Fail-closed twice over.** An unset or blank `JARVIS_OWNER_WA_ID` makes
*every* sender a non-owner, not every sender the owner. And the comparison is
exact on the stripped string — no prefix matching, no country-code
normalisation, nothing that could make a different number compare equal.

**The generic line is identical for "not the owner" and "no owner
configured".** A stranger learning which of those it is learns something
about the deployment, and neither answer helps them.

**A gap the task did not name, found by the test I wrote for it.** The gate in
`ConversationService.remember` does not cover the WhatsApp path at all:
`_deliver` in `executor/handlers/whatsapp.py` calls
`memory.remember_turn(...)` directly and never goes through
`ConversationService.remember`. So a stranger's message was still being
written into Ali's memory, which is the *worse* half — recall only reads it,
while a write puts a stranger's words where a later turn recalls them as his
own remembered context. `_deliver` now takes `store_turn`, computed from the
same predicate (`ConversationService.is_owner`, made public for exactly this),
so there is one definition of "the owner" and two call sites that consult it.

**The startup warning is in `executor/poller.py:main`, not at handler-build
time.** `DEFAULT_HANDLERS` is constructed at module import, before
`load_dotenv()` runs, so a value read there is read from an environment that
does not hold it yet — the same reason `assert_timeouts_ordered()` lives in
`main()` and the same reason the owner id is read **per message** rather than
when the closure is built. It is not skipped for `--once`: a diagnostic run
that quietly answers everything generically is the confusion the line exists
to prevent.

**`tools/replay_job.py` gained `--as-owner`, and does not bypass by default.**
Dedup in that tool is reported and then bypassed, because replaying an
already-answered message is the whole point. The owner check is a different
kind of thing: it is access control, and a diagnostic that silently walks
through access control teaches the wrong thing about what production does. So
the default is production behaviour, and `--as-owner` is the explicit way to
replay a payload as though its sender were the owner — which is also what
makes the full reply path exercisable before U18 lands.

**This is live now and it will refuse Ali too.** `JARVIS_OWNER_WA_ID` is
unset, so until **U18** is pasted the bot answers every message, his
included, with "Sorry, I can't help with that." The task said to say so rather
than wait, so: the worker logs one WARNING at startup naming the variable and
saying replies are generic, and the fix is one line in `.env`. The key name is
in `.env.example`; the value is Ali's.

**Verification.**

```
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1
1556 passed, 10 deselected in 62.18s (0:01:02)
```

The three cases the task asked for, and seven more: owner gets the real path;
a stranger gets the flat line with no recall, no action and not even a
classifier call; an unset owner makes everyone a stranger; a blank one counts
as unset; the id is compared exactly (a suffix and a prefix both rejected,
surrounding whitespace stripped); a stranger never writes into memory; the
sender id is logged; the startup warning fires when unset and stays silent
when set; and `owner_wa_id` strips and treats blank as absent. At the handler
level: a stranger gets the flat line while the enqueuer and memory stay
untouched; the owner is read at message time, not closure-build time (proved
by setting the wrong owner, building, then setting the right one); an unset
owner turns away the real owner; and an explicit `owner_id=` beats the
environment, which is the seam `--as-owner` uses. At the poller: warns on
startup when unset, silent when set.

**Existing tests that changed, and why.** Every test in
`test_conversation_service.py` and `test_whatsapp_handler.py` was implicitly
relying on "anyone may talk to this thing". `_service()` now defaults
`owner_id=USER`, and the handler module has an autouse fixture setting
`JARVIS_OWNER_WA_ID` to its default sender — through the environment rather
than the `owner_id=` argument, so the production wiring stays under test.
`test_the_outcome_goes_back_to_whoever_sent_the_command` sends from a
different number and now names that number as the owner; its point (the
descriptor names *this* sender, not a constant) is unchanged.
`test_replay_job.py`'s `build()` names the sender in its own payload.
`test_cli_logs_transient_errors_by_type_then_keeps_polling` asserted on
*every* log record and now filters to `executor.poller`, which is what it
meant.
