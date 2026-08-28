# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `77c07e5 Stop a Meta webhook redelivery from enqueueing a second job` on `main`, 14 ahead, 0 behind origin.

**Working tree:** 2 changed (plus 37 untracked)

```
  M  docs/plan.md
  M  docs/state.md
```

**Offline suite:** 480 passed, 4 deselected, 2 warnings in 16.41s _(recorded 2026-08-29)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `77c07e5` Stop a Meta webhook redelivery from enqueueing a second job  _(2026-08-29)_
- `e4f15a7` Make queue_depths and retry_health O(1) queries, add distill-chain liveness  _(2026-08-29)_
- `ae158b9` Cover OpenAIChatClient construction and pin mem0ai's private-API surface  _(2026-08-29)_
- `a88dd21` Fix context_status --check being unreachable through main()  _(2026-08-29)_
- `c6565c0` Add coverage for distill_memory's CLI, start_jarvis's uncovered paths, and request_completion  _(2026-08-29)_
- `c47d9b4` Cover WhatsAppClient's timeout and non-JSON-error-body paths  _(2026-08-29)_
- `1cb18ed` Close a stale blocker status and fence two unframed sub-model responses  _(2026-08-29)_
- `ed08e62` Wire flp_sort's write-path guard and diff report, and fix stale docstrings  _(2026-08-29)_

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

**The noninteractive Claude consult is unavailable.** Two `tools/consult.py`
attempts launched the CLI but returned no response or verdict; see
`docs/blockers/consult-cli-no-response.md`. Restore the CLI's noninteractive
session without sharing credentials so Class B decisions can use the required
consult path.

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
