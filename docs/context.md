# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `c91279c Fix run_backfill's usage docstring and record a near-miss with live traffic` on `main`, 8 ahead, 0 behind origin.

**Working tree:** 1 changed

```
  A  docs/scalability-review.md
```

**Offline suite:** 152 passed, 1 deselected in 4.56s _(recorded 2026-08-27)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `c91279c` Fix run_backfill's usage docstring and record a near-miss with live traffic  _(2026-08-27)_
- `129de3a` Disable conversation memory writes by default  _(2026-08-27)_
- `f11cbb8` Fix three bugs that stopped live WhatsApp replies, and reply before remembering  _(2026-08-27)_
- `afa6b58` Add a resumable backfill runner over the opted-in intake folder  _(2026-08-26)_
- `5b9c7d6` Close the retry_health and verify-token-logging blockers in state.md  _(2026-08-26)_
- `fb2eead` Wire retry_health into /status and redact the Meta verify token from access logs  _(2026-08-26)_
- `aea3109` Dedup whatsapp_webhook by Meta's message id  _(2026-08-26)_
- `e889732` Record the first live WhatsApp round trip through whatsapp_webhook  _(2026-08-26)_

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
local Ollama and replies stop — re-violated once already, no harm done only
because no message arrived mid-run. Checkpoint sits at chunk 1/24 of
`ingest/data/me.txt`; resume only after confirming `/status` shows
`queued`/`running` both 0.

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
