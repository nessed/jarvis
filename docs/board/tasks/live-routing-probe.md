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

**Answered 1 Sep 2026 — values given, but U2 is NOT done. Still blocked.**
Ali said "pasted" and supplied the five lines, but a key-name check of the
repo-root `.env` on 1 Sep found **none of the five keys present** (file
exists, 1271 bytes; names checked, no values read):

```
GROQ_DEFAULT_MODEL         present=False
CEREBRAS_DEFAULT_MODEL     present=False
NVIDIA_DEFAULT_MODEL       present=False
GEMINI_DEFAULT_MODEL       present=False
CLAUDE_API_DEFAULT_MODEL   present=False
```

Re-check that before starting. Running the probe now would only re-prove
the known gap, which is exactly what this gate exists to prevent.

When it does land, three values differ
from what `state.md` researched on 28 Aug, so this probe is now the only
thing that establishes whether they serve:

- `GROQ_DEFAULT_MODEL=openai/gpt-oss-120b` (researched value was the 20b)
- `GEMINI_DEFAULT_MODEL=gemini-3.6-flash` (researched value was 2.5-flash)
- `CEREBRAS_DEFAULT_MODEL=` blank on purpose — expect the rung to be
  skipped with `cerebras: no model configured`, not to 402

Report those three by name in the result, and update `state.md`'s model-ID
table to Ali's values rather than the researched ones.

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
