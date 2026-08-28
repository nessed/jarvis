# JARVIS work board

Forward tier. What is left, what it touches, and what may run beside what.
Mapped 27 Aug 2026 from a read-only snapshot at `628b6ea`. This is a planning
index, not a live source of truth: re-check a job's paths and dependencies
against the current tree before claiming it.

`context.md` is this week. `state.md` is now. `history/` is done.
`blueprint.md` is decisions. **This file is next.**

## How to use this

You are one of two orchestrators. Before starting anything:

1. Read **Rules** below. They override any job's own note.
2. Pick a job, inspect its current paths, and atomically claim every file and
   external resource it will change or consume. The claim tool is authoritative;
   this document never records live claim state.
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
Never edit the claim registry directly. The tool prunes a claim only when its
configured stale timeout has passed and its recorded PID is dead; there is no
renew command.

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

Files are not the only thing two agents collide on. These are exclusive
regardless of file ownership. **None of the below is mechanically enforced by
`tools/work_board_claim.py`** — `--resource KEY` records a claim honestly, but
nothing stops a process that never calls it from using Ollama, the mic, or
provider capacity concurrently, the same convention-only gap
`executor/heartbeat.py`'s `--force` override already has. File collisions are
the one thing the tool enforces mechanically; resource collisions still
depend on every lane actually calling `claim` first. Independently reviewed
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
  work.

### Verification and live-route resources

- Claim `test-workspace` before a full suite or any command using
  `.pytest-basetemp`; lanes must not share the same scratch directory.
- Claim `pre-commit` when changing its hook or invoking a commit, because it
  regenerates context status and runs the full offline suite. CORE alone claims
  `git-commit` and commits.
- Claim `meta-webhook` before `repoint_webhook.py` or any callback/subscription
  change, and claim `cloudflare-tunnel` before restarting or replacing a tunnel.
  These affect the live inbound route; never run either beside a Meta live probe.

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
  `tests/db/test_jobs.py:27`, `tests/test_integration.py:11`,
  `tests/executor/test_poller.py:30`, `tests/executor/test_distill_handler.py:59`.
- `executor/handlers/distill.py:112 ChainQueue` is a **second, deliberately
  narrower Protocol on the same object**, split apart to dodge exactly this.
  Treat both as one interface.
- `bus/status.py QueueStatusReader.from_repository` reaches into
  `repository._client`, so it breaks on repository internals while implementing
  neither Protocol.
- `TurnStore` / `FactExtractor` / `ConversationMemory` doubles live in
  `tests/executor/test_distill_handler.py:186,210` and
  `tests/executor/test_whatsapp_handler.py:117,375,398`.
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
| `test-repoint-webhook` | `tools/repoint_webhook.py` has no test file at all — 7.5KB, the whole re-point path uncovered. Also **add the 64-char `META_VERIFY_TOKEN` guard**; the limit is unenforced, not merely untested. | `tools/repoint_webhook.py`, `tests/tools/test_repoint_webhook.py` |
| `test-context-status` | `tools/context_status.py` has no tests and the pre-commit hook runs it on every commit. A break there breaks every commit. | `tests/tools/test_context_status.py` |
| ~~`test-distill-memory-cli`~~ | **Done**, uncommitted. 12 new tests mirroring `test_run_backfill.py`'s pattern. | `tests/tools/test_distill_memory.py` |
| ~~`test-start-jarvis-uncovered-paths`~~ | **Done**, uncommitted. 11 → 28 tests; all four named gaps covered against fakes. | `tests/tools/test_start_jarvis.py` |
| `consult-untested-paths` | The argv-vs-stdin fix has no regression test — the mock discards its arguments. Nothing tests `screen()`, `REFUSED_NAMES`, `SECRET_SHAPES`, which is the whole mechanism enforcing non-negotiable 1. Synthetic key shapes only. | `tests/tools/test_consult.py` |
| `test-openai-chat-client` | `OpenAIChatClient` is never constructed by any test — real header casing and SDK-exception mapping unexercised. | `tests/router/test_routing.py` |
| `poller-invariant-tests` | Nothing asserts the loop calls `touch_heartbeat()`, or that `flp_sort` is registered. Deleting `poller.py:235` breaks no test. | `tests/executor/test_poller.py` |
| `hooks-path-invariant-test` | The hook only fires if someone ran `git config core.hooksPath`. Its own comment says rules that depend on remembering do not hold. | `tests/tools/test_precommit_hook.py` |
| ~~`bus-branch-test-gaps`~~ | **Done**, uncommitted. Timeout + non-JSON-error-body tests added; `_default_jobs()` fallback (incl. loud-500-not-silent-drop) covered. | `tests/bus/test_whatsapp_client.py`, `tests/test_integration.py` |
| `mem0-version-conformance-test` | Six private-API couplings to `mem0ai==2.0.19`; only one fails loudly on a bump. The rest fail mid-extraction on the live path. | `tests/memory/test_mem0_pinning.py` |

### Small corrections

| id | what | files |
|---|---|---|
| ~~`flp-stale-module-docstrings`~~ | **Done**, uncommitted. Rewritten to state current status: registered as `flp_sort`, works on `.venv311`/3.11.5, blocked only by the new channel-groups `IndexError`. | `executor/flp/sort.py`, `executor/flp/__init__.py` |
| ~~`status-dead-letter-key`~~ | **Done**, uncommitted. `_QUEUE_STATUSES` now includes `dead_letter`; test updated. | `bus/status.py`, `tests/status/test_live_queue_status.py` |
| ~~`reframe-archived-consults`~~ | **Done**, uncommitted. Both files wrapped in `frame_untrusted()`'s exact shape (imported the real function, not hand-typed). | `docs/consults/*/response.md` |
| ~~`injection-blocker-stale-status`~~ | **Done**, uncommitted. Only the embedded "What was found and NOT fixed" sub-finding was stale (the system-role recall bug, fixed in `628b6ea`) — the file's top-level "OPEN. Not reproduced." status is a separate, still-unresolved incident (the fake plan-mode text, H4-H6) and was left alone. | `docs/blockers/tool-result-injection.md` |
| ~~`poller-dead-request-completion`~~ | **Partially done**, uncommitted: gained 2 tests, still zero live callers. "Wire it or delete it" was a false binary — its docstring ("give executor jobs the provider router's single async entry point") and signature (`urgent: bool = False`) show it's a deliberately-placed hook for a future *batch*-routed job kind, not dead code to remove. Nothing in the repo currently calls `route(..., urgent=False)` at all (checked 2026-08-28: `ProviderRouter` is only instantiated in `bus/main.py`; the only executor caller, `executor/handlers/whatsapp.py:160`, always passes `urgent=True`). Actually wiring it means inventing that caller, which is `router-deepseek-defer-not-skip`'s job, not this one's — see that entry below. | `executor/poller.py` (hot), `tests/executor/test_poller.py` |
| `verify-configured-model-ids` | Check the four `*_DEFAULT_MODEL` values in `.env` against live catalogues. **If `GROQ_DEFAULT_MODEL` is `llama-3.1-8b-instant` (retired 16 Aug) routable capacity is 3 rungs, not 4.** | `docs/state.md` |

### Greenfield — touches no existing file at all

`uia-tree-dump` · `whisper-npu-build` · `voice-runtime-deps` · `stt-backends` ·
`stt-benchmark` · `wakeword-recorder` · `wakeword-train` · `kokoro-tts` ·
`voice-loop` · `voice-acceptance` · `oracle-provision` · `vps-harden-deploy` ·
`vps-web-ui` · `powercfg-profile` · `cloud-routine-trigger` ·
`phase4-acceptance` · `uitars-install` · `facts-check-job`

Several are file-safe but **run-exclusive** — see Rules. Several are blocked on
Ali — see below. `facts-check-job` is the blueprint's only defence against its
own rot and has produced nothing in four days.

---

## Available now — serialize on a named file

### `router/routing.py` — five jobs, fixed order

1. `router-deepseek-weekday-gate` *(trivial)* — the gate tests the hour only, so
   the router refuses DeepSeek for seven hours every Saturday and Sunday, which
   are its cheapest. **Do this first.**
2. `router-402-aborts-chain` *(small)* — a Cerebras 402 reaches the bare `raise`
   and kills the whole cascade with **no cooldown recorded**, so it recurs
   forever. Any batch job that sees Groq 429 dies at rung 2 and never reaches
   OpenRouter or DeepSeek.
3. `router-model-env-validation` *(small)* — a rung with no `*_DEFAULT_MODEL`
   passes `_configured()`, enters the candidate list, then silently no-ops.
4. `router-deepseek-defer-not-skip` *(large, cross-area)* — the gate skips the
   rung instead of deferring the job via `run_after`, which the queue already
   supports. Writes three hot files. Dispatch as its own lane.
   **Corrected 2026-08-28:** not yet buildable as scoped. `_deepseek_allowed`'s
   weekday/peak gate (`router/routing.py:296-305`) only fires when
   `urgent=False`, and nothing in the repo calls `route()`/`request_completion`
   with `urgent=False` today — the only executor caller,
   `executor/handlers/whatsapp.py:160`, always passes `urgent=True` (a live
   reply), and `executor/poller.py`'s `request_completion` (the intended hook
   for a batch caller — see `poller-dead-request-completion`) has zero
   callers. Deferring "the job" via `run_after` needs an actual batch-routed
   job kind to defer, which doesn't exist yet. Building one to make this job
   exercisable is scope invention, not the described fix — report and hold
   rather than substitute.
5. `router-shared-cooldown-ledger` *(large, cross-area, blocked)* — see
   Decisions.

### `executor/poller.py` — six jobs

`distill-chain-reseed-in-loop`, `poller-drain-without-idle-sleep` and
`heartbeat-clear-on-exit` all edit the same eight lines of `main()`'s loop.
**Batch them into one lane** — strictly cheaper than three dispatches.

- `distill-chain-reseed-in-loop` — three consecutive extraction failures end
  distillation permanently until someone restarts the executor. `seed_distill_chain()`
  is already idempotent; it just never runs inside the loop.
- `poller-drain-without-idle-sleep` — the loop sleeps a full interval after every
  job, so a backlog drains one job per interval. One of the four terms in the
  ~25 messages/hour distill ceiling, and the only one that is free to fix.
- `heartbeat-clear-on-exit` — the executor never removes `.executor-heartbeat`,
  so batch tools refuse for up to 600s after a clean shutdown. Must stay
  fail-open.
- `flp-permanent-failure-no-retry` *(solo)* — rewrites `poll_once`'s exception
  handling. `ReorderNotSupported` and `FileNotFoundError` are permanent and get
  retried three times anyway.

### `memory/store.py` — three jobs

1. `undistilled-turns-indexed-query` *(medium)* — `undistilled_turns()` loads and
   JSON-decodes **every row** on every call, including the `limit=1` emptiness
   check the distill chain runs each tick.
2. `mem0-search-overfetch` *(small)* — every Mem0 search materialises the whole
   fact table just to take `len()` of it, then asks sqlite-vec for that many.
   Becomes a one-line consumer of job 1.
3. `sqlite-wal-and-busy-timeout` *(small)* — no connection sets `journal_mode` or
   `busy_timeout`, while three connections to one `memory.db` exist across two
   processes. A concurrent write raises "database is locked" immediately.

### `.env.example` — one writer, three contributors

18 variables the code reads are absent, and `SUPABASE_KEY` is present but read
by nothing. **`SUPABASE_SECRET_KEY` is required and missing.** `README.md` tells
a new setup to copy this file, so a fresh clone cannot reach the queue.

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

- `bus/main.py` — `status-distill-chain-liveness`, `status-provider-health-source`,
  `voice-command-ingress`, `webhook-message-dedup`, `enqueue-classifier`,
  `bus-offbox-packaging`. One at a time, and `enqueue-classifier` blocks most of
  Phase 4 by itself.
- `bus/status.py` — ~~`status-dead-letter-key`~~ (done), `status-count-queries`,
  `status-distill-chain-liveness`. Do as one pass.
- `executor/flp/sort.py` — `flp-real-mixer-convention` (blocked on Ali) is all
  that's left. ~~`flp-write-path-guard`~~, ~~`flp-diff-report-emission`~~,
  ~~`flp-stale-module-docstrings`~~ all done.

---

## Phase 2 — what is actually blocked and what is not

**Correction worth keeping:** Ali's `.flp` copies are **not** blocking all
Phase 2 work.

- `flp-sort-real-flp-end-to-end` **can run today.** PyFLP ships its own upstream
  fixture (`FL 20.8.4.flp`), and `JARVIS_FLP_FIXTURE` already points anywhere.
  Nothing has ever executed `sort.py`'s PyFLP calls — every proof on disk is of
  PyFLP itself. Run it under `.venv311` (**pinned 3.11.5**; 3.11.6 backported the
  empty-enum guard) and name the directory in the command, or a bare `-m realflp`
  collects the whole tree and dies on `ModuleNotFoundError: httpx`.
- ~~`flp-write-path-guard`~~ **Done**, uncommitted. `flp_sort_root()` (env
  `JARVIS_FLP_SORT_ROOT`, defaults to `test_projects/`) + a
  `resolve()`/`relative_to()` guard in `build_flp_sort_handler`, raising
  `FlpSortPathOutsideRoot` before `backup()`/`loader()` run for any path
  outside it.
- ~~`flp-diff-report-emission`~~ **Done**, uncommitted. `write_diff_report()`
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
| `flp-real-mixer-convention` | 2–3 real `.flp` copies into `test_projects/`, and dictate what "sorted" means — order, prefixes, colours, routing groups. Colours and routing are not implemented at all today; only renames. |
| `pywinauto-app-handlers` / `uia-app-scripts` | Name the 2–3 apps and the end state per app in plain words. Nothing starts without the list. |
| `queue-sleep-wake-probe` | Send a message with the lid closed, wake, confirm. **The one Phase 0 criterion with no evidence anywhere.** |
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
  amends the blueprint's Mem0 commitment.
- **`backfill-checkpoint-identity-drift`** — blueprint 1.3 says "checkpoint = file
  + offset"; the code keys on content hash. Amend the blueprint or conform the
  code. Must be settled **before** `finish-1.3-backfill-run`.
- **`backfill-batch-embedding-drift`** — 1.3 says "local batch embedding"; the code
  embeds one chunk at a time inside Mem0's `add()`. Batching moves Mem0 in the
  pipeline, which is a component decision. Report, do not restructure.
- **`flp-sort-producer-via-whatsapp`** — wiring "sort out this FLP" gives inbound
  WhatsApp text the power to write files on disk. Inbound text was an injection
  channel until 27 Aug. Explicit consent required.
- **`facts-check-job` scheduling** — audit §3.5: numbered Phase 0.8 with an owner,
  or cut. CLI-vs-job-kind follows from the answer.
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
  never run and cannot go red.

---
