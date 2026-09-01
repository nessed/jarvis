---
id: blueprint-corrections
status: done
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

## Also correct §3's worker sentence (added 2 Sep 2026 by `action-worker`)

`docs/blueprint.md:119` says the laptop runs "a separate background poller
which claims every other registered kind, including `distill_memory`". That
was never true of the code and is now doubly wrong: `action-worker` landed
2 Sep 2026 and there are **three** pollers, each restricted to a disjoint set.

Replace the clause with what shipped, which is Ali's Q2 = A answer applied:

- `whatsapp-worker` — `whatsapp_webhook` only
- `background-worker` — `distill_memory` only; alone in seeding the
  distillation chain and maintaining the batch heartbeat
- `action-worker` — `flp_sort`, `system_control`, `zoom_join_meeting`,
  `whatsapp_desktop_send_message`; an optional child, since its death leaves
  desktop actions unclaimed but leaves text and voice replies untouched

Keep the sentence's reason intact — slow offline work must not occupy the
reply worker before it can emit Meta's typing cue — because that is exactly
why the action kinds got their own worker rather than being folded into the
background one. Evidence and the live claim: `docs/board/tasks/action-worker.md`.

This is a factual correction to text Ali's own Q2 answer superseded, not a
new decision. It is documentation only, like a/b/c.

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

**2 Sep 2026 — done. Documentation only; no code changed.**

All three letters of Q10 applied, plus the §3 worker sentence added to this
task by `action-worker`.

### b — Ali's §3.3, verbatim

`docs/blueprint.md`'s enumerated 8-rung list under "The routing pattern" is
replaced by his text exactly as written in `QUESTIONS.md` Q10b. Two
implementation notes are appended *below* his text, not woven into it, so the
verbatim block stays verbatim: Claude Max is not a router target
(`tools/consult.py`), and the cooldown ledger is process-lifetime with the
executor reporting health (Q10c, built the same day).

Two further places stated a rung count and now do not — `0.6`'s
"`providers.yaml` with the 8 rungs" and Phase 0's "8-rung fallback chain".
His own rule is that removing a provider is a `providers.yaml` edit plus a
`state.md` line, never a blueprint edit; a count in two other paragraphs
would have made that false on the next roster change.

**The four deltas stand, unimplemented, and are named in this task's body
above.** They were not softened to match today's code:

| §3.3 clause | Where it goes |
|---|---|
| verification window | `router-eligibility-window` (needs Q11) |
| cost class then measured p50 | `router-cost-class-ordering` |
| 401/402/403 cools down *and surfaces* | fold into `router-cooldown-ledger` — **that task shipped 2 Sep without this half**; 402 still `continue`s rather than surfacing |
| generated `providers.yaml` / `state.md` lists | `provider-status-generator` |

`state.md`'s two lists (routable, configured-but-not-routable with a reason
and a date) were deliberately **not** hand-written here. §3.3 says they are
generated; hand-maintaining them would break the rule in the act of obeying
it. `provider-status-generator` owns them.

### b — the facts check is now 0.8

Moved out of "Ongoing" into a numbered Phase 0 deliverable. The argument
writes itself from this very task: two of the provider claims corrected
below were already false on the day the blueprint was written, and nothing
noticed for months. The tool exists (`tools/facts_check.py`, built by the
parallel lane the same day).

### The §3 worker sentence

"a separate background poller which claims every other registered kind" was
never true of the code — `--kind` took exactly one value until 2 Sep 2026, so
the four action kinds had no consumer at all. Replaced with the three-worker
set that shipped (Q2 = A), keeping the sentence's original reason intact,
because that reason is exactly why the action kinds got their own worker.

### a — five factual corrections, each re-verified today

The task's Step 5 says to re-verify before writing, since the audit is from
27 Aug. That mattered: **one of the audit's recommendations was wrong.**

1. **Groq's 8B lane.** `llama-3.1-8b-instant` deprecation was announced
   17 June 2026 alongside `llama-3.3-70b-versatile`; Groq names
   `openai/gpt-oss-20b` as its replacement. The "~14,400 RPD permissive lane"
   the old headline number came from no longer exists.
   Source: console.groq.com/docs/deprecations, re-checked 2 Sep 2026.
2. **Cerebras' free tier is gone**, replaced by a one-time $5 trial credit
   that needs a payment method and expires. It also never served GLM — the
   catalogue is OpenAI gpt-oss, Meta Llama, Alibaba Qwen. Sources disagree on
   the date (21 July per one tracker, 17 August per the audit), so the text
   says mid-2026 and treats the fact, not the day, as settled. Recorded as
   **trial/credit cost class, not free**, which is the distinction Ali's own
   ordering rule turns on.
3. **DeepSeek peak windows are weekdays only** — 01:00-04:00 and 06:00-10:00
   UTC, Monday to Friday; all weekend is off-peak, ~79% of the week cheap.
   Verified against DeepSeek's pricing docs and two independent trackers.
   `router/routing.py` already had the weekday gate, so this was a docs gap,
   not a code bug.
4. **The DeepSeek price caveat is resolved and marked so.** It described the
   6 Aug warning, which the 13 Aug announcement and 16 Aug 16:00 UTC
   effective date settled.
5. **NIM reconciled.** §1.3 said geo-blocked from Pakistan while the routing
   chain listed it as a lane; both cannot be true from one machine. Written
   as: not a laptop lane, still a Phase 4 VPS candidate, and never an
   extraction or embedding target anywhere regardless of geography
   (`CLAUDE.md` non-negotiable 3).
6. **1.3's extraction sentence** now says `json_object` + pydantic + one
   retry, which is what shipped.

### Where the audit was wrong, and what I did instead

§3.8 said to **delete** "200 RPM raise can be requested" from the NIM
section, on the strength of an 11 May 2026 NVIDIA staff comment that no
increase was available.

Re-checked 2 Sep 2026: NVIDIA's own developer forums currently carry multiple
threads of developers applying for exactly that 40→200 RPM upgrade, and
pricing trackers describe it as available on request. **So the line was kept
and qualified** rather than deleted — it is a request, not an entitlement,
NVIDIA publishes no guaranteed quota, and the account's real ceiling is
whatever the response headers say at runtime.

This is a deviation from the letter of §3.8, which Ali approved. It is what
Step 5 asks for — "re-verify each claim against a current source before
writing it; anything might have moved again" — and deleting a currently-true
line would have been the drift this task exists to remove. Flagging it here
rather than burying it: if Ali wants the line gone anyway, that is a one-line
edit.

### Not touched

`docs/blueprint.md` lines naming "Pipecat + Silero VAD" are Q12's, still
unanswered. Left alone.

### Board bookkeeping deferred — `README.md` is claimed by another lane

Two board edits this task would normally make itself are **not applied**:
marking `blueprint-corrections` done in NEXT, and filing
`router-denial-surfacing` for `board-audit`. `docs/board/README.md` is held by
`CORE/agent-harness` (claim `0ba606f0`), which is rewriting `CLAUDE.md`,
`agents.md`, the pre-commit hook and the claim tool itself.

A first attempt edited it anyway — `work_board_claim.py claim` reports a
conflict on stdout and still exits 0, so a `claim && edit` shell chain runs
the edit. Reverted immediately with `git checkout --`, and the file is
byte-identical to HEAD. Worth naming because that exit code makes the
documented "check `list` first, do not proceed on a conflict" protocol easy to
follow and still get wrong, and `agent-harness` owns that tool right now.

**`router-denial-surfacing` needs a home.** Blueprint §3.3 says a rung
returning 401/402/403 cools down **and surfaces the denial**.
`router-cooldown-ledger` shipped 2 Sep with only the cooldown half: 402 still
`continue`s down the chain instead of surfacing, and the 401/403 carve-out is
still Mistral-only (`router/routing.py`). Whoever next holds the board files
it.

### Verification

Documentation only — no code, no tests changed by this task.

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp
1166 passed, 9 deselected, 10 warnings
```

```
git diff --stat docs/blueprint.md
docs/blueprint.md | 65 +++++++++++++++++++++++++++++++++++++++-------------
```
