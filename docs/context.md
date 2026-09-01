# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `84f6d42 Let a WhatsApp message enqueue a real action, on a closed allowlist` on `main`, 3 ahead, 0 behind origin.

**Working tree:** 23 changed (plus 2 untracked)

```
  A  .dockerignore
   M bus/main.py
  M  docs/board/tasks/phase4-prep.md
  A  docs/tasks/phase4-runbook.md
   M executor/poller.py
  A  infra/.gitignore
  A  infra/README.md
  A  infra/docker/Dockerfile
  A  infra/docker/compose.yaml
  A  infra/docker/requirements-bus.txt
  A  infra/scripts/harden.sh
  A  infra/scripts/install-cloudflared.sh
  ...and 11 more
```

**Offline suite:** 1166 passed, 9 deselected, 10 warnings in 57.43s _(recorded 2026-09-02)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `84f6d42` Let a WhatsApp message enqueue a real action, on a closed allowlist  _(2026-09-02)_
- `31c1c64` Add the job replay harness and the blueprint's facts check  _(2026-09-02)_
- `0ff4e1a` Give the four orphaned job kinds a worker that can actually claim them  _(2026-09-02)_
- `e4129df` Fold Ali's ten answers into the board, blueprint and state  _(2026-09-01)_
- `94551a3` Replace plan.md with a self-serve work board under docs/board/  _(2026-09-01)_
- `bf15f79` Close the Meta token rotation and the FL Studio convention on Ali's instruction  _(2026-09-01)_
- `3695c05` Cover three untested voice CLIs, make the schema drift detector able to fail, and reconcile the docs  _(2026-09-01)_
- `52e2c03` push  _(2026-09-01)_

<!-- END GENERATED -->

## Now

**Phase 2's producer/consumer gap is closed.** `action-worker` gave the four
action job kinds a poller (committed, `0ff4e1a`); `enqueue-classifier` gave
`system_control` and `zoom_join_meeting` a producer, live-verified end to end
on 2 Sep. Work the NEXT order in `docs/board/README.md`; do not ask what next.

**One integration hold.** `enqueue-classifier` is finished and green in
isolation but uncommitted: it broke one test in the `replay-harness` lane's
still-uncommitted files, which that lane holds a claim on. Reported, not
touched — `docs/tasks/enqueue-classifier-crosslane-note.md` has the one-line
fix. Nothing in git is red.

**Three things are Ali's, and only these:**

- **Q12 — drop Pipecat from the desk loop?** Blocks `voice-loop` and
  `voice-command-ingress` behind it. Recommendation and consult filed.
- **Q11** — how long the router's "verification window" is. Blocks only
  `router-eligibility-window`.
- **U2** — the five model IDs are still absent as key names in `.env`. This is
  now costing something real: the router falls back to `openrouter/free`,
  which returned `User Safety: safe` instead of JSON on two of four classifier
  probes. Commands fail safe (they read as chat) but work only as reliably as
  that rung. `live-routing-probe` stays blocked.

**Standing constraint:** the FLP writing half stays unbuilt — no mixer-sorting
convention exists and the placeholder ruleset is unapproved; see
`docs/board/PARKED.md`. Reading `.flp`s is fine.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
