---
id: router-cooldown-ledger
status: ready
lane: AUTO
priority: 2
phase: 0
blocked-on: none
files: router/routing.py (hot), tests/router/test_routing.py (area-hot), executor/handlers/whatsapp.py (hot), executor/poller.py (hot), bus/status.py, bus/main.py (hot), docs/state.md
resources: none offline
---

# router-cooldown-ledger — a ledger that outlives one call

## Gate

**Answered 1 Sep 2026 — Q10c = yes.** Process-lifetime scope, executor
(not bus) reports provider health. Build as specified.

Q10c: Ali blesses process-lifetime scope with the executor reporting
provider health. This is the one router job that was Class C — the
blueprint underspecified the ledger's lifetime.

## Goal

Today `route()` builds a fresh `ProviderRouter` per call, so a 429'd
provider is retried on the very next message and `/status`'s provider
health reports a router that has never routed. Make the ledger
process-lifetime and make provider health real.

## Steps

1. One long-lived `ProviderRouter` per process (module-level factory with
   injection for tests; stop re-reading `providers.yaml` per call).
2. Cooldown state survives across calls; expiry honors `retry-after` /
   header data where present.
3. Provider health flows from the process that routes — the executor.
   Smallest honest mechanism for `/status` (e.g. executor writes a small
   health snapshot the status reader includes, like `retry_health` does)
   — design within existing patterns; a new external service is out of
   scope.
4. This file's touch-list is nearly all hot files — claim them all, run
   as a solo lane, name every test double touched (four router jobs'
   worth live in `tests/router/test_routing.py`).
5. Tests: cooldown persists across two `route()` calls; expiry; /status
   shows non-empty health after a routed failure (fakes).

## Done when

Suite green; a live two-message check shows the second request skipping a
cooled-down rung (cite logs); state.md router row updated.

## Log

_(empty)_
