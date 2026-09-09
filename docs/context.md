# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `ff59739 Write this evening's handoff` on `main`, 7 ahead, 0 behind origin.

**Working tree:** 3 changed (plus 15 untracked)

```
  M CLAUDE.md
  M  docs/board/tasks/board-audit.md
  M  docs/context.md
```

**Offline suite:** 1679 passed, 16 deselected in 86.18s (0:01:26) _(recorded 2026-09-09)_

**Live acceptance suite:** 1 passed, 1 warning in 34.04s _(recorded 2026-09-03)_

**Recent commits**

- `ff59739` Write this evening's handoff  _(2026-09-09)_
- `0f9df38` Prove the new provider IDs actually serve, live  _(2026-09-09)_
- `bb68c9a` Board audit: unblock live-routing-probe, narrow three stale gates  _(2026-09-09)_
- `8738c4a` Measure Qwen3-4B/llama.cpp against llama3.1:8b for local extraction  _(2026-09-09)_
- `138f07f` Absorb Fable review's 8 Sep provider/speech fact corrections  _(2026-09-09)_
- `9e47b7e` Package the brain, not just the inbox, for the rented x86 box  _(2026-09-09)_
- `ca34952` Answer text messages right away; only voice still queues  _(2026-09-09)_
- `0ff9639` Write the idle circle's colour down, and make it reproducible  _(2026-09-09)_

<!-- END GENERATED -->

## Now

Eleven board tasks have landed 9 Sep, most recently: the brain is packaged
for the AWS box (`bus-offbox-packaging`, amd64, memory/ + conversation
service in the image, `ollama` sidecar); Fable's provider/speech fact
corrections absorbed into `state.md`; a local-extraction spike found
`llama3.1:8b`/CPU still beats Qwen3-4B/llama.cpp on this hardware (no model
switch); `live-routing-probe` confirmed Groq/Gemini/OpenRouter/DeepSeek all
serve live. `HANDOFF.md` is tonight's handoff.

**U20 is the remaining live gap**: no `reply-latency` line has been read
back from a real Graph send since the stack went down 4 Sep, for either the
queue or the new inline path (`JARVIS_INLINE_REPLY`, default on; voice still
queues). Needs `JARVIS_LIVE_WHATSAPP_TO` + the stack up.
Also Ali's: Q17-D4 (single-call flip), U17, Q11-Q15.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
