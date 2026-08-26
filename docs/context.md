# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `fb2eead Wire retry_health into /status and redact the Meta verify token from access logs` on `main`, 3 ahead, 0 behind origin.

**Working tree:** 1 changed

```
  M  docs/state.md
```

**Offline suite:** 137 passed, 1 deselected in 4.58s _(recorded 2026-08-26)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `fb2eead` Wire retry_health into /status and redact the Meta verify token from access logs  _(2026-08-26)_
- `aea3109` Dedup whatsapp_webhook by Meta's message id  _(2026-08-26)_
- `e889732` Record the first live WhatsApp round trip through whatsapp_webhook  _(2026-08-26)_
- `98383ef` Make context_status --check detect rot, not normal lag  _(2026-08-26)_
- `eb510d7` Split the context system by rate of change  _(2026-08-26)_
- `6e4420b` Document the whatsapp_webhook handler and fix the pytest command  _(2026-08-26)_
- `27663d9` Wire the whatsapp_webhook handler into the executor  _(2026-08-26)_
- `24cf31c` Rewrite README in plain language  _(2026-08-26)_

<!-- END GENERATED -->

## Now

The real end-to-end WhatsApp round trip landed 26 August 2026 — see
`docs/history/whatsapp-live-roundtrip.md`. The message-id dedup gap it
surfaced is fixed: `SeenMessageStore` (`executor/handlers/whatsapp.py`) marks
a message sent only after a reply actually goes out, so a failed attempt
still retries normally but a Meta redelivery of an already-answered message
is a silent no-op. The live executor was restarted to pick this up.

Next candidate, not yet started: wire `retry_health()` into `bus/main.py`'s
`/status` route (another session appears to be mid-edit on that file already
— check before starting).

## Waiting on you

Nothing. The bus, tunnel, and executor were left running from the live test;
the tunnel URL will die next time `cloudflared` restarts and needs
re-pointing then, not now.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
