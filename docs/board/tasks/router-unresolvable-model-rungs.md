---
id: router-unresolvable-model-rungs
status: ready
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
