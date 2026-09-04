# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `8b90d89 Stop paying a TLS handshake per call, and start the stack in parallel` on `main`, 1 ahead, 0 behind origin.

**Working tree:** 2 changed

```
  M  docs/board/USER-TASKS.md
  M  docs/history/infra-audit-2026-09-04.md
```

**Offline suite:** 1434 passed, 9 deselected in 62.42s (0:01:02) _(recorded 2026-09-05)_

**Live acceptance suite:** 1 passed, 1 warning in 34.04s _(recorded 2026-09-03)_

**Recent commits**

- `8b90d89` Stop paying a TLS handshake per call, and start the stack in parallel  _(2026-09-04)_
- `ca8a767` Bring the README back in line with what the code does  _(2026-09-03)_
- `669b47b` Write this week's handoff  _(2026-09-03)_
- `ba80f71` Keep the commit gate off the internet  _(2026-09-03)_
- `7647c67` Audit the board, and find backfill blocked on a contradiction  _(2026-09-03)_
- `ec8ae8e` Let a bare pytest work, and stop two lanes deleting each other's temp files  _(2026-09-03)_
- `e0609bc` Generate the provider lists instead of typing them  _(2026-09-03)_
- `d8b1970` Order the ladder by what a rung costs, then by how fast it actually is  _(2026-09-03)_

<!-- END GENERATED -->

## Now

**4 Sep: the lag audit landed.** Ali asked for speed. Measured, then fixed
inline: every client was rebuilt per call (queue claim 2 s -> 0.3 s, Graph
0.8 s -> 0.24 s, routed call 2.0 s -> 0.8 s), Kokoro rebuilt per reply
(now cached + warmed), the launcher ran serially and orphaned children (now
parallel, job-object). `docs/history/infra-audit-2026-09-04.md` has every
number. Nothing `ready` remains but `board-audit`.

**His, and only these:**

- **U15** — kill the two orphaned whisper-servers (PIDs in USER-TASKS).
- **U16** — run `start-jarvis.bat`, report the banner's seconds and how
  long a text and a voice reply take now.
- **Q15** — Groq Whisper primary (one env var), local turbo, or keep the
  11-18 s lag. Recommendation: A now, B later.
- **U7** — Oracle signup. That *is* "deploy": `infra/` and the runbook are
  written and validated; the account needs his card.
- Still open from 3 Sep: **U2**, **U12**, **U14**, **Q11**, **Q12**.

**Standing constraint:** the FLP writing half stays unbuilt — `PARKED.md`.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
