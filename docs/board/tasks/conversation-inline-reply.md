---
id: conversation-inline-reply
status: blocked
lane: AUTO
priority: 2
phase: 4
blocked-on: U20 (live citation only; everything else below is done)
files: bus/main.py (hot), bus/conversation_runner.py (new), executor/handlers/whatsapp.py (hot), tests/bus/, tests/test_integration.py, docs/state.md
resources: none until live; the live check needs the stack up (meta-webhook not changed)
---

# conversation-inline-reply — answer right away; queue only laptop work

## Decision this implements

Ali, 8 Sep 2026 (`QUESTIONS.md` Q17.1, queue question): "for now, answer
right away." Ordinary conversation is handled in-process by the bus after
it returns 200 to Meta; only jobs that need the laptop (`system_control`,
`zoom_join_meeting`, `flp_sort`, `whatsapp_desktop_send_message`,
`distill_memory`) go through the Supabase queue. Explicitly interim: if a
crashed process loses a message in practice, it gets revisited.

## Steps

1. `bus/conversation_runner.py`: after `receive_webhook` has verified,
   deduped and returned `{"accepted": true}`, a FastAPI `BackgroundTask`
   calls the conversation service and sends the reply through the
   existing Graph client. The bus **must not** import executor-heavy
   modules — the service is import-light by construction
   (`conversation-service-extract` step 2); re-run that check from
   `bus.main`.
2. Voice notes keep the queue for now (STT/TTS run on the laptop until
   `hosted-urdu-tts` / Q15 land). Only text takes the inline path.
3. Action proposals from the service still enqueue exactly as today; the
   inline path replies "On it… queued as job …" itself.
4. Env switch `JARVIS_INLINE_REPLY=1` (default **on**, per the answer)
   so the queue path is one variable away as rollback. Record which
   path answered in the `reply-latency` line (`path=inline|queue`).
5. Memory: the bus process now needs the memory runtime (recall +
   remember) on the same host. On the laptop today that is the same
   Ollama/sqlite the worker uses — serialize on `memory/store.py`'s
   WAL; do not open a second extraction path. On the VPS it is the
   packaged memory volume (`bus-offbox-packaging`).
6. Live: stack up, one text from the phone, cite the `reply-latency`
   line with `path=inline` and the total.

## Done when

Offline suite green; the live line shows `path=inline` with
`queue_wait_ms=0`; `docs/state.md` says which kinds queue and which do
not.

## Log

### 2026-09-09 — blocked on U20 (live citation only); everything else done (lane-1)

**Premise re-verified.** Both blocking tasks (`conversation-service-extract`,
`single-call-classify-reply`) were already `done` and their files matched
what their own Logs claim.

**What it does.** `bus/main.py`'s `POST /webhook`, after the existing
webhook-level dedup, now parses the payload with
`parse_inbound_text_message` when `JARVIS_INLINE_REPLY` is not explicitly
off (default on). A real text message is scheduled as a FastAPI
`BackgroundTask` (`bus/conversation_runner.py::build_inline_reply_task`)
instead of being enqueued, and the response is `{"accepted": true}` with no
`job_id` — there is no job. A voice note (`parse_inbound_text_message`
returns `None` for it) and anything the inline reply flag turns off still
enqueue `whatsapp_webhook` exactly as before.

**`bus/conversation_runner.py` (new)** mirrors
`executor.handlers.whatsapp.build_whatsapp_webhook_handler`'s text path —
same `ConversationService`, same action-enqueue shape (`_with_outcome_notice`
carries the same `notify` descriptor), same `queued_reply` acknowledgement —
minus voice (cue/STT/TTS) and minus a second already-sent check, since the
bus's own webhook dedup already decided this message is worth answering.
Reuses `executor.handlers.whatsapp.InboundMessage`,
`parse_inbound_text_message`, `commands_enabled` and `memory_writes_enabled`
directly rather than duplicating them — confirmed non-circular: that module
imports only `bus.whatsapp_client`, never anything from `bus.main` or
`bus.conversation_runner`.

**Import weight (step 1).**

```
$ .venv/Scripts/python.exe -c "import bus.conversation_runner, sys; print(sorted(m for m in sys.modules if m.split('.')[0] in {'torch','kokoro','pywinauto','pyflp','sounddevice','voice'}))"
[]
```

Asserted from now on by
`tests/bus/test_conversation_runner.py::test_the_runner_stays_light_enough_for_the_offbox_bus`
(subprocess, mirrors the service's own version of this test).

**`executor/latency.py` gained a `path` field** (not in this task's listed
files; claimed and edited because the reply-latency line is the only place
"which path answered" can be recorded, and no other lane was running).
`ReplySpans` now carries `path: str = "queue"` — every existing call site is
unchanged and keeps reading `path=queue` — plus a new
`ReplySpans.for_inline_reply(message_id, kind)` that stamps
`created_at == claimed_at` so the line reports `queue_wait_ms=0` explicitly
rather than omitting the field the way a job with no timestamp does. Updated
`tests/executor/test_latency.py`'s "no message text, only names and numbers"
assertion to exempt `path` alongside `job`/`kind`, and added two new tests
for the default and the inline constructor.

**Step 2 (voice keeps the queue) and step 3 (actions still enqueue)** are
both structural: `parse_inbound_text_message` only ever returns non-`None`
for a text message, and `build_inline_reply_task`'s action branch calls the
same `enqueue_action` shape the queue path uses. Covered by
`test_a_voice_note_still_enqueues_instead_of_answering_inline` and
`test_an_action_proposal_is_enqueued_with_the_notify_descriptor_and_the_reply_quotes_the_job_id`.

**Step 4 (`JARVIS_INLINE_REPLY`, default on).** `inline_reply_enabled()` in
`bus/conversation_runner.py`, read the strict way round (only an explicit
off value disables it). `test_inline_reply_disabled_falls_back_to_enqueueing_text_too`
proves the rollback still enqueues text like the old behaviour.

**Step 5 (memory).** `build_inline_reply_task` defaults to the same
`memory.conversation.open_conversation_memory` the queue path uses — no
second opener, no second sqlite path, so the existing WAL serialization
already covers both processes running against the same file today. Nothing
new needed here; verified by reading `memory.conversation.py`'s import graph
matches, not by adding a lever.

**Step 6 (live) — blocked on U20, not attempted further.** Checked what
would be needed to do it now: Ollama is up, and `META_ACCESS_TOKEN`,
`META_PHONE_NUMBER_ID`, `META_APP_SECRET` and `JARVIS_OWNER_WA_ID` are all
set (U18 landed — `docs/state.md` and `context.md`'s stale "refusing
everyone" line are both corrected in this pass). `JARVIS_LIVE_WHATSAPP_TO`
is **not** set, and sending a real Graph message requires a real allow-listed
recipient number — the same personal-data gap `test_text_reply_latency.py`
already gates on and that U20 already names. Not something to guess or ask
for outside the existing tracked item. `docs/board/USER-TASKS.md`'s U20 entry
already covers this; once it lands, hitting the real `/webhook` (not
`db.jobs.enqueue` directly, which would exercise the *queue* path and show
`path=queue`) and reading back `path=inline` closes this.

**Full offline suite.**

```
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1
1620 passed, 10 deselected in 94.04s (0:01:34)
```

1604 -> 1620: 10 new `tests/bus/test_conversation_runner.py`, 4 new
`tests/test_integration.py::TestInlineTextReply`, 2 new
`tests/executor/test_latency.py` path tests.

**`docs/state.md`** gained an "Inline text replies" row (which kinds queue,
which don't, and the U20 gap) and a correction to "Executor topology"'s
"the webhook remains enqueue-only" claim, which this task makes false for
text. The "Owner identity check" row's stale "unset today, refusing
everyone" claim is also corrected — found while checking U18's state for
step 6, not something this task set out to fix, but leaving it would have
left `state.md` self-contradicting the moment this row landed beside it.
