# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `f11cbb8 Fix three bugs that stopped live WhatsApp replies, and reply before remembering` on `main`, 6 ahead, 0 behind origin.

**Working tree:** 6 changed

```
  M  docs/context.md
  M  docs/history/whatsapp-reply-failures.md
  M  docs/state.md
  M  executor/handlers/whatsapp.py
  M  tests/executor/test_whatsapp_handler.py
   M tools/run_backfill.py
```

**Offline suite:** 152 passed, 1 deselected in 5.87s _(recorded 2026-08-27)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `f11cbb8` Fix three bugs that stopped live WhatsApp replies, and reply before remembering  _(2026-08-27)_
- `afa6b58` Add a resumable backfill runner over the opted-in intake folder  _(2026-08-26)_
- `5b9c7d6` Close the retry_health and verify-token-logging blockers in state.md  _(2026-08-26)_
- `fb2eead` Wire retry_health into /status and redact the Meta verify token from access logs  _(2026-08-26)_
- `aea3109` Dedup whatsapp_webhook by Meta's message id  _(2026-08-26)_
- `e889732` Record the first live WhatsApp round trip through whatsapp_webhook  _(2026-08-26)_
- `98383ef` Make context_status --check detect rot, not normal lag  _(2026-08-26)_
- `eb510d7` Split the context system by rate of change  _(2026-08-26)_

<!-- END GENERATED -->

## Now

WhatsApp replies work end to end. Five separate causes had to be cleared —
migration `0002` never applied live, a non-idempotent prompt patch, a too-small
`max_tokens`, a backfill run starving Ollama, and memory writes failing 100% of
the time. All recorded in `docs/history/whatsapp-reply-failures.md`.

Two design consequences, both authorized: the handler replies *before* writing
memory, and conversation memory writes are **off by default**
(`JARVIS_MEMORY_WRITES=1` to re-enable). Local extraction on this CPU cannot
keep up with conversation — that is now the honest Phase 1 blocker in
`docs/state.md`, not a timeout to tune.

Do not run `tools/run_backfill.py` while conversing. It monopolises the single
local Ollama and replies stop.

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
