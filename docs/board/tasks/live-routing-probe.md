---
id: live-routing-probe
status: ready
lane: AUTO
priority: 2
phase: 0
blocked-on: none — U2 done 9 Sep 2026
files: tests/live/test_routing.py, docs/state.md
resources: provider-account (spends real allowance)
---

# live-routing-probe — prove which rungs actually serve

## Gate

**Cleared 9 Sep 2026 (board-audit).** U2 is done: `GROQ_DEFAULT_MODEL` and
`GEMINI_DEFAULT_MODEL` are both present in `.env` (checked by key name
only, no value read), matching `docs/state.md`'s "Provider ladder" row and
`USER-TASKS.md`'s U2 entry ("DONE 9 Sep 2026"). `CEREBRAS_DEFAULT_MODEL`
and `NVIDIA_DEFAULT_MODEL` remain absent, which is **not** a gap: Q6
deliberately leaves Cerebras blank so its rung is skipped rather than
402ing, and NIM has no routing role at all (geo-blocked, CLAUDE.md #3).
`CLAUDE_API_DEFAULT_MODEL` is also absent and not required for this probe
— `claude_api` is not one of the four rungs `routing-pattern` currently
puts traffic through.

**Before this session's earlier check (1 Sep 2026), values were given but
not present.** Ali said "pasted" and supplied the five lines, but a
key-name check of the repo-root `.env` that day found none of the five
keys present. Superseded by the 9 Sep check above.

When it does land, three values differ
from what `state.md` researched on 28 Aug, so this probe is now the only
thing that establishes whether they serve:

- `GROQ_DEFAULT_MODEL=openai/gpt-oss-120b` (researched value was the 20b)
- `GEMINI_DEFAULT_MODEL=gemini-3.6-flash` (researched value was 2.5-flash)
- `CEREBRAS_DEFAULT_MODEL=` blank on purpose — expect the rung to be
  skipped with `cerebras: no model configured`, not to 402

Report those three by name in the result, and update `state.md`'s model-ID
table to Ali's values rather than the researched ones.

## Goal

`state.md`'s Groq/Gemini "working" claims are unverified under current
config, `tests/live/` has zero routing coverage, and DeepSeek's credit
top-up was never independently confirmed. One live test per rung settles
all of it.

## Steps

1. `tests/live/test_routing.py` (`-m live`): for each configured rung —
   Groq, Gemini, OpenRouter, DeepSeek (and Cerebras/Mistral only to
   assert their *expected* failure mode, until Q6/U9 change it) — one
   minimal completion through the real `route()` path, asserting reply
   non-empty and recording which provider served and what rate-limit
   headers came back. Never hardcode limits; read headers.
2. Keep each call tiny (a few tokens out). Claim `provider-account`.
3. Update `state.md`'s Provider rungs table from the results — evidence,
   dated, replacing the "unverified" caveats.

## Verification

`.venv\Scripts\python.exe -m pytest -q -m live tests/live/test_routing.py`
output cited per rung.

## Done when

Every rung's row in state.md says verified-working or fails-as-expected
with today's date and the probe on disk to re-run any time.

## Log

_(empty)_
