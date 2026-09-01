---
id: router-denial-surfacing
status: ready
lane: AUTO
priority: 2
phase: 0
blocked-on: none
files: router/routing.py (hot), tests/router/test_routing.py (area-hot), docs/state.md
resources: none offline
---

# router-denial-surfacing — 401/402/403 must surface, not just cool down

## Goal

`docs/blueprint.md` §3.3 (Ali's own text, applied 2 Sep 2026): "A rung that
returns 401/402/403 enters cooldown and **surfaces the denial**. It does not
silently fall through to paid work."

`router-cooldown-ledger` shipped 2 Sep with only the cooldown half. Today:

- **402** cools the provider down and then `continue`s down the ladder
  (`router/routing.py`, the 429/402/5xx branch). A payment-required rung is
  therefore indistinguishable from a busy one, and the request quietly moves
  on — possibly to a paid rung, which is the exact thing the clause forbids.
- **401/403** re-raise, but the cooldown is a **Mistral-only carve-out** by
  name. Any other provider's auth denial cools down nothing, so every
  subsequent job re-probes a key that cannot work.

## Steps

1. Generalise the 401/403 carve-out from `provider.name == "mistral"` to
   every provider. The comment explaining why a denial is not a malformed
   request already applies to all of them.
2. Decide what "surfaces" means concretely, and write it down. The ledger
   entry already carries `last_status`, so the cheapest honest answer is that
   `/status`'s provider health shows it (it does, since 2 Sep) **plus** the
   cascade not silently absorbing it. Say which of those Ali's sentence
   demands before changing control flow — if a 402 must abort the cascade,
   that changes reply behaviour on a live rung failure, and that belongs in
   the Log rather than being discovered later.
3. Tests: a 402 does not silently reach a paid rung; a 401 from any provider
   cools it down; the existing Mistral test still passes.

## Done when

Every 401/402/403 both cools the rung down and is visible without reading
logs; the suite is green; `docs/state.md`'s router rows say what changed.
