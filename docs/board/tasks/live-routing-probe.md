---
id: live-routing-probe
status: blocked
lane: AUTO
priority: 2
phase: 0
blocked-on: U2
files: tests/live/test_routing.py, docs/state.md
resources: provider-account (spends real allowance)
---

# live-routing-probe — prove which rungs actually serve

## Gate

U2 (the five `*_DEFAULT_MODEL` lines in `.env`). Before that, the probe
can only re-prove the known gap.

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
