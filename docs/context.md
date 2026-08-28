# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `1672f8c Add coverage for four tools that had none` on `main`, 5 ahead, 0 behind origin.

**Working tree:** 23 changed (plus 33 untracked)

```
  M  .gitignore
  M  CLAUDE.md
  M  agents.md
   M bus/status.py
   M docs/blockers/tool-result-injection.md
   M docs/consults/2026-08-27-distill-scheduling-mechanism/response.md
   M docs/consults/2026-08-27-path-smoke-test/response.md
  A  docs/plan.md
   M docs/state.md
  A  docs/tasks/board-claim-tool.md
  A  docs/tasks/board-documentation.md
  A  docs/tasks/review-work-board.md
  ...and 11 more
```

**Offline suite:** 463 passed, 4 deselected in 14.85s _(recorded 2026-08-29)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `1672f8c` Add coverage for four tools that had none  _(2026-08-29)_
- `14629c0` Stop the distill chain's emptiness check from decoding the whole fact table  _(2026-08-29)_
- `b9458fb` Drain the queue without stalling, and stop wasting retries on dead ends  _(2026-08-29)_
- `49719b9` Stop the router silently mis-handling three fallback edge cases  _(2026-08-29)_
- `608dfd7` Fill 18 missing .env.example variables and drop the dead SUPABASE_KEY  _(2026-08-29)_
- `f4c5acb` Log a second, distinct PyFLP failure on a real project  _(2026-08-27)_
- `d08cea3` Let a lane repair a mandated tool it doesn't own  _(2026-08-27)_
- `628b6ea` Close two injection channels, unfork the distill chain, unblock PyFLP  _(2026-08-27)_

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
