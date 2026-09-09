---
id: live-routing-probe
status: done
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

### 2026-09-09 — done (lane-1)

**Gate re-verified before starting** (see the Gate section above, updated
in the same pass by `board-audit`): U2 is genuinely done, checked by key
name only.

**`tests/live/test_routing.py`** (new, 6 tests). Each test builds its own
single-provider `ProviderRouter(providers=[...])` rather than going
through `shared_router()`, so a working `groq` cannot mask a broken
`gemini` by sorting first — the point is "does this rung work", not "which
rung does the full ladder pick today."

**All four "should serve" rungs served, real HTTP 200s:**

```
$ .venv/Scripts/python.exe -m pytest -q -m live tests/live/test_routing.py -s
groq: model='openai/gpt-oss-120b' status=200 reply='pong'
  rate-limit headers: {'x-ratelimit-limit-requests': '1000', 'x-ratelimit-limit-tokens': '8000', ...}
gemini: model='gemini-3.6-flash' status=200 reply='pong'
openrouter: model='openrouter/free' status=200 reply='pong'
deepseek: model='deepseek-v4-flash' status=200 reply='pong'
mistral: denied (NoEligibleProvider: ... HTTP 429), last_status=429
6 passed in 14.70s
```

Groq's rate-limit headers match the documented free-lane caps exactly
(`docs/state.md`'s Provider rungs prose: 30 RPM/1K RPD/8K TPM) — the
`-limit-requests: 1000` and `-limit-tokens: 8000` headers are the same
numbers read back from the provider itself, not just from a pricing page.

**Cerebras confirmed excluded for the right reason, not by accident.**
`unroutable_reasons()["cerebras"]` names a model-resolution reason;
asserted it is *not* "no API key" (which is present) — proves the blank
`CEREBRAS_DEFAULT_MODEL` (Q6) is what excludes it, matching the deliberate
design rather than a coincidental misconfiguration.

**Mistral denied — HTTP 429, not the previously-reported 403 (U9).** Ran
three times across this session's debugging; 429 every time. Reported as
uncertain in `state.md` rather than as "the failure mode changed": this
session made several calls to Mistral's API while debugging the test
itself, and a self-inflicted rate limit from repeated testing is at least
as likely an explanation as an account-side change. U9 stays open.

**Real bug found while writing the probe, not in the router itself.**
Groq's `openai/gpt-oss-120b` and DeepSeek's `deepseek-v4-flash` are both
reasoning models: with `max_tokens=5` or `20`, both returned
`finish_reason: "length"` and an **empty** `content` — the budget was
spent entirely on the `reasoning` field before either model reached its
actual answer. Looks exactly like a broken rung from the response shape
alone; only `finish_reason` gives it away. `max_tokens=300` was enough for
both to complete. `docs/state.md` names this explicitly so the next
person who writes a tiny-budget live probe against either model doesn't
lose the same twenty minutes.

**`docs/state.md` updated** with a new `live-routing-probe` row (all of
the above, dated) directly under the Provider ladder row it verifies.

**Full offline suite** (the live tests are `-m live`-marked and excluded
by default; confirms nothing broke and the new file is correctly
deselected):

```
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1
1679 passed, 16 deselected in 66.13s (0:01:06)
```

10 -> 16 deselected: the 6 new `-m live` tests, correctly excluded from
the default run.
