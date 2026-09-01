---
id: blueprint-corrections
status: blocked
lane: AUTO
priority: 2
phase: docs
blocked-on: Q10
files: docs/blueprint.md, docs/state.md
resources: none
---

# blueprint-corrections — apply the approved factual fixes

## Gate

Q10 (blanket approval; apply only the letters Ali approved).

## Steps

1. Apply `docs/audit/blueprint-drift.md` §3.7 + §3.8 verbatim in spirit:
   DeepSeek peak windows are Mon–Fri; delete the resolved price-change
   caveat; correct Cerebras (free tier abolished 17 Aug 2026, never served
   GLM) and Groq (`llama-3.1-8b-instant` retired 16 Aug 2026); reconcile
   NIM's rung-3 listing with its own geo-block amendment; drop the
   "200 RPM raise" claim; rewrite 1.3's extraction sentence to what
   shipped (Mem0 Ollama adapter, `json_object` + pydantic + one retry).
2. If Q10b approved: restate the chain as 9 rungs as decision-only,
   delegating live status to state.md's table; number the facts-check job
   as a Phase 0.8 deliverable (the tool exists by then or its task is on
   this board).
3. If Q10c approved: write the cooldown ledger's process-lifetime scope
   into 0.6 (unblocks `router-cooldown-ledger` if not already flipped).
4. Mark each edit `[UPDATED <date>, approved by Ali via QUESTIONS.md Q10]`
   in the blueprint's own tag style.
5. Re-verify each claim against a current source before writing it —
   the audit is from 27 Aug; anything might have moved again.

## Done when

Blueprint carries no known-false provider claims; each edit tagged;
sources cited in the Log here.

## Log

_(empty)_
