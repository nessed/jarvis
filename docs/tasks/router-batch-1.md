# Lane: router-batch-1

## Ownership

Own only `router/routing.py` and `tests/router/test_routing.py`. Claimed under
work-board claim `router-batch-1` (files: `router/routing.py`,
`tests/router/test_routing.py`) — already held by the orchestrator; do not
re-claim or release it, that happens after your report is reviewed. Do not
touch any other file. Do not edit `requirements.txt` — if a new dependency is
genuinely needed, append it to `docs/tasks/deps-router-batch-1.txt` instead.
Do not commit.

## Context

`router/routing.py` is JARVIS's provider-routing core: `ProviderRouter.route()`
walks a priority-ordered candidate list of LLM providers and falls through on
429/5xx. Fix three bugs, in this exact order, each with a regression test in
`tests/router/test_routing.py`:

### 1. `router-deepseek-weekday-gate` (do this first)

`_deepseek_allowed` (around line 283) only checks the UTC hour against
`PEAK_DEEPSEEK_WINDOWS_UTC`, never the weekday. DeepSeek is refused during
those hours every single day, including Saturday and Sunday — its cheapest
days, when the peak-avoidance restriction shouldn't even apply. Confirm with
DeepSeek's actual off-peak pricing calendar (weekday vs weekend UTC pricing)
before hard-coding a weekday check — if weekend pricing is flat cheap all day,
the fix is "skip the peak-window check entirely on Saturday/Sunday UTC"; if
weekend pricing has its own peak windows, gate on those instead. Do not guess;
check the provider's current published pricing schedule.

### 2. `router-402-aborts-chain` (small)

In `route()` (around line 212-238), the `except Exception as exc:` block only
records a cooldown and continues the fallback loop for `status == 429` or
`500 <= status <= 599`. Any other status (e.g. a Cerebras 402 — no free tier)
falls through to the bare `raise` at the bottom, propagating out of `route()`
and killing the entire fallback cascade for that call. Worse: because no
cooldown is recorded, the same 402 will be hit again on the very next call, at
the very same priority position, forever silently aborting every downstream
provider (Groq → Cerebras → OpenRouter → DeepSeek) whenever Cerebras is
reached. Record a cooldown for 402 (and any other definitively
"this key/plan cannot serve this rung" status you can identify — check what
other providers can plausibly return) and continue the fallback loop instead
of raising, mirroring the existing 429/5xx handling. Do not swallow genuine
auth/malformed-request errors (401/403/400 for providers other than the
existing Mistral special case) — those should keep propagating, per the
function's existing docstring contract ("Only a 429 or server error falls
through").

### 3. `router-model-env-validation` (small)

`_configured()` (line 241) checks only `endpoint`, `key_env`, and that the key
env var is set — it never checks whether `provider.model_env` (when present)
resolves to an actual configured model. A provider whose `model_env` is unset
in `.env` still passes `_configured()`, enters the candidate list, and only
fails inside `route()`'s `_model_for()` call, which returns `None`, which then
just appends `"{name}: no model configured"` to `failures` and moves to the
next candidate — no cooldown recorded, no visibility unless every candidate
exhausts. Make `_configured()` also check that a `model_env`-requiring
provider actually has that variable set (providers using `default_model` or
`discover_chat_model` need no such check). This keeps a misconfigured rung out
of the candidate list entirely instead of silently no-op'ing through it at
request time.

## Verification

Run, and cite full output in your report:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-router tests/router/test_routing.py
```

Then the full offline suite (still required before your report is considered
complete, even though you won't commit):

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-router --ignore=tests/db/test_jobs_integration.py
```

## Report

For each of the three fixes: what was wrong, the fix, and the test that
proves it. Name any provider-pricing source you used for item 1. Name
anything you found that changes the picture (e.g. if DeepSeek weekend pricing
turns out not to need a change at all — report that as a finding, don't force
a fix that isn't needed).
