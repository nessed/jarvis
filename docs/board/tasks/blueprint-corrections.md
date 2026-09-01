---
id: blueprint-corrections
status: ready
lane: AUTO
priority: 2
phase: docs
blocked-on: none
files: docs/blueprint.md, docs/state.md
resources: none
---

# blueprint-corrections — apply the approved factual fixes

## Gate

**Answered 1 Sep 2026 — a = yes, c = yes, b = yes with Ali's own text.**

All three letters are approved. For **b**, Ali wrote the replacement
§3.3 himself; it is recorded verbatim in `QUESTIONS.md` Q10b. Apply it
**exactly as written** — it is an instruction, not a draft. It replaces the
enumerated 8-rung list under "The routing pattern"
(`docs/blueprint.md:82-93`), including the rung count, which the new text
explicitly refuses to state.

**This task edits documentation only.** Four clauses of Ali's §3.3 describe
router behaviour that does not exist yet. Do not implement any of them
here, and do not soften the blueprint text to match today's code — the
whole point is that the spec now leads. Verified against the tree on
1 Sep and named here so they become real work rather than quiet drift:

| §3.3 clause | Today | Where it goes |
|---|---|---|
| Eligible needs a verified 200 in a verification window | `_configured()` (`router/routing.py:246-257`) checks key presence only. No `last_verified`, no window — zero grep hits | New task `router-eligibility-window`, gated on **Q11** (window duration + cold-start rule) |
| Cost class first, then measured p50 within class | `providers.yaml` has a static int `priority`. No `cost_class`, no latency measurement — zero grep hits | New task `router-cost-class-ordering` |
| 401/402/403 cools down and surfaces the denial | Generalises the existing Mistral-only carve-out (`routing.py:236-243`) to every provider. 402 currently cools down but `continue`s (`routing.py:227-235`) instead of surfacing | Fold into `router-cooldown-ledger`, which already owns `routing.py` |
| `providers.yaml` + `state.md` lists are *generated*, and `state.md` carries routable / configured-but-not-routable with reason + date | Both are hand-written prose today. No generator exists | New task `provider-status-generator` |

Add those four to the board via `board-audit` — do not create them ad hoc,
and do not start any of them from inside this task.

## Steps for b

1. Replace `docs/blueprint.md:82-93` with Ali's §3.3 verbatim.
2. Leave the surrounding "read rate-limit headers at runtime" paragraph.
3. In the Log, state that b landed as documentation and list the four
   deltas above as unimplemented.

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
