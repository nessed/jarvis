---
id: router-eligibility-window
status: blocked
lane: AUTO
priority: 3
phase: 0
blocked-on: Q11
files: router/routing.py (hot), tests/router/test_routing.py (area-hot), docs/state.md
resources: none offline
---

# router-eligibility-window — "verified 200 within the window"

## Gate

**Q11, unanswered.** Ali's §3.3 says a rung is eligible only with "a
configured key AND a verified 200 within the current verification window.
Configured-but-unverified is not eligible." The window has no duration and
nothing measures one.

Two numbers are needed, both recommended in `QUESTIONS.md` Q11:

- **How long is the window?** Recommended 24h, refreshed by any 200 the
  router already sees in normal traffic.
- **What happens at cold start**, when nothing has a fresh 200? Recommended
  eligible-but-last within its cost class, because a strict reading empties
  the chain entirely and JARVIS answers nothing until a probe runs.

Do not pick these. They change what happens after every reboot.

## Goal

Track `last_verified` per provider and gate eligibility on it, per whatever
Q11 answers.

## Steps

1. Record `last_verified` on every 200. The process-lifetime ledger
   (`router.shared_router()`, built 2 Sep) is where provider state already
   lives, and `router/health_report.py` already carries a snapshot across
   processes — extend those rather than adding a third store.
2. Gate `ordered_providers` on the window, honouring Q11's cold-start rule.
3. `live-routing-probe` becomes the cold-start refresher; it is blocked on U2
   today.
4. Tests: a rung with a stale verification drops out; a fresh 200 restores
   it; cold start behaves exactly as Q11 says and not as anyone's judgement.

## Done when

Eligibility honours the window, cold start matches Q11's answer, and the
suite is green.
