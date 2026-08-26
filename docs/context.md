# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `afa6b58 Add a resumable backfill runner over the opted-in intake folder` on `main`, 5 ahead, 0 behind origin.

**Working tree:** 8 changed

```
  M  docs/context.md
  A  docs/history/whatsapp-reply-failures.md
  M  docs/state.md
  M  executor/handlers/whatsapp.py
  M  memory/mem0_wrapper.py
  M  tests/executor/test_whatsapp_handler.py
  M  tests/memory/test_mem0_wrapper.py
   M tools/run_backfill.py
```

**Offline suite:** 150 passed, 1 deselected in 6.84s _(recorded 2026-08-27)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `afa6b58` Add a resumable backfill runner over the opted-in intake folder  _(2026-08-26)_
- `5b9c7d6` Close the retry_health and verify-token-logging blockers in state.md  _(2026-08-26)_
- `fb2eead` Wire retry_health into /status and redact the Meta verify token from access logs  _(2026-08-26)_
- `aea3109` Dedup whatsapp_webhook by Meta's message id  _(2026-08-26)_
- `e889732` Record the first live WhatsApp round trip through whatsapp_webhook  _(2026-08-26)_
- `98383ef` Make context_status --check detect rot, not normal lag  _(2026-08-26)_
- `eb510d7` Split the context system by rate of change  _(2026-08-26)_
- `6e4420b` Document the whatsapp_webhook handler and fix the pytest command  _(2026-08-26)_

<!-- END GENERATED -->

## Now

Live WhatsApp replies were failing in the field even though every unit test
was green. Three real bugs, all found by replaying the actual failing job
payloads (see `docs/history/whatsapp-reply-failures.md`): migration `0002`
had never been applied live, so nothing could retry; the compact-prompt
patch was not idempotent, so only the first message per executor process
worked; and `max_tokens=128` truncated real extraction JSON mid-string.

The blueprint's step order was amended with the user's authorization: the
handler now sends the reply *before* writing memory, and a memory failure
after the send is logged rather than failing the job. Local CPU extraction
costs 60-130s and was making every reply wait on it — and discarding
already-generated replies when it failed.

## Waiting on you

Nothing. Bus, tunnel and executor are running. The tunnel URL dies whenever
`cloudflared` restarts and needs `tools/repoint_webhook.py` then, not now.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
