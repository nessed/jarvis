# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `d3094ad Make a second stack impossible and run distillation on the queue` on `main`, in sync with origin.

**Working tree:** 26 changed

```
  M  .gitignore
  M  bus/logging.py
  M  db/jobs.py
  A  docs/audit/blueprint-drift.md
  M  docs/blockers/pyflp-python-312.md
  A  docs/blockers/tool-result-injection.md
  A  docs/consults/2026-08-27-lane-a-was-approved-to-install/prompt.md
  A  docs/consults/2026-08-27-lane-a-was-approved-to-install/response.md
  A  docs/consults/2026-08-27-lane-a-was-approved-to-install/verdict.json
  M  docs/context.md
  M  docs/state.md
  A  docs/tasks/distill-chain-verification.md
  ...and 14 more
```

**Offline suite:** 291 passed, 4 deselected in 5.90s _(recorded 2026-08-27)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `d3094ad` Make a second stack impossible and run distillation on the queue  _(2026-08-27)_
- `1527ee9` Gitignore test_projects/ before real .flp guinea pigs land  _(2026-08-27)_
- `09363de` Record the duplicate start_jarvis.py incident in context.md  _(2026-08-27)_
- `a7a2030` Reconcile the context docs with what actually landed tonight  _(2026-08-27)_
- `0de7c89` Add one-command startup so the whole stack comes up together  _(2026-08-27)_
- `607bde1` Add PyFLP proof-of-concept scaffolding for Phase 2  _(2026-08-27)_
- `123b724` Pin the queue client timeout so a hung connection can't stall every message  _(2026-08-27)_
- `603cec6` Make conversation memory work by taking extraction off the reply path  _(2026-08-27)_

<!-- END GENERATED -->

## Now

**The stack is up and Meta is pointed at it.** QUIC is unroutable on this
network, so the launcher now forces cloudflared's http2 transport
(`JARVIS_TUNNEL_PROTOCOL`); without it the tunnel minted a URL that resolved
nowhere. Meta's handshake landed on the live tunnel. The one untested link is a
real inbound message from the user's phone.

Two injection fixes landed. Recalled memory reached the model as a **system**
message, so stored inbound text carried operator authority; it is now
user-role and fenced. `tools/consult.py` framed sub-model output the same way.
The distill chain gained a fork guard evaluated at the write site, and
`assert_timeouts_ordered` finally has production callers.

PyFLP works on `.venv311`, pinned to **3.11.5** — 3.11.6 backported the
empty-enum guard, so plain "3.11" is not enough. Blocker 4 is resolved.

## Waiting on you

1. **Rotate the Meta verify token.** It was written to `tools/bus.out.log` in
   plaintext — the redaction only matched `hub.verify_token`, and the live
   handshake also carried `hub_verify_token`. Gitignored, never committed, now
   fixed both ways.
2. **Send one WhatsApp message** to the test number so the reply path is proven
   end to end.
3. **Phase 2 needs real `.flp` copies** in `test_projects/` and the dictated
   mixer-sorting convention. Both are yours; PyFLP itself is unblocked.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
