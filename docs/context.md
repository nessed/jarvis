# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `c4cc48d Make the inspector read the two .flp files PyFLP gives up on` on `main`, 7 ahead, 0 behind origin.

**Working tree:** 24 changed (plus 6 untracked)

```
  A  .claude/hooks/_harness.py
  A  .claude/hooks/harness_guard.py
  A  .claude/hooks/harness_prompt.py
  A  .claude/hooks/harness_session_start.py
  A  .claude/hooks/harness_stop.py
  M  .claude/settings.json
  M  .githooks/pre-commit
   M .gitignore
  M  CLAUDE.md
  M  agents.md
  A  docs/board/HANDOFF.md
  M  docs/board/README.md
  ...and 12 more
```

**Offline suite:** 1289 passed, 9 deselected, 10 warnings in 64.61s (0:01:04) _(recorded 2026-09-02)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `c4cc48d` Make the inspector read the two .flp files PyFLP gives up on  _(2026-09-02)_
- `6bd3ad4` Apply Ali's blueprint corrections, and keep one line the audit was wrong about  _(2026-09-02)_
- `10be80b` Give the router a ledger that outlives one call, and let /status see it  _(2026-09-02)_
- `34b4bc0` Write the whole Oracle side of Phase 4 before the account exists  _(2026-09-02)_
- `84f6d42` Let a WhatsApp message enqueue a real action, on a closed allowlist  _(2026-09-02)_
- `31c1c64` Add the job replay harness and the blueprint's facts check  _(2026-09-02)_
- `0ff4e1a` Give the four orphaned job kinds a worker that can actually claim them  _(2026-09-02)_
- `e4129df` Fold Ali's ten answers into the board, blueprint and state  _(2026-09-01)_

<!-- END GENERATED -->

## Now

**Phase 2's producer/consumer gap is closed and the router's ledger is real.**
Three tasks landed 2 Sep: `action-worker` (a poller for the four action job
kinds), `enqueue-classifier` (WhatsApp text becomes action jobs), and
`router-cooldown-ledger` (process-lifetime cooldowns, and `/status` now serves
the ledger of the process that actually routes). Work the NEXT order in
`docs/board/README.md`; do not ask what is next.

**The multi-session harness landed 2 Sep.** Hooks in `.claude/hooks/`
register each terminal as a lane, refuse writes to a live peer's claimed
files, gate `git commit` on `git-commit`, deliver peer messages, and keep the
board loop running after `go`/`resume`. Panes opened before it landed keep
the old rules until reopened. `python tools/work_board_claim.py status` says
what every terminal is doing. Brief: `docs/tasks/agent-harness.md`.

**Three things are Ali's, and only these:**

- **Q12 — drop Pipecat from the desk loop?** Blocks `voice-loop` and
  `voice-command-ingress` behind it.
- **Q11** — how long the router's "verification window" is. Blocks only
  `router-eligibility-window`.
- **U2** — the five model IDs are still absent as key names in `.env`, and
  this is now costing two measurable things. `groq` and `cerebras` sort to the
  front of every request and are silently skipped ("no model configured"), so
  the ladder collapses to `openrouter/free`; and that rung answered the
  command classifier with `User Safety: safe` instead of JSON on two of four
  probes. Commands fail safe, but they are only as reliable as that rung.

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
