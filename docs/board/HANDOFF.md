# Handoff — 9 September 2026 (evening pass)

Six more board tasks landed since this morning's handoff. Text replies now
answer without the queue, the brain is packaged for the rented box, and the
provider ladder is proven live rather than assumed.

## What landed

| Commit | Task |
|---|---|
| `ca34952` | `conversation-inline-reply` |
| `9e47b7e` | `bus-offbox-packaging` |
| `138f07f` | `state-facts-refresh` |
| `8738c4a` | `extraction-model-spike` |
| `bb68c9a` | `board-audit` |
| `0f9df38` | `live-routing-probe` |

**A text message no longer waits on the queue.** The bus answers it
in-process the moment the webhook verifies it, instead of enqueueing a job
for a worker to pick up later. Voice notes and anything a message asks the
laptop to do still queue exactly as before. One env var
(`JARVIS_INLINE_REPLY`) rolls it back if a crashed process ever loses a
message in a way that matters in practice.

**The brain — not just the inbox — is packaged for the box your brother is
renting.** The old image shipped only the webhook; this one carries memory
too, so a text reply can be answered entirely off the laptop once it's
deployed. Nothing is deployed yet — `vps-harden-deploy` is that step, and
it is still waiting on the box existing (**U17**).

**Every provider your `.env` names now has a real call behind it, this
afternoon.** Groq, Gemini, OpenRouter and DeepSeek all answered live;
Cerebras confirmed excluded on purpose (Q6's blank model, not a mistake).
Mistral was denied — an HTTP 429 this time, not the 403 you've seen before,
which is more likely this session's own repeated testing than anything
having changed on Mistral's side.

**A model swap was tested and rejected, with numbers.** The blueprint hoped
a smaller local model on the laptop's GPU would beat the current one on
CPU. Measured: it doesn't, at every size tried, and it hit a real
compatibility bug along the way (a thinking-mode chat template that fights
JSON-schema-constrained output). Nothing was switched.

## What needs you

- **U20 — the live latency probe.** Unchanged from this morning: add
  `JARVIS_LIVE_WHATSAPP_TO=<your number>` to `.env`, start the stack for a
  minute, and the agent runs the probe and sends you one real reply. Two
  tasks are waiting on this number specifically to close out their live
  citation.
- **U17 — the rented box.** Once it exists, `vps-harden-deploy` deploys
  today's packaging work onto it. Nothing else in this batch is behind it.
- **Q17-D4 — flip the single-call default?** Still open from this morning;
  the evaluation table is under D4 in `QUESTIONS.md`, 100% agreement, your
  bar was 95%.
- **Q17.3's blueprint deltas** — four small corrections `state-facts-refresh`
  found today (Cerebras' real context size, NIM dropping out entirely,
  Hetzner's plan being unbuyable right now, Kokoro's missing Urdu stated
  plainly) — one blanket yes covers all four.

Everything else outstanding is unchanged in `USER-TASKS.md` and
`QUESTIONS.md`. Nothing there was silently answered.

## What was found along the way, and not asked about

- **Two stale claims in `docs/state.md` and the runbook said U18 was still
  unpasted.** It's done — checked, not assumed. Corrected in place.
- **Three board task gates were half-stale.** Two named `bus-offbox-packaging`
  as a co-blocker after it had landed; one named `latency-spans` the same
  way. Narrowed to their one real remaining gate.
- **`live-routing-probe` had been sitting blocked on an already-cleared
  gate for a while**, unnoticed because the board hadn't been audited since
  3 Sep. That's what today's audit pass exists to catch, and it's why it's
  in this batch at all rather than still waiting.
- **A tiny `max_tokens` budget makes a working provider look broken.** Two
  of the four live-tested models spend their token budget on internal
  reasoning before writing an actual answer; a small cap returns an empty
  reply that reads exactly like a dead rung. Noted in `state.md` so nobody
  loses time to it again.

## What was deliberately not done

- **No model switch.** The extraction spike's numbers argue against it
  today; switching is still yours to decide if a later llama.cpp release
  fixes the compatibility bug found.
- **No live citation for the new inline-reply path.** It needs the same
  `JARVIS_LIVE_WHATSAPP_TO` as U20 above, and Ali's phone number isn't
  something to guess at.
- **No full re-verification of every task on the board.** Today's audit
  checked what changed today and the four gates that looked stale; a full
  pass across all 45 task files is due again once the board has drifted
  further, not this pass.

## Verification

```
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1
1679 passed, 16 deselected in 86.17s (0:01:26)
```

Every commit went through the pre-commit gate, which runs the same full
suite and refuses a red tree. Per-task evidence — the full provider tables,
the extraction benchmark numbers, and the routing probe's live output — is
in each task's `## Log` under `docs/board/tasks/`.
