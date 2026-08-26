# JARVIS work setup — objective overview

Baseline recorded 25 August 2026; outcomes appended 26 August 2026 (see §12).
Scope: this document describes **how work is performed on this repository** —
the actors, artifacts, control flow, human touchpoints, and measured
characteristics of the process. It does not describe the product architecture
(see `docs/blueprint.md`) or the current build state (see `docs/context.md`).

Sections 1–11 are the descriptive record as it stood on 25 August, and are
deliberately left unedited: they were the evidence input to a process review,
and rewriting them in place would destroy the before-state that makes the
after-state legible. **They are no longer an accurate description of the current
process.** §12 records what the review changed and what it did not. Read §12
first if you want the current picture; read §5, §6 and §7 as history.

The review's goal was to increase automation, increase decision quality, and
reduce the number of points where the process halts on the user.

---

## 1. What is being built (one paragraph, for context only)

A personal assistant ("JARVIS") built as a durable command bus: a FastAPI
webhook receives WhatsApp messages (Meta Graph API), enqueues them into a
Supabase Postgres job table, and a laptop-resident pull executor claims,
checkpoints, and completes jobs locally. An 8-rung provider router fans LLM
calls across free tiers before paid overflow. A local-first memory subsystem
(Ollama + `nomic-embed-text` + sqlite-vec + SQLite facts, wrapped by self-hosted
Mem0) provides `remember()` / `recall()`. Build order is Phase 0 (bus) → 1
(memory) → 2 (FL Studio automation) → 3 (voice) → 4 (VPS/laptop split) → 5
(vision fallback). Current position: Phase 1, incomplete.

---

## 2. Actors in the work system

Five distinct actors participate. Only three are named in the governance rules;
two exist in practice and are undocumented.

### 2.1 Terminal orchestrator (documented)

A CLI coding agent running in the repository working directory on Windows 11.
Holds full machine authority: `pip`/`git`/venv, file creation and movement
anywhere in the repo, PowerShell and shell execution, process inspection,
background process launch. Responsible for decomposing work into lanes,
authoring lane briefs, dispatching subagents, integrating their output,
updating `docs/context.md`, and committing. It is the only actor permitted to
commit and the only actor permitted to edit `requirements.txt`.

### 2.2 Subagents / lanes (documented)

Task-scoped agents dispatched by the orchestrator against a written brief. Each
is given **strict disjoint file ownership**. A lane that needs to touch another
lane's paths must report the need rather than edit. Subagents may not commit and
may not edit `requirements.txt` (they append to `docs/tasks/deps-<lane>.txt`
instead). Observed named lanes in a recent session: `mem0_implementation`,
`context_update`, `qwen_smoke_diagnosis`, `brief_revision`,
`llama_default_smoke`.

### 2.3 Browser agent (documented)

Drives web consoles: navigation, reading, form population up to the auth wall.
Explicitly forbidden from typing into password, 2FA, or card fields, and from
free-running on payment or billing pages. Used for provider key creation and
Meta dashboard configuration.

### 2.4 The user (documented)

Sole holder of phone, ears, card, 2FA codes, passwords, and taste. Per
`agents.md`, the user handles **only**: logins/2FA/captchas, card entry, final
Save/Confirm clicks on third-party dashboards, and sensory verification (e.g.
listening to TTS, checking FL Studio edits by ear). In practice the user's role
is materially larger — see §5 and §6.

### 2.5 Claude web (Opus 5, high effort) — **undocumented, human-relayed**

A second, more capable model consulted outside the repository. It is not wired
into any tool, script, or router rung. The user manually copies terminal output
into the Claude web UI, receives a higher-quality answer, and manually pastes
that answer back into the terminal session. The user is the transport layer.
This actor appears nowhere in `agents.md`, `docs/blueprint.md`, or
`docs/context.md`, but is a load-bearing part of how decisions actually get
made.

---

## 3. Governance artifacts

Four artifact classes carry the process. All are plain markdown in-repo.

| Artifact | Role | Authority |
|---|---|---|
| `agents.md` (3,906 B) | Build rules: parallelism, ownership, secrets, verification, stop-and-report | Binding process contract |
| `docs/blueprint.md` (~282 lines) | Technical spec: architecture, provider ladder, phase definitions, done-criteria | Binding for decisions; provider *claims* must be re-verified before use |
| `docs/context.md` (~208 lines) | Standing handoff ledger: current state, completed+verified list, blockers, acceptance evidence | Source of truth for build state; updated after every completed subtask |
| `docs/tasks/<lane>.md` (43 files, 7,584 words) | Per-lane self-contained brief, written **before** dispatch, designed to be a recovery path if context is lost | Binding for that lane's scope |
| `docs/tasks/deps-<lane>.txt` (5 files) | Dependency requests from subagents, integrated by orchestrator | Required audit trail for dependency changes |

Key rule distinctions encoded in `agents.md`:

- **Claims vs decisions.** Provider pricing, rate limits, model names, and free
  tiers are *claims* requiring current verification. Architecture, component
  choices, dependency selection, and phase ordering are *decisions* — an agent
  that believes a specified component is wrong must **stop and report, never
  substitute**.
- **Deviation-to-commit is failure.** "A deviation that reaches a commit is a
  failure whether or not the code passes tests."
- **No unverified completion claims.** "Every claim that something works must
  name the command or test that produced it and its output. A dispatched
  subagent returning no completion is failed verification, not a result."
- **Artifact retention.** Test data and artifacts may not be deleted before the
  outcome has been reported.

---

## 4. Control flow of a unit of work

Observed lifecycle, from the recent Mem0 wrapper and Qwen diagnosis sessions:

```
1.  User states an objective in natural language
2.  Orchestrator reads agents.md + blueprint.md + context.md + prior brief
3.  Orchestrator decomposes into lanes with disjoint file ownership
4.  Orchestrator writes docs/tasks/<lane>.md (recovery-capable brief)
5.  Orchestrator dispatches subagent(s)
6.  -- POLL LOOP --  "Waiting for agents" -> "Finished waiting" ->
                     "No agents completed yet"   (repeats; see 7.1)
7.  Subagent returns work; orchestrator inspects via git diff / file reads
8.  Orchestrator runs the focused verification command, captures exact output
9.  On blocker: STOP. Report to user. Do not implement an alternative.
10. User decides (often after relaying to Claude web -- see 5)
11. Orchestrator applies decision, re-verifies, updates docs/context.md
12. Orchestrator commits (subagents never commit)
```

Steps 9–10 are the halt points. Every one of them is a full human round trip.

### 4.1 Verification regime

Verification is command-and-output based, not self-attested. Observed pattern:
every completion claim in `docs/context.md` cites a literal invocation and its
literal result. Examples currently recorded:

- `.venv\Scripts\python.exe -m pytest -q tests/memory` → `38 passed in 8.50s`
- `.venv\Scripts\python.exe -m pytest -q --ignore=tests/db/test_jobs_integration.py` → `82 passed in 3.46s`
- Focused suites tracked per lane: memory 31→37→38→39, router 15, ingest 11, executor 9

Failures are recorded verbatim rather than omitted. The 25 August live Mem0
probe that timed out is written into `docs/context.md` with its exact command,
its exact captured output, and an explicit statement that it "makes no success
claim."

### 4.2 Two-tier test taxonomy

- **Focused / offline tests** — deterministic, injected seams, no network. These
  pass. 40 Python files, 4,463 lines total; roughly 1,802 lines of test code
  against 2,661 lines of production code (~0.68 ratio).
- **Live probes** — exercise real Ollama, real Supabase, real Meta, real
  providers. These are where every current failure lives. They are run manually,
  ad hoc, with hand-specified environment variables and hand-chosen timeouts,
  and are not part of any suite.

---

## 5. The manual escalation loop

The single most significant undocumented mechanism in the workflow.

```
Terminal agent produces output / hits a judgment call
        |  (user copies terminal text by hand)
        v
Claude web -- Opus 5, high effort
        |  (user copies answer by hand)
        v
Terminal agent receives pasted answer, acts
```

Observed properties:

- **Trigger is discretionary.** There is no rule, threshold, or heuristic
  governing when escalation happens. It occurs when the user judges the
  terminal's answer inadequate.
- **The user is the transport.** Latency is human-speed and the loop cannot run
  unattended.
- **Context is lossy in both directions.** Opus sees only what was pasted, not
  the repository state, the test output, or the lane brief. The terminal
  receives only Opus's final text, not its reasoning.
- **It is invisible to the record.** No `docs/context.md` entry, commit message,
  or lane brief attributes any decision to this path. The audit trail implies
  the terminal agent reached these conclusions itself.
- **The blueprint already specifies this escalation as an automated rung.**
  `docs/blueprint.md` routing rung 7 reads: "Claude Max (subscription) — the
  smart agentic executor, invoked as `claude -p` jobs, not as a router target,"
  and separately notes headless `claude -p` runs remain subscription-backed.
  The capability is specified; it is currently executed by hand.

### 5.1 Measured effect on interaction speed

In the recent transcript, after the user interrupted with a directive to drop
formal reporting style, the interaction pattern changed measurably. The
preceding agent-driven diagnosis consumed two sessions (25m15s and 13m15s) with
~13 empty poll cycles. The subsequent decision — extraction model selection —
closed in five short exchanges ("llama then obviously whats pros and cons" →
answer → "wb qwen" → "why does it fail" → "bet"). Formal status-report output is
optimized for audit trail production, not for time-to-decision.

---

## 6. Complete enumeration of human touchpoints

Documented in `agents.md`:

1. Logins, 2FA, captchas on third-party consoles
2. Card entry / payment
3. Final Save/Confirm clicks on third-party dashboards
4. Sensory verification (audio, FL Studio by ear)

Observed in practice but **not** documented:

5. **Decision arbitration on every stop-and-report.** The stop rule is
   correctness-preserving but has no autonomous resolution path — every stop
   waits on the user.
6. **Escalation relay to Claude web** (§5) — copy out, copy back.
7. **Model / dependency selection.** e.g. qwen3:4b vs llama3.1:8b was surfaced
   as an explicit user choice ("make Llama the default, or keep Qwen and accept
   timeouts").
8. **Correctness-of-memory review.** Blueprint 1.4 permanently assigns this:
   "The agent cannot judge whether a remembered fact about your life is right;
   that check is permanently yours."
9. **Corpus selection** (blueprint 1.2) — the privacy boundary, deliberately
   user-held.
10. **Interrupt-driven process correction** — e.g. the mid-session style
    directive that changed reporting behavior.
11. **Tunnel/webhook re-pointing** after each Quick Tunnel restart (§7.5).

Items 8 and 9 are deliberate, principled human retention. Items 5, 6, 7, and 11
are not principled — they are unautomated mechanism.

---

## 7. Measured characteristics

### 7.1 Empty polling

In the reviewed transcript, the sequence
`Waiting for agents → Finished waiting → No agents completed yet` appears
**~13 times**, each returning zero new information. The orchestrator's check-in
cadence is not matched to subagent completion time. This is the largest
observable source of wasted orchestrator turns.

### 7.2 Session and commit cadence

- 12 commits spanning 2026-08-23 14:29 → 2026-08-25 02:14.
- One ~24.5 hour gap between commit 1 (`bc7fb27` skeleton) and commit 2
  (`699c92d` Phase 0 bus foundation).
- Remainder is bursty: 10 commits inside a ~35-hour window, intervals from 3
  minutes to 2h28m.
- Work concentrates in a small number of long sessions. Each session start
  re-pays a full context-reload cost — reading `agents.md`, `blueprint.md`,
  `context.md`, and the active brief. This reload cost is the reason
  `docs/context.md` is written at its current density; it is substituting for
  session continuity.

### 7.3 Lane brief distribution

43 briefs, 7,584 words, mean ~176 words. Distribution is highly skewed:

- `mem0_wrapper.md` — 1,007 words (2.4× the next largest)
- `browser-log.md` — 417
- Median brief — ~133 words

Brief length correlates with prior failure. The largest brief exists because its
task was stopped once for authorization and needed a full recovery rewrite.

### 7.4 Recovery and reconciliation share

Of 43 briefs, at least 7 are recovery-named rather than progress-named:
`stop1.md`, `stop2.md`, `tunnel_recovery.md`, `status_recovery.md`,
`browser-log.md`, `context_reconciliation.md`, `next_work_scan.md` — ~16% of
lane volume spent re-establishing state rather than advancing the blueprint.

### 7.5 Structural sources of recurring toil

- **Cloudflare Quick Tunnel.** Ephemeral by design; URL dies on any cloudflared
  or laptop restart, requiring manual Meta callback re-point each time. Already
  caused one `Recover tunnel handoff` commit and one `tunnel_recovery.md` lane.
  `tools/cloudflared.log` is 1.7 MB. A named tunnel would eliminate this class
  of work now; the blueprint defers the fix to Phase 4.
- **Meta dashboard browser automation.** Reproducible browser-side rendering
  failure — after a clean retry, Meta returned "only Meta's 832-character
  application shell after nine seconds" with no callback/verify fields exposed.
  Retried across multiple sessions without success and without escalation to a
  manual hand-off.
- **Windows environment friction.** `Get-CimInstance` returned `Access denied`
  during process inspection; file deletion blocked by a still-running probe
  holding SQLite handles, requiring a stop-then-delete sequence; system Python
  lacks pytest so `.venv\Scripts\python.exe` must be used explicitly; CRLF/LF
  warnings on every `git diff`.

### 7.6 Process-compliance gaps

- **Missing `deps-mem0_wrapper.txt`.** Five `deps-<lane>.txt` files exist
  (`db`, `router`, `security`, `memory_embeddings`, `memory_ingest`). The
  in-flight mem0 lane has none, yet `requirements.txt` carries uncommitted
  additions (`mem0ai==2.0.19`, `ollama==0.6.2`). The audit trail that exists for
  every prior dependency change is absent here.
- **Live-probe verification lags focused-test verification.** Focused suites are
  green (39 passed) while the behavior the phase is defined by — a real
  `remember()` / `recall()` round trip — has never completed successfully. Unit
  green + live red is a state the current process can carry for multiple
  sessions without flagging it as blocking.

---

## 8. Worked example — the Qwen extraction failure

The clearest end-to-end sample of the system operating, including both its
strengths and its costs.

| Step | What happened | Cost |
|---|---|---|
| 1 | Mem0 wrapper implemented, focused tests pass (38) | 25m15s session |
| 2 | Required live smoke probe stalls >30s; recorded verbatim as failed, no success claimed | — |
| 3 | User asks "what then"; agent proposes diagnosis; user says "yes" | 1 round trip |
| 4 | Agent bisects layers: raw Ollama → Mem0 adapter → wrapper | ~13 poll cycles |
| 5 | Root cause isolated **before** any code change: raw qwen3:4b times out at 20s; raw llama3.1:8b returns in ~17s. Not a wrapper bug | 13m15s session |
| 6 | Real defect found and fixed: no local extraction timeout existed, so failures hung instead of failing cleanly | — |
| 7 | Agent explicitly refuses to switch models unilaterally: "I did not switch models behind your back" | STOP → user |
| 8 | User decides Llama; asks pros/cons; asks why Qwen fails | 5 exchanges |
| 9 | Cause explained: earlier 10/10 JSON test used a short prompt capped at 32 output tokens; real Mem0 extraction prompt is far larger | — |
| 10 | `DEFAULT_FACT_EXTRACTION_MODEL = "llama3.1:8b"` set; `OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS` default 30 added; tests 39 passed | — |

**What the process got right:** no fabricated success, root cause isolated
before code was touched, an unrelated real defect (missing timeout) surfaced by
the investigation, no silent model substitution, artifacts documented before
deletion.

**What it cost:** ~38 minutes of agent session time plus ~13 empty poll cycles,
and a hard stop on a decision ("bigger model that finishes vs smaller model that
hangs") that had one defensible answer given the evidence already in hand.

---

## 9. Current state snapshot (as of this document)

Working tree, uncommitted:

```
 M docs/blueprint.md          M memory/store.py
 M docs/context.md            M memory/types.py
 M memory/__init__.py         M memory/vector_index.py
 M memory/embeddings.py       M requirements.txt
 M memory/runtime.py          M tests/memory/test_runtime.py
                              M tests/memory/test_store.py
                              M tests/memory/test_vector_index.py
?? docs/tasks/mem0_wrapper.md
?? memory/mem0_wrapper.py
?? tests/memory/test_mem0_wrapper.py
```

- Focused memory suite: 39 passed. Offline integration: 82 passed.
- Live Mem0 `remember()`/`recall()` round trip: never completed successfully.
- `llama_default_smoke` lane dispatched, outcome not yet recorded.
- Diagnosis databases removed after documentation, per the retention rule.

Standing external blockers, all provider-side:

- Meta system-user access token returns OAuth error 190 — blocks all outbound
  Graph API sends. Inbound HMAC validation unaffected.
- Meta app is unpublished — dashboard test events work, production data will not
  be delivered.
- Cerebras authenticates but chat returns `402 payment_required` — unusable as a
  free rung.
- Mistral returns 403 on free Labs chat — rung present, cannot accept work.
- Quick Tunnel URL is ephemeral and must be re-registered with Meta on restart.

---

## 10. Invariants any future automation must preserve

Extracted from `agents.md` and `docs/blueprint.md`. Listed here so the follow-up
review can distinguish removable ceremony from load-bearing constraint.

**Non-negotiable (correctness / privacy / trust):**

1. No secret is ever printed, echoed, logged, committed, or requested. `.env` is
   gitignored; `.env.example` holds empty placeholders only.
2. No personal corpus is read or ingested without explicit user opt-in.
   `ingest/` stays empty by design.
3. Memory extraction and embeddings are loopback-only. Non-loopback URLs are
   hard-rejected. Unavailable local Ollama fails closed — no hosted fallback.
   Rationale: NVIDIA NIM is geo-blocked from Pakistan and Gemini's free tier may
   train on prompts, so neither may receive private content.
4. No silent model or dimension drift — the index refuses to open when stored
   vectors came from a different embedding model.
5. Completion claims must cite the command and its literal output. A subagent
   returning nothing is failed verification, not a result.
6. Specified components are decisions, not suggestions: stop and report rather
   than substitute.
7. Correctness of remembered personal facts is permanently the user's judgment.
8. The user personally handles passwords, 2FA, captchas, card entry, and final
   Save/Confirm on third-party dashboards.
9. Destructive operations (`rm -rf`, `DROP TABLE`, deleting cloud resources,
   writing to any original `.flp`, global git config) require explicit user
   approval; agents work on copies.

**Process mechanism (mutable — this is what the review targets):**

10. Poll cadence for dispatched subagents.
11. Escalation trigger, transport, and record-keeping for the
    higher-capability-model consult (§5).
12. Which stop-and-report events genuinely require the user versus which have a
    single defensible answer derivable from evidence already gathered.
13. Report verbosity and format.
14. Session context-reload cost and how `docs/context.md` amortizes it.
15. Whether live probes remain manual and ad hoc or become a runnable suite.
16. Phase ordering where a later phase's component (named tunnel, Phase 4)
    would remove recurring toil in the current phase.

---

## 11. Summary

The system is a written-contract, disjoint-lane, evidence-gated agent workflow
with a human decision arbiter and an undocumented manual escalation to a
higher-capability model. Its correctness properties are strong and observably
enforced: nothing in the record is fabricated, no specified component has been
silently substituted, and failures are retained verbatim.

Its throughput properties are weaker. Wall-clock time concentrates in three
places: empty poll cycles against dispatched subagents, full human round trips
at every stop-and-report, and hand-relayed escalation to a model that the
blueprint already specifies as an automatable routing rung. Two structural
choices — deferring the named tunnel to Phase 4, and running live probes
manually outside any suite — generate recurring work that the process then
spends ~16% of its lane volume recovering from.

---

## 12. What changed — 26 August 2026

Committed in `b89e203`. This section is the only current part of the document.

### 12.1 The finding that mattered most

**`agents.md` was never loaded into agent context.** There was no `CLAUDE.md` in
the repository, and nothing else imported the rules file. The "binding process
contract" in §3 bound only when an agent happened to open it — §4 step 2
("Orchestrator reads agents.md + blueprint.md + context.md") describes a habit,
not a mechanism. Every rule in this document's §3 and §10 was advisory by
accident for the whole build.

This is precisely the class of thing a document written by an agent operating
inside the system it describes will not notice: the agent *had* read the rules,
in the session that produced this file, so the rules appeared to be in force.

Fixed: `CLAUDE.md` now imports `agents.md` and is loaded automatically at every
session start, including for subagents. Verified by a clean headless session
instructed not to read files, which correctly named the three stop classes and
both new scripts from context alone.

### 12.2 Resolved — §10 mutable items

| Item | Was | Now |
|---|---|---|
| 11 — escalation transport (§5) | Human copies terminal output into Claude web, copies the answer back | `tools/consult.py` — headless `claude -p`, structured `{verdict, reasoning, confidence, what_would_change_this}`, exchange saved under `docs/consults/`. The record gap named in §5 closes: consults are cited when acted on. |
| 12 — which stops need the user | No rule; every stop waited on the user | Three named classes in `agents.md`. Class A: evidence obtainable — get it, do not ask. Class B: single defensible judgment — consult, act on the verdict. Class C: the user's alone. A Class B halt reaching the user without a consult first is a failed halt. |
| 15 — live probes manual | Hand-typed commands with hand-chosen env vars, outside any suite | `tests/live/` behind a `live` pytest marker; new `pytest.ini` defaults to `-m "not live"`. The 26 August Mem0 round trip is now `test_remember_then_recall_round_trip`. |
| 10 — poll cadence | ~13 consecutive no-information check-ins (§7.1) | Rule: never report with nothing new to say. Not mechanically enforced. |
| 13 — report verbosity | Formal status-report style; §5.1 measured it as optimized for audit trail, not time-to-decision | Existing terseness rule kept; empty-report rule added. |

### 12.3 Resolved — §6 unprincipled touchpoints

- **6 (escalation relay)** — removed; see above.
- **5 and 7 (stop arbitration, model/dependency selection)** — narrowed by the
  Class A/B/C taxonomy. The Qwen-vs-Llama decision in §8 step 7 is the archetype:
  it had one defensible answer given evidence already in hand, and would now
  resolve by consult rather than by a full human round trip.
- **11 (tunnel/webhook re-pointing)** — `tools/repoint_webhook.py` re-points
  Meta via `POST /{app-id}/subscriptions`, discovering the live tunnel URL from
  `tools/cloudflared*.log`, probing it before changing anything, and reading the
  subscription back to confirm. Verified with `--check` against live Meta. The
  POST path is unexercised — no tunnel was running when it was written.

The §7.5 Meta dashboard browser failure is retired rather than fixed: the Graph
API replaces the surface that was failing to render. `agents.md` now also
requires a second reproduction to end retrying — `docs/blockers/<slug>.md`
instead of another attempt.

### 12.4 A gap this document did not identify

§7.6 named the live-vs-focused verification lag. It did not name the sharper
version of the same problem: **a focused test run satisfies the citation rule
while the tree is red.**

At `8fb271f` the full offline suite was failing. `tests/test_integration.py`'s
`FakeJobs.enqueue` was still on the pre-`8fb271f` signature after the
queue-durability lane widened the `JobRepository` Protocol. The lane owned the
Protocol; the stranded test double lived in a file no lane owned. The citation
recorded in `docs/context.md` — `pytest -q tests\memory` → 45 passed — was true
and proved nothing about the tree.

This is a direct product of the disjoint-lane model in §3, not an accident of
one lane's carelessness. Two changes:

- `agents.md`: the full offline suite runs before any commit, and a lane
  changing a shared interface names every implementer including doubles in files
  it cannot edit.
- `.githooks/pre-commit` (with `core.hooksPath` set): refuses a commit while the
  suite is red. Verified by deliberately breaking a test — the commit was
  blocked and nothing landed. This is the only change in the set that is
  mechanically enforced rather than instruction-followed.

### 12.5 Not addressed

- **§7.2 context-reload cost / §7.3 brief distribution / §7.4 recovery share.**
  `docs/context.md` is still the amortization mechanism and still dense. The
  proposed split into a short `## Now` block plus dated evidence files was not
  done; a partial hand reconciliation on 26 August collapsed superseded
  diagnostic entries instead.
- **§7.5 Cloudflare Quick Tunnel.** `repoint_webhook.py` fixes the Meta side.
  Restarting `cloudflared` itself is still manual. The named tunnel remains
  deferred to Phase 4.
- **§7.6 missing `deps-mem0_wrapper.txt`.** Still missing.
- **§10 items 1–9.** Untouched by design — these are the load-bearing
  constraints, and the review's premise was that they must be satisfied without
  a human in the loop for every instance, not relaxed.
