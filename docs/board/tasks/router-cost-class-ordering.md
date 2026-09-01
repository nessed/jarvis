---
id: router-cost-class-ordering
status: ready
lane: AUTO
priority: 3
phase: 0
blocked-on: none
files: router/providers.yaml, router/routing.py (hot), tests/router/test_routing.py (area-hot), docs/state.md
resources: none offline
---

# router-cost-class-ordering — order by cost class, then measured p50

## Goal

Blueprint §3.3, Ali's text: "Rungs are ordered by cost class first
(free-tier, then trial/credit, then paid), and within a class by measured p50
latency for the task profile." And: "`route(task_profile)` reorders **within
a cost class only**. It never promotes a paid rung above a free one that is
eligible; urgency does that, explicitly and per-job."

Today `providers.yaml` has a static integer `priority` and nothing else.
There is no `cost_class` field and no latency measurement anywhere — grepped
1 Sep 2026 and again 2 Sep, zero hits.

The gap is not academic: Cerebras stopped being free in mid-2026 and is now a
$5 trial credit (`blueprint-corrections`, 2 Sep), so "free" and "trial" are
already two different things inside the current roster, and a static priority
integer cannot express that.

## Steps

1. Add `cost_class` to `router/providers.yaml` for every provider —
   `free` / `trial` / `paid`. This is a data edit; get the classification
   right against `docs/blueprint.md`'s provider section **as corrected on
   2 Sep**, not against memory.
2. Make ordering cost-class-major, existing priority minor, before any
   latency work. That alone satisfies the "never promotes a paid rung"
   clause and is independently testable.
3. Measure p50 per (provider, task_profile). The router already sees every
   response; where the measurement lives — process-lifetime beside the
   cooldown ledger, or persisted — is a design decision to make explicitly.
   The ledger's own scope was a Class C question (Q10c), so do not assume.
4. Urgency stays the only thing that crosses a class boundary, per-job.

## Done when

Ordering is cost-class-major with p50 within a class, a paid rung can never
outrank an eligible free one except on an explicitly urgent job, and the
suite is green.
