# JARVIS lane rules (former work board)

**Superseded as a task source, 1 Sep 2026.** Tasks now live in
`docs/board/` — start at `docs/board/README.md`. Nothing below this file's
Rules section is current work: the job tables are a historical planning
snapshot (27 Aug 2026, `628b6ea`) kept for their reasoning; everything
still worth doing from them was carried onto the board, and everything
deliberately not being done is in `docs/board/PARKED.md`.

**What stays authoritative here:** the Rules — roles, exclusive resources,
verification/live-route resources, the hot files, and the cross-lane
test-double index. The board's tasks reference them; `board-audit` keeps
the test-double line numbers honest.

`context.md` is this week. `state.md` is now. `history/` is done.
`blueprint.md` is decisions. **`docs/board/` is next.**

## How to use this

1. Read **Rules** below. They override any task's own note.
2. Before acting on a board task, atomically claim its task file and every
   file and external resource it will change or consume. The claim tool is
   authoritative; this document never records live claim state.
3. Release the claim ID when verification is complete. If work is interrupted,
   it remains active until a later CLI operation finds it older than its stale
   timeout **and** its recorded process ID is no longer alive.

Use the tool from the repository root:

```
python tools/work_board_claim.py claim --role CORE --work-item ITEM --file PATH [--resource KEY]
python tools/work_board_claim.py list
python tools/work_board_claim.py release CLAIM_ID
```

`CORE` and `BUILD` are coordination labels, not path ownership. A successful
claim grants the holder temporary exclusive authority for the named paths and
resources; every existing directory is therefore covered by the same rule.
Never edit the claim registry directly.

**Liveness is real since 2 Sep 2026.** Every claim records the Claude
session that made it (`JARVIS_SESSION_ID`, exported by the SessionStart
hook), and the PreToolUse hook heartbeats that session on every tool call.
A claim is dropped when its session has been silent for 30 minutes, never
by age while the session is alive. A claim with no session id is a
pre-harness one and keeps the old 24h age rule. The same hook *enforces*
file claims: a write to a path a live peer holds is refused. Resource
claims are still convention, except `git-commit`, which the hook checks.

---

## Rules

### Roles

`CORE` and `BUILD` do not own directories. A successful atomic claim grants
temporary authority for every named file, artifact location, and exclusive
resource; that rule covers all current and future directories. CORE integrates
completed lanes and alone claims `git-commit`; BUILD does not commit. A lane
changing a shared interface names every implementer and test double in its
completion report.

- CORE does not own paths; it integrates lanes and is the only role that
  commits after it has claimed `git-commit`.

### Exclusive resources

**Canonical resource keys** — the claim tool only collides identical
strings, so spelling is load-bearing. Use exactly these: `git-commit`,
`pre-commit`, `test-workspace`, `provider-account`, `meta-webhook`,
`cloudflare-tunnel`, `ollama-embed` (tier one below), `ollama-extract`
(tier two below), `microphone-speakers`, `live-jobs-table`. A new
exclusive resource gets its key added here before first use.

Files are not the only thing two agents collide on. These are exclusive
regardless of file ownership. **None of the below is mechanically enforced by
`tools/work_board_claim.py`** — `--resource KEY` records a claim honestly, but
nothing stops a process that never calls it from using Ollama, the mic, or
provider capacity concurrently, the same convention-only gap
`executor/heartbeat.py`'s `--force` override already has. File collisions and
`git-commit` are enforced mechanically by `.claude/hooks/harness_guard.py`;
the other resource collisions still depend on every lane actually calling
`claim` first. Independently reviewed
2026-08-28 (`docs/tasks/review-work-board.md`): also worth knowing, the
tool's PID-liveness check on a claim is close to decorative in practice — the
recorded PID is the short-lived `claim` subprocess, which has already exited
by the time anyone checks it, so the real backstop preventing a crashed
lane's claim from blocking others is the 24h stale timeout, not the PID
check.

- **Ollama is one lane wide, in two tiers.**
  - *Embed, ~0.5s*: the live reply path, `cache-dimension-probe`, the identity
    and persistence probes. These may share a window with each other.
  - *Extract, 20–130s*: `live-probe-distill`, `live-probe-backfill`,
    `finish-1.3-backfill-run`, `1.4-review-loop`. **Each must be alone, with the
    executor stopped.** An unguarded backfill on 26 Aug held the model and left
    eight inbound messages unclaimed. `executor/heartbeat.py` refuses batch
    tools while the executor polls, but nothing stops two agents both passing
    `--force`.
  - If Ali may be messaging the bot, no tier-two job runs at all.
- **The live `jobs` table.** `live-schema-drift-guard` writes probe rows,
  `sweep-orphan-probe-row` mutates one, `migration-runner-and-ledger` changes
  the schema, and a running executor claims from it throughout. Serialize all
  live-queue work and never run it while the stack is up.
- **Provider capacity.** `router-live-rung-probe` and
  `verify-configured-model-ids` spend real allowance. Claim `provider-account`
  and obtain current response headers or account/catalog evidence before using
  capacity; no fixed quota, free-tier, or model-availability claim here is
  authoritative.
- **The machine itself.** `whisper-npu-build` is a from-source C++ build plus a
  multi-GB download. `wakeword-train` is a training run. Either alone makes the
  laptop unresponsive. Running `stt-benchmark` beside either produces a fake
  number — and that number is what Ali is asked to judge.
- **Physical I/O.** The microphone, the speakers, and keyboard focus cannot be
  shared. `voice-loop`, `stt-benchmark`, `uia-app-scripts`, `uitars-install`.
- **git.** One role commits. Two agents committing into one working tree lose
  work. Enforced: the guard hook refuses `git commit` from a session that
  has not claimed `git-commit`, and from anyone while a live peer holds it.

### Verification and live-route resources

- Each session has its own scratch directory, `.pytest-basetemp-$JARVIS_LANE`
  (the documented command and the pre-commit hook both use it). Two panes
  sharing one produced a fake flaky suite on 2 Sep 2026. `test-workspace`
  now only matters for a shell without `JARVIS_LANE` exported.
- Claim `pre-commit` when changing its hook or invoking a commit, because it
  regenerates context status and runs the full offline suite. CORE alone claims
  `git-commit` and commits.
- Claim `meta-webhook` before `repoint_webhook.py` or any callback/subscription
  change, and claim `cloudflare-tunnel` before restarting or replacing a tunnel.
  These affect the live inbound route; never run either beside a Meta live probe.
- **Never `git stash` to get an isolated before/after count.** This working
  tree is shared live by every concurrent lane; a stash pauses *all* of their
  uncommitted work at once, not just your own file claims, and a pop racing
  another lane's write is exactly the kind of collision the claim tool exists
  to prevent. Observed 2026-08-28: a lane stashed/popped to measure its own
  test-count delta while several other lanes had uncommitted work in the same
  tree. It happened to pop clean, verified after the fact — but "verified
  clean after" is not a substitute for never risking it. Measure a delta some
  other way (a `pytest --collect-only` count, or just report the file(s) you
  added and let CORE diff them at integration) instead.

### The hot files

Every collision this project has had landed on these. Only one job may write
any one of them at a time:

```
executor/handlers/whatsapp.py
executor/poller.py
bus/main.py
db/jobs.py
router/routing.py
bus/whatsapp_client.py    <- sixth; one method today, voice needs two more
```

Two more are hot within their own area:

```
memory/store.py           <- three memory jobs want it
memory/conversation.py    <- conversation-turn storage and its tests
tests/router/test_routing.py  <- four router jobs want it
```

`.env.example` is contended three ways — router vars, bus/executor vars, memory
vars. **One lane writes the whole file in one pass**; the other two hand it
their lines.

### Cross-lane test doubles

This is the scar. Widening a Protocol once stranded a double in a file no lane
owned and shipped a red tree behind a green focused run. `.githooks/pre-commit`
exists because of it.

- `db.jobs.JobRepository` — implementers: `db/jobs.py SupabaseJobsRepository`,
  `tests/db/test_jobs.py:27` (`InMemoryJobsRepository`),
  `tests/test_integration.py:11` (`FakeJobs`),
  `tests/executor/test_poller.py:33` (`FakeJobs`),
  `tests/executor/test_distill_handler.py:59` (`FakeQueue`).
  *Line numbers re-verified 1 Sep 2026; `test_poller.py` had drifted 30 → 33.
  Each now names the class, so the next reader can re-find it after it moves.*
- `executor/handlers/distill.py:112 ChainQueue` is a **second, deliberately
  narrower Protocol on the same object**, split apart to dodge exactly this.
  Treat both as one interface.
- `bus/status.py QueueStatusReader.from_repository` reaches into
  `repository._client`, so it breaks on repository internals while implementing
  neither Protocol.
- `TurnStore` / `FactExtractor` / `ConversationMemory` doubles live in
  `tests/executor/test_distill_handler.py:186` (`FakeTurns`), `:210`
  (`FakeExtractor`), and `tests/executor/test_whatsapp_handler.py:179`
  (`FakeFact`), `:186` (`FakeMemory`), `:208` (`FakeSeenStore`).
  *Re-verified 1 Sep 2026. The three `test_whatsapp_handler.py` pointers were
  all wrong — 117/375/398 landed on unrelated lines. This is the section that
  exists to stop a stranded double shipping a red tree, so it rotting is the
  failure mode it was written to prevent.*
- `Job` is a frozen dataclass **constructed positionally** in
  `tests/test_integration.py:18`. Adding a field anywhere but the end breaks it
  silently.

A lane that changes a shared interface names every implementer in its report,
including doubles in files it cannot edit. Naming is required; editing is not
permitted.

### Proposed sequencing — verify before relying on it

These dependencies were inferred from the snapshot and are planning prompts,
not enforced facts. Confirm them against the current implementation before
claiming either job:

- `router-deepseek-weekday-gate` **before** `router-deepseek-defer-not-skip` —
  the deferral computes the next off-peak boundary from the same constant and
  computes it wrongly on a weekend.
- `undistilled-turns-indexed-query` **before** `undistilled-backlog-metric` —
  without the index the metric recreates the full scan it exists to avoid.
- `backfill-checkpoint-identity-drift` **before** `finish-1.3-backfill-run` —
  changing the checkpoint key after a partial ingest throws away completed
  chunks.
- `mem0-version-conformance-test` **before** `lazy-mem0-import` — so the lazy
  change has something that fails when it breaks.
- `router-shared-cooldown-ledger` strictly first or strictly last among router
  jobs — every other one reads `self.health`.

---

## Candidate work — claim required

These jobs looked independent in the snapshot. They are not guaranteed to be
collision-free: inspect and atomically claim their current paths/resources
before starting. **This is the block to hand an idle orchestrator.**

### Tests for things that have none

| id | what | files |
|---|---|---|
| ~~`test-repoint-webhook`~~ | **Done** (`1672f8c`). The 64-char guard was correctly **not** added — the lane found no source confirms any Meta verify_token length limit, and this session independently web-searched and found none either (2026-08-28); "64" in this row was an unverified number, not a real constraint. Guessing one would have been fabricating a validation rule. | `tools/repoint_webhook.py`, `tests/tools/test_repoint_webhook.py` |
| ~~`test-context-status`~~ | **Done** (`1672f8c`). The bug that lane found and correctly left alone (`main()` calling `splice()` before branching on `--check`) is now **also done** (landed 2026-08-29): `--check` now short-circuits before `splice()`, so a missing-markers file reaches `check()`'s own dedicated message via a clean `return 1` instead of an uncaught `SystemExit`. `--write` is unaffected (still needs the spliced block, so it still raises the same way). | `tests/tools/test_context_status.py`, `tools/context_status.py` |
| ~~`test-distill-memory-cli`~~ | **Done** (landed 2026-08-29). 12 new tests mirroring `test_run_backfill.py`'s pattern. | `tests/tools/test_distill_memory.py` |
| ~~`test-start-jarvis-uncovered-paths`~~ | **Done** (landed 2026-08-29). 11 → 28 tests; all four named gaps covered against fakes. | `tests/tools/test_start_jarvis.py` |
| ~~`consult-untested-paths`~~ | **Done** (`1672f8c`). | `tests/tools/test_consult.py` |
| ~~`test-openai-chat-client`~~ | **Done** (`ae158b9`). Exercised through its real `__init__`/`AsyncOpenAI` import path, fake swapped in only at `with_raw_response`. | `tests/router/test_routing.py` |
| ~~`poller-invariant-tests`~~ | **Done** (`b9458fb`, folded into the poller batch that also fixed drain-without-sleep, reseed-in-loop, heartbeat-clear-on-exit, and flp-permanent-failure-no-retry). | `tests/executor/test_poller.py` |
| ~~`hooks-path-invariant-test`~~ | **Done** (`1672f8c`). | `tests/tools/test_precommit_hook.py` |
| ~~`bus-branch-test-gaps`~~ | **Done** (`c47d9b4`). Timeout + non-JSON-error-body tests added; `_default_jobs()` fallback (incl. loud-500-not-silent-drop) covered. | `tests/bus/test_whatsapp_client.py`, `tests/test_integration.py` |
| ~~`mem0-version-conformance-test`~~ | **Done** (`ae158b9`). Six private-API couplings asserted directly against the installed `mem0ai==2.0.19`. | `tests/memory/test_mem0_pinning.py` |

### Small corrections

| id | what | files |
|---|---|---|
| ~~`flp-stale-module-docstrings`~~ | **Done** (`ed08e62`). Rewritten to state current status: registered as `flp_sort`, works on `.venv311`/3.11.5, blocked only by the new channel-groups `IndexError`. | `executor/flp/sort.py`, `executor/flp/__init__.py` |
| ~~`status-dead-letter-key`~~ | **Done** (`e4f15a7`). `_QUEUE_STATUSES` now includes `dead_letter`; test updated. | `bus/status.py`, `tests/status/test_live_queue_status.py` |
| ~~`reframe-archived-consults`~~ | **Done** (`1cb18ed`). Both files wrapped in `frame_untrusted()`'s exact shape (imported the real function, not hand-typed). | `docs/consults/*/response.md` |
| ~~`injection-blocker-stale-status`~~ | **Done** (`1cb18ed`). Only the embedded "What was found and NOT fixed" sub-finding was stale (the system-role recall bug, fixed in `628b6ea`) — the file's top-level "OPEN. Not reproduced." status is a separate, still-unresolved incident (the fake plan-mode text, H4-H6) and was left alone. | `docs/blockers/tool-result-injection.md` |
| ~~`poller-dead-request-completion`~~ | **Done as scoped** (`c6565c0`): gained 2 tests pinning its actual current behavior, still zero live callers. "Wire it or delete it" was a false binary — its docstring ("give executor jobs the provider router's single async entry point") and signature (`urgent: bool = False`) show it's a deliberately-placed hook for a future *batch*-routed job kind, not dead code to remove. Nothing in the repo currently calls `route(..., urgent=False)` at all (checked 2026-08-28: `ProviderRouter` is only instantiated in `bus/main.py`; the only executor caller, `executor/handlers/whatsapp.py:227`, always passes `urgent=True`). Actually wiring it means inventing that caller, which is `router-deepseek-defer-not-skip`'s job, not this one's — see that entry below. | `executor/poller.py` (hot), `tests/executor/test_poller.py` |
| `verify-configured-model-ids` | **Evidence gathered** (`docs/state.md`'s Provider rungs section, 2026-08-28), fix not applied. Five providers (`GROQ_DEFAULT_MODEL`, `CEREBRAS_DEFAULT_MODEL`, `NVIDIA_DEFAULT_MODEL`, `GEMINI_DEFAULT_MODEL`, `CLAUDE_API_DEFAULT_MODEL`) are absent as *keys* in the live `.env` (checked names only, no values read). Current model IDs researched and cited in `docs/state.md`. Setting the actual values in `.env` is the user's, not an agent's — `.env` is hand-filled per `CLAUDE.md`. | `docs/state.md` |

### Greenfield — touches no existing file at all

~~`whisper-npu-build`~~ (done, `0391f3f`) · `stt-backends` ·
`stt-benchmark` · ~~`wakeword-train`~~ (not blocked — **not needed**, the
pretrained model passed 7/7; see `docs/state.md`) · `kokoro-tts` ·
`voice-loop` · `voice-acceptance` · `oracle-provision` · `vps-harden-deploy` ·
`vps-web-ui` · `cloud-routine-trigger` ·
`phase4-acceptance` · `uitars-install` · `facts-check-job`

`voice-runtime-deps`, `wakeword-recorder`, and the agent half of
`stt-benchmark` landed in `4f39697` (see `docs/tasks/voice-deps-and-tooling-
report.md`). `uia-tree-dump` and `powercfg-profile` are subsumed into the two
newly briefed lanes below, not separate work.

Several are file-safe but **run-exclusive** — see Rules. Several are blocked on
Ali — see below. `facts-check-job` is the blueprint's only defence against its
own rot and has produced nothing in four days.

**Briefed as of 29 Aug 2026. Read the brief before dispatching any of these —
some are already in flight and re-dispatching one collides head-on.**

| brief | covers | state |
|---|---|---|
| `docs/tasks/whisper-npu-build.md` | `whisper-npu-build` | ~~blocked on AC power~~ **DONE** (`0391f3f`). Whisper large-v3 on the XDNA NPU, 12.4x CPU encoder speed, independently re-verified by CORE. Report: `docs/tasks/whisper-npu-build-report.md` |
| `docs/tasks/laptop-system-control.md` | Power/wifi/bluetooth/display, scheduled tasks, printing, file ops, process-kill — CLI/API only, no UIA | ~~in flight~~ **DONE** (`0391f3f`). `executor/system_control/`, 77 tests, registered as job kind `system_control`. Report: `docs/tasks/laptop-system-control-report.md` |
| `docs/tasks/pywinauto-zoom-whatsapp.md` | Zoom's native-dialog join tail, WhatsApp Desktop send-as-personal-number — the real UIA targets from blueprint 2.4 | ~~in flight~~ **DONE** (`0391f3f`). `executor/app_automation/`, 45 tests, registered as `zoom_join_meeting` + `whatsapp_desktop_send_message`. Report: `docs/tasks/pywinauto-zoom-whatsapp-report.md` |

**All three landed. Do not re-dispatch any of them.** What is now true of all
three, and is the next real question for this area: they are registered in
`executor/poller.py`'s `DEFAULT_HANDLERS` but **nothing enqueues them**. The
tree has exactly two producers: `bus/main.py:112`
(`whatsapp_webhook`) and `executor/handlers/distill.py:469` (the
self-re-enqueuing distill chain), and neither emits these kinds. Giving them a producer is `enqueue-classifier`, which is
a Barrier and is Class C — see Decisions. `flp_sort` is in the same position.

~~`whisper-npu-build` may not start while `laptop-power-lag-live-capture` holds
a claim~~ — moot, the build is done. The reasoning is kept because it applies
to the next from-source build: a C++ build during a battery-transition power
capture poisons the capture, and that capture's numbers are what Ali is asked
to judge. This laptop also has a recorded `108 C` ACPI thermal event, so any
long build needs AC power. Check `work_board_claim.py list` first.

It does **not** collide with `voice-deps-and-tooling` on files: that lane owns
`voice/benchmark_stt.py`, this one owns `voice/whisper/local_backend.py`, and
the interface between them is coordinated by report, not by cross-lane editing.
Disjoint ownership working as designed is not a conflict.

---

## Available now — serialize on a named file

### `router/routing.py` — five jobs, fixed order

1. ~~`router-deepseek-weekday-gate`~~ *(trivial)* — **done** (`49719b9`). DeepSeek
   dropped weekend peak pricing 23 Aug 2026 (confirmed via Bloomberg); weekend
   UTC now skips the gate entirely rather than gating on a weekday check.
2. ~~`router-402-aborts-chain`~~ *(small)* — **done** (`49719b9`). 402 now cools
   down and falls through like 429/5xx instead of hitting the bare `raise`.
3. ~~`router-model-env-validation`~~ *(small)* — **done** (`49719b9`).
   `_configured()` now excludes a `model_env`-requiring provider with no
   fallback and no env var set, instead of letting it no-op through
   `_model_for()`.
4. `router-deepseek-defer-not-skip` *(large, cross-area)* — the gate skips the
   rung instead of deferring the job via `run_after`, which the queue already
   supports. Writes three hot files. Dispatch as its own lane.
   **Corrected 2026-08-28:** not yet buildable as scoped. `_deepseek_allowed`'s
   weekday/peak gate (`router/routing.py:296-305`) only fires when
   `urgent=False`, and nothing in the repo calls `route()`/`request_completion`
   with `urgent=False` today — the only executor caller,
   `executor/handlers/whatsapp.py:227`, always passes `urgent=True` (a live
   reply), and `executor/poller.py`'s `request_completion` (the intended hook
   for a batch caller — see `poller-dead-request-completion`) has zero
   callers. Deferring "the job" via `run_after` needs an actual batch-routed
   job kind to defer, which doesn't exist yet. Building one to make this job
   exercisable is scope invention, not the described fix — report and hold
   rather than substitute.
5. `router-shared-cooldown-ledger` *(large, cross-area, blocked)* — see
   Decisions.

### `executor/poller.py` — six jobs

~~`distill-chain-reseed-in-loop`~~, ~~`poller-drain-without-idle-sleep`~~ and
~~`heartbeat-clear-on-exit`~~ **all done, batched into one lane** (`b9458fb`).

- ~~`distill-chain-reseed-in-loop`~~ — fixed: `_seed_distill_chain()` now also
  runs once per idle cycle inside the loop, not just once before it.
- ~~`poller-drain-without-idle-sleep`~~ — fixed: the loop only sleeps when
  `poll_once` returned `None`; a non-idle result loops straight back in.
- ~~`heartbeat-clear-on-exit`~~ — fixed: new `heartbeat.clear()`, called only
  from the `KeyboardInterrupt` handler, stays fail-open on a crash.
- ~~`flp-permanent-failure-no-retry`~~ *(solo)* — **done**, same commit.
  `ReorderNotSupported`/`FileNotFoundError` now route straight to `fail()`
  instead of burning the retry/backoff budget.

### `memory/store.py` — three jobs

**All done** (`14629c0`).

1. ~~`undistilled-turns-indexed-query`~~ *(medium)* — an indexed `distilled`
   column (tri-state, mirrors `metadata["distilled"]`) plus a partial index
   replace the full-table JSON-decode-and-filter; the `limit=1` emptiness
   check is now a single indexed lookup.
2. ~~`mem0-search-overfetch`~~ *(small)* — `mem0_wrapper.py`'s search now calls
   `store.count()` (one `SELECT COUNT(*)`) instead of `list_facts()`.
3. ~~`sqlite-wal-and-busy-timeout`~~ *(small)* — `journal_mode=WAL` and
   `busy_timeout=5000` set on connection open.

### `.env.example` — one writer, three contributors

**Done** (`608dfd7`). All 18 variables added, each grep-confirmed against a
real reader; `SUPABASE_KEY` confirmed dead (only remaining reference is a test
asserting it is *not* used) and removed.

- bus/db: `SUPABASE_SECRET_KEY`, `SUPABASE_QUEUE_TIMEOUT_SECONDS`
- router: `GROQ_DEFAULT_MODEL`, `CEREBRAS_DEFAULT_MODEL`, `NVIDIA_DEFAULT_MODEL`,
  `GEMINI_DEFAULT_MODEL`, `MISTRAL_DEFAULT_MODEL`, `CLAUDE_API_BASE_URL`,
  `CLAUDE_API_DEFAULT_MODEL`, `OPENROUTER_BASE_URL`, `OPENROUTER_DEEPSEEK_MODEL`
- executor/memory: `JARVIS_MEMORY_WRITES`, `JARVIS_DISTILL`,
  `JARVIS_POLL_INTERVAL_SECONDS`, `JARVIS_EXECUTOR_HEARTBEAT`,
  `OLLAMA_EMBEDDING_TIMEOUT_SECONDS`, `OLLAMA_FACT_EXTRACTION_MODEL`,
  `OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS`

`OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS` is a **startup precondition**, not a
knob — set above the handler timeout and the executor refuses to start. Say so
in the comment.

### Other single-file contention

- `bus/main.py` — ~~`webhook-message-dedup`~~ **done** (landed 2026-08-29, see below).
  `status-provider-health-source`, `voice-command-ingress`, `enqueue-classifier`
  are Class C (see Decisions). `bus-offbox-packaging` is Phase 4, not started,
  gated behind `enqueue-classifier` — not buildable yet, don't invent scope for
  it. ~~`status-distill-chain-liveness`~~ done — see the `bus/status.py` row
  below for the full note; its one-line wire-in here is also done.

  `webhook-message-dedup`, done 2026-08-28: new `bus/webhook_dedup.py`
  (`SeenWebhookMessageStore`, sqlite, mirrors `SeenMessageStore`'s pattern
  exactly), wired into `receive_webhook`. Duplicate response:
  `{"accepted": True, "duplicate": True}`, no `job_id`. Env var
  `JARVIS_WEBHOOK_DEDUP_DB_PATH`, defaults to `webhook.seen-messages.db`
  (already covered by the existing `*.seen-messages.db` gitignore glob, no
  `.gitignore` edit needed). Did not touch `db/jobs.py`/`JobRepository`, no
  live schema change, no import from `executor.handlers.whatsapp` (would have
  been circular). 11 new tests. `docs/state.md`'s "Dedups by Meta's message
  id" line has since been corrected to say it dedups at both enqueue and send;
  that follow-up is done.
- `bus/status.py` — ~~`status-dead-letter-key`~~, ~~`status-count-queries`~~,
  ~~`status-distill-chain-liveness`~~ **all done** (landed 2026-08-29).
  `queue_depths()`/`retry_health()` now issue count-only PostgREST queries
  (`count="exact", head=True`) instead of fetching every row — verified
  against the actually-pinned `postgrest` 1.1.1 (via `supabase==2.18.1`),
  which has no GROUP-BY-shaped aggregate, so this is 5 + 2 count queries, not
  one. New `QueueStatusReader.distill_chain_health()`: 3 count queries
  scoped to `kind="distill_memory"`, returns `{"alive": bool,
  "dead_letter_count": int, "has_ever_run": bool}` — `has_ever_run`
  distinguishes never-seeded from died, both otherwise reporting
  `alive=False`. Wired into `status_payload`/`create_status_handler`
  additively, and a matching one-line `distill_chain_health` param + wiring
  was added to `bus/main.py`'s `create_app()` (done separately, after
  `webhook-message-dedup` landed on that same file, to avoid the collision
  the dispatch brief flagged). `tests/status/test_live_queue_status.py`'s
  fake client was rewritten to model real filter/count semantics instead of
  canned per-field responses; 4 → 9 tests.
- `executor/flp/sort.py` — `flp-real-mixer-convention` is **closed unanswered**
  (Ali, 1 Sep 2026). Nothing here is dispatchable: the writing half needs a
  convention that does not exist and may not be guessed. All ~~`flp-write-path-guard`~~, ~~`flp-diff-report-emission`~~,
  ~~`flp-stale-module-docstrings`~~ all done.

---

## Phase 2 — what is actually blocked and what is not

**Correction worth keeping:** Ali's `.flp` copies are **not** blocking all
Phase 2 work.

- ~~`flp-sort-real-flp-end-to-end`~~ **Done** (landed 2026-08-29).
  Downloaded PyFLP's own upstream fixture into `test_projects/FL 20.8.4.flp`
  (public, from `demberto/PyFLP`'s repo — see `docs/blockers/pyflp-python-312.md`
  for the same URL a prior lane already used). New
  `test_flp_sort_handler_runs_the_full_pipeline_against_a_real_flp` in
  `tests/flp/test_flp_real.py` runs `build_flp_sort_handler`'s **actual**
  backup → load → apply_rules → save → verify → diff-report pipeline against
  it (`safe_root` pointed at `tmp_path`, never touching the tree outside the
  test) — a real mixer insert (`"Master"`) renamed, saved, re-parsed from
  scratch to confirm the rename stuck, backup file confirmed present, diff
  report confirmed present and correct. This is the first proof on disk that
  `sort.py` itself (not just PyFLP) works end to end — every prior proof was
  either fakes/stubs or PyFLP's raw `parse`/`save` alone. Verified:
  `.venv311\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-flp -m realflp tests/flp/` →
  `4 passed`. Main suite unaffected (`480 passed, 5 deselected` — one more
  deselected than before, correctly, since the new test is `realflp`-marked).
- ~~`flp-write-path-guard`~~ **Done** (landed 2026-08-29). `flp_sort_root()` (env
  `JARVIS_FLP_SORT_ROOT`, defaults to `test_projects/`) + a
  `resolve()`/`relative_to()` guard in `build_flp_sort_handler`, raising
  `FlpSortPathOutsideRoot` before `backup()`/`loader()` run for any path
  outside it.
- ~~`flp-diff-report-emission`~~ **Done** (landed 2026-08-29). `write_diff_report()`
  writes `MixerDiff.as_dict()` as `<stem>.<stamp>.diff.json` beside the
  backup, same timestamp source so the two are pairable; skipped when the
  diff is empty.
  `tests/executor/test_flp_sort.py` (not `tests/flp/` — this doc had the
  wrong path; corrected here) went 18 → 27 tests.

What his files unlock is `flp-real-mixer-convention` — proving the *rules*, which
is the demo. **Sharp edge:** if his convention is order-based, `apply_rules`
raises `ReorderNotSupported` because PyFLP has no insert-move API. That is a
stop-and-report, not a workaround.

---

## Blocked on Ali

Batch these into one sitting where possible.

| id | what he has to do |
|---|---|
| ~~`flp-real-mixer-convention`~~ | **Closed on Ali's instruction, 1 Sep 2026, with no convention dictated.** Do not re-surface it and do not re-dispatch it. It is closed as a *question*, not as a *gap*: `apply_rules()` still runs on an unapproved placeholder ruleset, so the FLP **writing** half stays unbuilt. Inferring a convention from the 26-project audit, from `outroagain`'s DRUMS/BASS/INSTRUMENTS/CHOPS/VOX1-8 layout, or from the placeholder itself is **substituting a decision** — a Class C stop under `agents.md`, and it writes to Ali's real project files, which is not recoverable. Reading `.flp` files is unaffected and still fine. |
| ~~`pywinauto-app-handlers` / `uia-app-scripts`~~ | **Answered 2026-08-29**, via a personal-context agent of Ali's. Apps and end states now live in `docs/tasks/laptop-system-control.md` (power/wifi/bluetooth/display, scheduled tasks, printing, files, process-kill — CLI/API, no UIA) and `docs/tasks/pywinauto-zoom-whatsapp.md` (Zoom's native-dialog join tail, WhatsApp Desktop send-as-personal-number — the actual UIA targets). Both briefed and in flight. |
| `queue-sleep-wake-probe` | Send a message with the lid closed, wake, confirm. **The one Phase 0 criterion with no evidence anywhere.** Ali has said he will do this later (1 Sep 2026) — still open, but stop raising it in handoffs until he brings it up. |
| `finish-1.3-backfill-run` | Confirm `ingest/data/` is the intended final ingest list, and give a window where he expects no replies. The run monopolises Ollama. |
| `1.4-review-loop` | Ask it ten things, delete what is wrong, name exclusion patterns. **Phase 1's actual acceptance gate.** Needs three jobs landed first: `finish-1.3-backfill-run`, `fact-review-and-forget-api`, `ingest-noise-filter`. |
| `oracle-provision` | Signup, identity, card, region pick, then the OCI API key. Over-limit instances auto-terminate since 18 Aug, so "exactly 2 OCPU / 12GB" is load-bearing. |
| `cloud-routine-trigger` | Create the routine in the Claude UI, decide what it may touch, paste endpoint and token into `.env`. |
| `uitars-install` | Create the second Windows account, log in once, then babysit the first runs. |
| `stt-benchmark` / `kokoro-tts` / `voice-acceptance` | Mic placement, read the benchmark and call NPU-vs-Groq, pick a voice by ear, record 30–50 wake clips. All sensory; never an agent's call. |
| `migration-runner-and-ledger`, `sweep-orphan-probe-row`, `jobs-index-and-retention` | Approval to write live schema and mutate live rows. Also which Postgres driver enters `requirements.txt` — there is none today, which is exactly why 0002 sat unapplied and stranded four messages. |

---

## Decisions needed before some of these are even correct

Building these before the answer is substituting an interpretation, not fixing a
defect. All Class C.

- **`router-shared-cooldown-ledger`** — blueprint 0.6 says "a cooldown ledger so
  a limited provider gets skipped instead of hammered" without naming a scope.
  Today `route()` builds a fresh router per call, so the ledger dies each
  request. Audit §3.4 proposes specifying process-lifetime. Also needs a call on
  whether the **executor**, not the bus, reports provider health — the bus
  process never routes, so `/status`'s provider health is structurally always
  empty.
- **`distill-starvation-floor` and `distilled-duplicate-recall-decision`** — audit
  §3.2. Is raw-turn recall *the* Phase 1 product, with Mem0 demoted to
  opportunistic? If yes, `distill-starvation-floor` is deleted rather than built.
  Deleting a raw turn after extraction is irreversible; accepting the duplication
  amends the blueprint's Mem0 commitment. **Deferred by Ali, 2026-08-29:** keep
  both paths exactly as they are for now; revisit once a "final version" of
  memory exists to optimize against. Not a yes/no on the question above — do not
  build either side of it until he actually answers.
- **`backfill-checkpoint-identity-drift`** — blueprint 1.3 says "checkpoint = file
  + offset"; the code keys on content hash. Amend the blueprint or conform the
  code. Must be settled **before** `finish-1.3-backfill-run`.
- **`backfill-batch-embedding-drift`** — 1.3 says "local batch embedding"; the code
  embeds one chunk at a time inside Mem0's `add()`. Batching moves Mem0 in the
  pipeline, which is a component decision. Report, do not restructure.
- **`flp-sort-producer-via-whatsapp`** — wiring "sort out this FLP" gives inbound
  WhatsApp text the power to write files on disk. Inbound text was an injection
  channel until 27 Aug. Explicit consent required.
- **~~Four registered job kinds have no consumer~~ — SETTLED 2 Sep 2026 by
  `action-worker`.** Kept because the warning below is still the reason the
  fix has the shape it does. A third supervised poller now owns `flp_sort`,
  `system_control`, `zoom_join_meeting` and `whatsapp_desktop_send_message`;
  `--kind` takes `nargs="+"`, and the poll loop rotates its kind order so the
  set cannot self-starve. The obvious conformance was **not** taken: letting
  background-worker claim every other kind would put a 2-second
  `zoom_join_meeting` behind a `distill_memory` job that holds Ollama for
  20-130s, which is the exact starvation the two-worker split was built to
  prevent and what left eight inbound messages unclaimed on 26 Aug 2026. The
  blueprint sentence saying the background poller "claims every other
  registered kind" is now wrong in a third way and is `blueprint-corrections`'
  to fix. `docs/board/tasks/action-worker.md` holds the evidence, including
  the first live claim of any of those four kinds.

- **`facts-check-job` scheduling** — audit §3.5: numbered Phase 0.8 with an owner,
  or cut. CLI-vs-job-kind follows from the answer. The 1 Sep 2026 audit did this
  job by hand once (`docs/tasks/docs-drift-audit-report.md`) and found ~12% of
  checkable claims had drifted in four days, which is the empirical case for
  scheduling it rather than cutting it.
- **`voice-command-ingress`** — a bearer-authed `POST /command` on the bus, or the
  voice loop calling `db.jobs.enqueue` directly. Different architectures for
  Phase 4: the first survives the bus moving to Oracle, the second does not.
- **`stt-backends` provider path** — `router/routing.py` is chat-completions only;
  `TASK_PROFILES` has no audio profile and Groq STT is a different endpoint
  shape. Either voice owns its own client or the router grows an audio lane. The
  second is a shared-interface change.
- **Cerebras at rung 2** — its free tier was abolished 17 Aug. Reaching it needs a
  card. Leaving a rung that always 402s at priority 2 is what makes
  `router-402-aborts-chain` bite.

---

## Barriers — nothing else may be mid-run

- **`pytest-ini-carries-local-flags`** — `CLAUDE.md` and `.githooks/pre-commit`
  both hand-carry `-p no:cacheprovider --basetemp=.pytest-basetemp` because the
  system TEMP is locked down, but `addopts` does not, so a bare `pytest` fails
  with `PermissionError`. Changing it changes what every lane's verification
  command resolves to.
- **`enqueue-classifier`** — writes three of the hot files plus a live migration.
  It gates `laptop-executor-service` and `voice-command-ingress`, which should
  queue behind it rather than beside it.
- **`live-schema-drift-guard`** — `tests/db/test_jobs_integration.py:114` calls
  `pytest.skip` on exactly the condition it exists to catch, and the file is
  `--ignore`d by both the documented command and the pre-commit hook. It has
  never run and cannot go red. **DONE 1 Sep 2026.** Was a file-local,
  fakes-only fix — brief `docs/tasks/live-schema-drift-guard.md`. It is scoped
  to make the file *capable* of going red (separating "no credentials" from
  "network failed" from "schema drifted") **without** touching the live `jobs`
  table and **without** removing the `--ignore`, so it is not acting as a
  barrier. Removing the `--ignore` is still a barrier and is still open.

---

## In flight

Nothing via this file anymore — live pickup state is
`work_board_claim.py list` plus `in-progress` statuses under
`docs/board/tasks/`. (The two lanes formerly listed here —
`voice-cli-tests` and `live-schema-drift-guard` — both landed in
`3695c05` and their claims are released.)
