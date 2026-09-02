---
id: router-denial-surfacing
status: done
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

## Log

### 2 September 2026 — done. The clause reads narrower than it looks, and that matters.

### Step 2 first, as the task asks: what "surfaces" demands

`docs/consults/2026-09-02-router-denial-surfacing-reading/` — **verdict B,
confidence high.** Three readings were put up:

- **A, literal-strict:** 401/402/403 aborts the cascade for every provider.
- **B, paid-boundary:** the denial cools down and the cascade continues, but
  may not cross into a rung that costs money without surfacing first.
- **C, surfacing-only:** no control-flow change; `/status` showing
  `last_status` is enough.

**B, because of the two qualifiers.** Ali wrote "It does not *silently* fall
through to *paid* work." Under A both words are dead — an unconditional
re-raise forbids every fall-through, silent or not, paid or not, and he would
have written "aborts the cascade". Under C the cascade demonstrably does reach
paid work, so only "silently" does any work. B is the only reading where both
qualifiers bind, and it is what the surrounding bullets are about: §3.3's
subject is cost discipline — cost class first, reorder within a class only,
paid never promoted above free except by explicit per-job urgency. This is the
third cost rule, not an error-propagation rule.

A denial that lands on Groq and gets served by Cerebras costs nothing and
breaks nothing. A denial that quietly ends up on DeepSeek is the whole thing
the section exists to prevent.

The verdict named one observation that would flip step 4, and it was checked
rather than assumed: nothing upstream catches `NoEligibleProvider` specially.
`executor/poller.py` catches bare `Exception`, and the only other references
are in the router itself and its own tests. So the new subclass changes no
retry or dead-letter behaviour.

### What changed

1. **The carve-out is gone** (Step 1). It was literally
   `provider.name == "mistral"`. Every other provider's auth denial cooled
   down nothing, so every subsequent job re-probed a key that could not work.
   The comment justifying it — a denial is not a malformed request — was never
   Mistral-specific.
2. **401/403 stopped aborting the cascade.** They now cool down and fall
   through like 429/402/5xx. This *gains* a live reply where one was lost
   before, which is the opposite of the risk the task flagged.
3. **The paid boundary.** A denial recorded during a request bars the cascade
   from crossing into a rung marked `paid_overflow` or `capped`. At that
   boundary it raises `ProviderDenied` naming the denying rung, and never
   attempts the paid one. Checked *before* the attempt, because after it the
   money is already spent.
4. **Exhaustion and denial are told apart.** All rungs failing with at least
   one denial raises `ProviderDenied`, not a generic `NoEligibleProvider`. A
   denial is something Ali can fix; a 429 is something he waits out.

Three deliberate limits, each with a reason:

- **The bar is per request, never sticky.** The cooldown ledger already
  handles repetition; a persistent bar would let one bad key disable paid
  overflow indefinitely. A test drives exactly that: deny, get
  `ProviderDenied`, then the next request reaches the paid rung because the
  denying rung is now merely in cooldown.
- **`emergency=True` may cross it.** §3.3's adjacent bullet says urgency
  promotes a paid rung "explicitly and per-job", and a flag the caller set is
  the opposite of silent.
- **401 and 402 keep one rule.** A bad key repeats forever and a spent plan
  might not, which is a real difference — but it belongs in cooldown
  *duration*, not in whether the cascade continues, and the blueprint names
  the three statuses as one set. Splitting a specified grouping is Ali's call,
  not a lane's.

### Behaviour change, stated rather than discovered later

**A 402 on a free rung no longer reaches `deepseek`.** That is the intended
regression and the only one. Narrow in practice: `deepseek` is peak-gated and
`claude_api` is `emergency_only`, so on a normal ladder the boundary is rarely
reached at all.

### Step 3: tests

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-lane-1 tests/router/
62 passed in 2.05s
```

Eight added: the paid boundary for each of 401/402/403; a 429 still falling
through to paid work, so the boundary has not widened into a general fallback
ban; the emergency crossing; denial-vs-exhaustion in both directions; the bar
lasting exactly one request; and a 401 from a non-Mistral provider cooling
down.

Two existing tests were rewritten rather than deleted, and both were asserting
the behaviour this task exists to change:

- `test_401_still_propagates_for_non_mistral_providers` asserted
  `cooldown_until == 0.0` — the exact bug Step 1 names.
- `test_mistral_workspace_denial_cools_down_without_paid_fallback` asserted a
  bare re-raise past a rung called `spare` that costs nothing.

Full suite:

```
1326 passed, 9 deselected, 10 warnings in 68.15s
```

### What is specified and not done

`/status` shows a denial as `last_status: 401`, which meets the Done-when
("visible without reading logs") but leaves the reader to know that 402 means
denial. A `denied: true` flag would say it in words. Not built: it changes
`/status`'s response shape, which is a contract other tasks touch, and the
task's own Step 2 accepts the ledger field as sufficient.
