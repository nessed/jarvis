# Parked — deliberately not being done

Read before proposing "obvious" work. Re-opening any of these requires Ali
saying so in words, not an agent's judgment. Dates are when the state was
set.

- **The FLP writing half** (`apply_rules()` against real projects, any
  producer for `flp_sort` on real files). No mixer-sorting convention
  exists; Ali closed the question unanswered (1 Sep 2026). The placeholder
  ruleset is unapproved. Inferring a convention from the 26-project audit
  or from `outroagain`'s layout is a Class C substitution and writes to his
  real projects — not recoverable. Reading `.flp` files stays fine.
- **`wakeword-train`** — not blocked, **not needed**. Pretrained
  `hey_jarvis_v0.1` passed 7/7 with wide margins (29 Aug 2026).
  `voice/record_wakeword.py` stays for the day a noisier room changes that.
- **Mem0 demotion / raw-turn duplication decision** (drift audit §3.2,
  `distill-starvation-floor`, `distilled-duplicate-recall-decision`) —
  Ali deferred it explicitly (29 Aug 2026): keep both paths exactly as
  they are; revisit when a "final version" of memory exists. Do not
  re-ask; do not build either side.
- **`router-deepseek-defer-not-skip`** — not buildable as scoped: nothing
  calls `route()` with `urgent=False`, so there is no batch-routed job to
  defer. Becomes real work only after a batch caller exists (likely via
  `action-worker`/`enqueue-classifier` era). Re-check then.
- **Meta app publishing** (open blocker 2) — dev mode with the allow-listed
  number serves the single-user product fine. Publishing is real work with
  review overhead and buys nothing until someone other than Ali messages
  it.
- **Rotate-Meta-verify-token tracking** — closed by Ali's instruction
  (1 Sep 2026), recorded as a decision, not as a verified rotation. The
  log leak itself is fixed at source.
- **Phase 5 entirely** (UI-TARS vision fallback) — optional by blueprint,
  last by design, gated on U10.
- **The ambient-circle UI** (blueprint §5) — the endgame target, not a
  current phase. Nothing on this board builds UI; the circle waits for
  Phases 3/4 to be solid underneath it, per the blueprint's own note.
