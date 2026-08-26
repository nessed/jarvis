# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `6e4420b Document the whatsapp_webhook handler and fix the pytest command` on `main`, 1 ahead, 0 behind origin.

**Working tree:** 12 changed

```
  M  .githooks/pre-commit
  M  .gitignore
  M  CLAUDE.md
  M  README.md
  M  agents.md
  M  docs/context.md
  A  docs/history/phase0.md
  A  docs/history/phase1.md
  A  docs/history/process-tooling.md
  A  docs/state.md
  M  docs/workflow_overview.md
  A  tools/context_status.py
```

**Offline suite:** 125 passed, 1 deselected in 5.51s _(recorded 2026-08-26)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `6e4420b` Document the whatsapp_webhook handler and fix the pytest command  _(2026-08-26)_
- `27663d9` Wire the whatsapp_webhook handler into the executor  _(2026-08-26)_
- `24cf31c` Rewrite README in plain language  _(2026-08-26)_
- `b741359` Update docs for the process changes  _(2026-08-26)_
- `b89e203` Replace three human relay steps with mechanism  _(2026-08-26)_
- `8138dc6` pre-workflow change  _(2026-08-26)_
- `a621829` yo  _(2026-08-26)_
- `8fb271f` 11 36 pm 25 aug  _(2026-08-25)_

<!-- END GENERATED -->

## Now

The `whatsapp_webhook` handler is registered and unit-tested: an inbound
message runs recall, routes through the provider ladder, remembers, and replies
through `WhatsAppClient`. Every send so far has gone through a fake transport.

Next: a real end-to-end send. Start the bus and the tunnel, run
`tools/repoint_webhook.py`, send a message from the phone, and confirm a reply
arrives. That also exercises the untested POST path in `repoint_webhook.py`.

## Waiting on you

Nothing.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
