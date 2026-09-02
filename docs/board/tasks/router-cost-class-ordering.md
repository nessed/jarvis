---
id: router-cost-class-ordering
status: done
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

## Log

### 2 September 2026 — done. All four steps.

### Step 1: `cost_class` in the manifest

Classified against `docs/blueprint.md` **as corrected 2 Sep 2026** (Q10a), not
from memory:

```
groq         free      cerebras   trial     nvidia_nim  free
gemini       free      openrouter free      mistral     free
deepseek     paid      claude_max paid      claude_api  paid
```

`cerebras` is the whole reason the field exists. Blueprint line 46: "The open
free tier is gone ... a one-time **$5 trial credit** ... Treat Cerebras as
**trial/credit cost class, not free**, which is exactly the distinction the
routing pattern above orders by."

The three `paid` rungs keep the blueprint's own ladder order among themselves
(DeepSeek Flash → Claude Max → Claude API) through the existing priority
integer, so no information was lost by collapsing them into one class.

A missing or unrecognised `cost_class` loads as **`paid`**. A manifest typo
should cost a rung its tier, not cost money — and it must never stop the
router from starting, so it is a default rather than an error.

### Step 2: ordering, and the defect underneath it

Cost class major, profile preference minor — and the second had to move
*inside* the first.

The old code partitioned the **whole eligible list** into `preferred + others`.
That is a promotion across cost classes: a paid rung declaring the task
profile sorted above a free rung that did not. Adding `cost_class` and sorting
by it would have left that intact, because the partition ran afterwards.
§3.3's "`route(task_profile)` reorders **within a cost class only**" is
structural, and it is now structural in the code: the loop is per class, and
nothing inside it can move a rung between tiers.

### Step 3: p50, and where it lives

`docs/consults/2026-09-02-router-p50-storage-scope/` — the task says the ledger's
own scope was Class C (Q10c) so do not assume. **Verdict: this one is Class B,
mine, and the answer is process-lifetime.** Confidence high.

Q10c was about whether the router may believe a fact across restarts, and
Ali's recorded reasoning — "a file would tell a fresh process to keep avoiding
a provider that recovered hours ago" — is about preferring forgetting to stale
belief. A persisted latency baseline reintroduces exactly that, and correcting
for it needs a decay window nobody has specified. **Inventing that window
would be inventing policy**, which is the Class C move; shipping in-memory
pre-empts nothing and leaves persistence open as a later question with real
variance behind it.

Piggybacking on `router/health_report.py` was rejected on evidence: that
document is age-bounded at 600s and `read()` returns `None` wholesale past it,
which is right for a countdown and wrong for a baseline — a p50 field there
would silently vanish with it.

The verdict's flip-condition was checked: it would become Ali's if the routing
process were short-lived enough never to reach 5 samples. It is not.
`whatsapp-worker` is a long-running poll loop — `tools/whatsapp-worker.out.log`
is 1570 lines of continuous polling — and `shared_router()` is built once per
process.

What shipped:

- A bounded `deque(maxlen=20)` per **(provider, task_profile)**, so "for the
  task profile" is literal and the window is recent by construction rather
  than by a decay constant.
- **5 samples before a median may reorder anything.** A p50 over one call is
  just the last call. Below the floor a rung keeps its manifest priority,
  which is a defensible order rather than a guess.
- **Successful calls only.** A 429 measures how fast a provider says no and a
  5xx how fast it falls over; folding either in would make the rung that
  rejects fastest look like the rung that serves fastest.
- A measured rung outranks an unmeasured one in the same class — it has
  earned its place, where a priority integer is a number someone typed once.

### Step 4: urgency

Unchanged and still the only thing that crosses a class boundary, per job:
`emergency` in `ordered_providers`, and `router-denial-surfacing`'s paid-bar
carve-out. The p50 sort runs strictly inside a class, so it cannot cross one
by construction — there is a test that drives a 30s free rung against a 0.01s
paid one and asserts the free one still leads.

### Verification

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-lane-1
1346 passed, 9 deselected, 10 warnings in 68.29s
```

Fourteen tests added. Against the real manifest and the real `.env`:

```
live latency order: ['openrouter', 'mistral', 'deepseek']
live batch   order: ['openrouter', 'mistral', 'deepseek']
```

Free rungs first, paid last. The three missing free rungs are U2, not this.
