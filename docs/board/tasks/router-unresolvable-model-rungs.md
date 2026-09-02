---
id: router-unresolvable-model-rungs
status: done
lane: AUTO
priority: 2
phase: 0
blocked-on: none
files: router/routing.py (hot), tests/router/test_routing.py (area-hot), docs/state.md
resources: none offline
---

# router-unresolvable-model-rungs — two dead rungs at the front of every request

## Goal

`groq` (priority 1) and `cerebras` (priority 2) are eligible on every
request, sort to the front of the ladder, and are silently skipped inside
`route()`. Found 2 Sep 2026 by `router-cooldown-ledger`.

Both declare `default_model: "${GROQ_DEFAULT_MODEL}"` /
`"${CEREBRAS_DEFAULT_MODEL}"`, and `load_providers` resolves an unset
placeholder to `None`. `_configured()` does not catch it: its model guard
only fires for providers that declare `model_env`, and these declare
`default_model`. So they enter the candidate list, `_model_for()` returns
`None`, and `route()` appends `"<name>: no model configured"` to `failures`
and continues — a message surfaced **only if every provider fails**.

Evidence: six consecutive live `latency` calls all served by `openrouter`,
with `groq` first in `ordered_providers` every time and its ledger entry
still showing `last_status: None`.

## Why it is not just U2

U2 (the five model IDs reaching `.env`) makes these two rungs work again and
the symptom disappears. The *defect* does not: any future provider whose
`default_model` is an unresolved placeholder will be silently unroutable in
exactly the same way, at the front of the queue, with nothing surfacing it.

## Steps

1. Widen `_configured()` so a provider with no resolvable model is not
   eligible, whether that model would have come from `model_env` or from a
   `default_model` placeholder. The narrow version is a one-line change;
   check the `discover_chat_model` path is not caught by it — mistral
   resolves its model at request time and **is** routable
   (`codestral-2508`, live 2 Sep).
2. Decide with `provider-status-generator` whether the answer is only
   "ineligible" or also "reported as configured-but-not-routable, with a
   reason". Ali's §3.3 asks for the second; do not invent the report format
   here alone.
3. Tests: a provider with an unresolved `${...}` default_model never reaches
   the candidate list; one with `discover_chat_model` still does.

## Done when

Neither rung appears in `ordered_providers` while its model is unresolvable,
the reason is visible somewhere a human looks, and the suite is green.

## Log

### 2 September 2026 — done. Three dead rungs, not two.

### The fix

`_configured()` deferred to a model guard that only fired for providers
declaring `model_env`. `groq`, `cerebras` and `gemini` declare
`default_model: "${...}"` instead, and `load_providers` resolves an unset
placeholder to `None`, so all three entered the candidate list, sorted to the
front by priority, and were skipped inside `route()`.

The skip was recorded — appended to a `failures` list that is rendered **only
when every provider fails**. So the ladder working correctly was the exact
condition that kept it invisible.

`_can_resolve_model()` replaces that guard and checks the same three sources
`_model_for()` uses, in the same order, so the two cannot drift apart:

1. `model_env` present in the environment,
2. `discover_chat_model`, which resolves at request time,
3. a `default_model` that actually resolved.

`discover_chat_model` counting as resolvable is what keeps Mistral routable
with no `default_model` at all — live 2 Sep on `codestral-2508`, and the task
called that out specifically.

### Measured, not assumed

Against the real manifest and the real `.env`:

```
unroutable:
  groq           no model: its default_model placeholder is unset in .env
  cerebras       no model: its default_model placeholder is unset in .env
  nvidia_nim     no API key in NVIDIA_API_KEY
  gemini         no model: its default_model placeholder is unset in .env
  claude_max     not a router target
  claude_api     no endpoint configured

order for latency: ['openrouter', 'mistral', 'deepseek']
order for batch  : ['openrouter', 'mistral', 'deepseek']
```

**`gemini` is a third rung with the same defect**, which the task did not name
— it says "two dead rungs". U2 has been updated with the measured list, since
"the ladder collapses to openrouter/free" was previously an inference and is
now a printout.

### Step 2: what "the reason is visible" means, without inventing the report

The task is explicit that the report format belongs to
`provider-status-generator` and must not be invented here. So this task ships
the *input* and not the presentation:

- `unroutable_reasons()` returns `{provider: reason}`, naming the env var that
  would fix each one. Cooldowns are deliberately excluded — a cooling rung is
  routable and merely resting, and the ledger already reports it with its
  status and remaining seconds.
- One warning per provider per process, so the fact is not waiting on a task
  that has not landed yet. Once per process rather than per request: this runs
  on every message, and a warning per message is noise nobody reads.

`provider-status-generator` is the next `ready` task and can format this
without re-deriving it.

### Tests

Six added: an unresolved placeholder never becoming a candidate; the same
provider becoming one once it resolves; `discover_chat_model` still routable;
a set `model_env` sufficing without a default, and an unset one not; the
reasons naming the right env var per rung; and the warning firing once across
five requests rather than five times.

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-lane-1
1332 passed, 9 deselected, 10 warnings in 73.07s
```
