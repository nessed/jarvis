---
id: conversation-service-extract
status: done
lane: AUTO
priority: 1
phase: 4
blocked-on: none
files: executor/handlers/whatsapp.py (hot), executor/conversation/ (new), tests/executor/test_whatsapp_handler.py, tests/executor/test_conversation_service.py (new)
resources: none
---

# conversation-service-extract — pull the reply brain out of the WhatsApp closure

## Why

Both 8 Sep architecture reviews (`docs/history/architecture-review-2026-09-08.md`
§8 checklist 3; `architecture-review-fable-2026-09-08.md` §4.1) need the
same thing first: the channel-neutral part of "receive text → recall →
model → reply text" as a unit that the bus (on a VPS), the WhatsApp
handler, and later a desk-voice loop can all call. Today it lives inside
`build_whatsapp_handler`'s closure in `executor/handlers/whatsapp.py`
(roughly lines 417-514: classify, recall, complete, send, remember). Every
other task in this batch edits that file; this one goes first so they edit
a service instead.

## Premise to re-verify

`grep -n "def build_whatsapp_handler\|classify_command\|recall(" executor/handlers/whatsapp.py`
still shows the classify → recall → completion sequence inline in the
handler. If a `ConversationService` (or equivalent) already exists, mark
this `done` with the citation and move on.

## Steps

1. Create `executor/conversation/service.py` with one class whose
   constructor takes the memory interface, the router/completion callable,
   and the command classifier as injected dependencies (the existing test
   doubles in `tests/executor/test_whatsapp_handler.py` — `FakeMemory`,
   `FakeFact`, `FakeSeenStore` — must still fit; name every double you
   touch in the Log). One public method: text in → `ReplyResult` out
   (reply text, optional action proposal, timings dict). No Meta/Graph
   calls inside it; no sqlite paths hard-coded.
2. **Import weight matters.** `bus/` will import this on the VPS
   (`conversation-inline-reply`). It must not pull `torch`, `kokoro`,
   `pywinauto`, `pyflp`, `sounddevice` or `voice/` transitively. Prove it:
   `python -c "import executor.conversation.service, sys; print(sorted(m for m in sys.modules if m.split('.')[0] in {'torch','kokoro','pywinauto','pyflp','sounddevice','voice'}))"`
   must print `[]`. Cite it.
3. Rewire `build_whatsapp_handler` to call the service; keep dedup,
   typing cue, download/STT/TTS, send and `remember` exactly where they
   are. Behaviour must be byte-identical for text: run
   `tools/replay_job.py` on an existing captured payload before and after
   and diff the outbound send.
4. Tests: the handler suite stays green unchanged; new
   `tests/executor/test_conversation_service.py` covers the pure path with
   fakes (classify skipped over 300 chars, recall failure → still answers,
   model failure → surfaced).

## Done when

Full offline suite green, the import-weight command prints `[]`, and
`whatsapp.py` no longer contains the classify/recall/complete sequence
inline. Log cites all three.

## Log

**8 Sep 2026 — done (lane-2).**

Premise re-verified before starting: the sequence was still inline.

```
$ grep -n "def build_whatsapp_handler\|classify_command\|recall(" executor/handlers/whatsapp.py
34:    classify_command,
280:    ``recall()`` runs either way.
342:    classifier = classify or (lambda text: classify_command(text, complete=completion))
477:            recalled = memory.recall(message_text, user_id=inbound.sender)
```

**What moved.** `executor/conversation/service.py` (341 lines) holds
`ConversationService.reply(text, *, user_id, spoken)` -> `ReplyResult(reply,
action, timings)`, plus `ActionProposal`, `LazyMemory`, the system prompt, the
voice-language note, and the three helpers that were private to the handler
(`fence_recalled_context`, `format_recalled_context`, `extract_reply_text`).
`whatsapp.py` went 573 -> 481 lines and now holds only the WhatsApp half.

**Two deliberate shape choices, both to keep behaviour identical:**

- *Actions are proposed, not enqueued.* The queue row carries a `notify`
  descriptor that only the channel can fill in, so the service returns an
  `ActionProposal` and the handler enqueues it and formats `queued_reply()`
  with the job id. `ActionProposal.confirmed` preserves the two distinct log
  lines ("confirmed action enqueued" vs "action enqueued from message").
- *`LazyMemory` wraps the opener.* The constructor takes the memory interface
  as specified, but a command message must not pay to load the embedding
  runtime before the classifier has spoken — that cost sat after the classify
  step before this change, and it still does.

The two `_deliver` paths (command reply, conversational reply) collapsed into
one, since after hoisting the store open they were identical bar a log string.

**Test doubles touched** (step 1's requirement to name them): none changed.
`FakeMemory`, `FakeFact`, `FakeSeenStore`, `FakePendingStore` and
`FakeEnqueuer` in `tests/executor/test_whatsapp_handler.py` all still fit
unedited — that file is untouched by this task. The new
`tests/executor/test_conversation_service.py` re-declares the same shapes
against the service directly (27 tests).

**Import weight (step 2).**

```
$ .venv/Scripts/python.exe -c "import executor.conversation.service, sys; print(sorted(m for m in sys.modules if m.split('.')[0] in {'torch','kokoro','pywinauto','pyflp','sounddevice','voice'}))"
[]
```

Asserted from now on by
`tests/executor/test_conversation_service.py::test_the_service_stays_light_enough_for_the_offbox_bus`,
which runs that same command in a subprocess.

**Behaviour unchanged (step 3).** `tools/replay_job.build_replay_handler`
driven over six scenarios — text / allowlisted command / confirmation-needed
command, each with `handle_commands` off and on — with the provider and the
turn store faked so the diff is behaviour, not the model's mood. Captured
before the change and after:

```
$ diff replay_before.txt replay_after.txt && echo IDENTICAL
IDENTICAL
```

Every outbound send, every enqueued payload (including the `notify`
descriptor), both memory writes, the typing cue and the routed-call count are
byte-identical across all six.

**Full offline suite.**

```
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-2
1461 passed, 9 deselected in 66.15s (0:01:06)
```

1434 -> 1461: the 27 new service tests, no handler test changed.

**For the tasks behind this one.** `ReplyResult.timings` already carries
`classify` / `recall` / `model` seconds — `latency-spans` has somewhere to put
per-stage numbers without reopening the hot file. `LazyMemory` is the seam
`hotpath-quick-wins` replaces with a per-process runtime.
