# Blueprint drift audit

Read-only audit, 27 August 2026, 17:12–17:25 PST.

**Snapshot.** `HEAD d3094ad`, 12 modified files, 7 untracked paths. Another
session owned this tree throughout and committed `d3094ad`, then edited
`.gitignore`, `pytest.ini` and added `tests/flp/` while this audit ran. Findings
are timestamped where the tree moved under them. Nothing was edited by this
audit except this file.

Evidence rule: every claim cites a path and line, or a command and its output.
Where an observation was unavailable it is in section 4 rather than guessed.

---

## 1. Where we actually are, phase by phase

**Phase 0 is genuinely complete. Phase 1 passes its stated acceptance by a path
the blueprint did not specify, and its real gate has never been run. Phase 2 is
scaffolding blocked on an interpreter and two Class C inputs. Phases 3, 4 and 5
have zero code.**

### Phase 0 — harden the bus: complete, with one component built but not functioning as specified

Declared complete in `docs/state.md:14`. It is.

The three stated criteria:

- **Unauthorized webhook calls bounce.** Real. `bus/security.py` does HMAC-SHA256
  with `compare_digest` plus hex-shape validation, 403 on absent, malformed and
  bad signatures, bearer middleware everywhere else with `/webhook` exempt.
- **A job moves queued → running → done in logs.** Real, and proven live.
  `docs/scalability-review.md:24` — "Real messages 34 / 34 reached `done`."
- **A message survives the laptop being asleep and executes on wake.** Not
  evidenced anywhere in the repo. The queue is durable and the mechanism is
  sound, but no probe covers it. See section 4.

Phase 0 also specified the router. It is built and it is good: `task_profile`
reordering, `retry-after` and `x-ratelimit-*` parsing, `not_a_router_target` /
`emergency_only` / `capped` flags, a DeepSeek off-peak gate. Three things do not
match the spec.

**The cooldown ledger has no lifetime beyond a single call.**

`router/routing.py:372-376` builds a fresh `ProviderRouter()` per call, and
`__init__` at `:173` resets `self.health` to empty. Both production callers go
through that function:

- `executor/handlers/whatsapp.py:160`
- `executor/poller.py:269`

A provider that 429s is skipped for the rest of that one cascade and retried on
the very next message. Blueprint 0.6 asks for "a cooldown ledger so a limited
provider gets skipped instead of hammered." Within a call, yes. Across calls,
there is no ledger. `load_providers()` also re-reads `providers.yaml` from disk
on every route call.

**`/status`'s per-provider health is structurally always empty.**

`bus/main.py:77` creates a router in the bus process; `bus/main.py:47-56`
reports its `.health`. `bus/` contains no routing call at all — the webhook is
enqueue-only (`bus/main.py:89-98`), which is blueprint 0.5 as designed. The
health being reported belongs to a router that has never made a request, in a
process that never routes.

**Four rungs silently no-op when an undocumented env var is unset.**

`router/providers.yaml` resolves `${GROQ_DEFAULT_MODEL}`,
`${CEREBRAS_DEFAULT_MODEL}`, `${NVIDIA_DEFAULT_MODEL}`, `${GEMINI_DEFAULT_MODEL}`,
plus `CLAUDE_API_BASE_URL` and `CLAUDE_API_DEFAULT_MODEL`. `_configured()` at
`routing.py:241-244` checks endpoint and key only, so such a rung enters the
candidate list and then hits `routing.py:216-218`, which appends
`"<name>: no model configured"` and continues. That string surfaces only inside
`NoEligibleProvider`, and only if every rung fails. None of those six variables
are in `.env.example`.

**A fourth router defect is in section 2b**, because it only becomes visible once
the provider claims are re-verified: a Cerebras `402` aborts the entire fallback
chain permanently, with no cooldown recorded. For a `batch` profile that means
any job which sees Groq 429 dies at rung 2 and never reaches OpenRouter or
DeepSeek.

**Verdict: complete as specified. The ledger is the one place the code does not
do what 0.6 asked, and no test can see it, because every router test constructs
a router and drives it directly.**

### Phase 1 — memory: not complete, and both closer to and further from done than the docs say

`docs/state.md:14` says "Phase 1 underway." Correct, but the shape is not what
either `state.md` or `docs/history/whatsapp-reply-failures.md` describes.

**The behavioural criterion passes.** Blueprint: "you tell it something on
Monday and it uses it unprompted on Thursday." `memory/conversation.py:80-82`
searches the shared index and keeps everything that is not another
conversation's turn. Distilled Mem0 facts land in the same `memory.db`
(`memory/runtime.py:74`, `:105`) with `source = "mem0"`
(`memory/mem0_wrapper.py:161`), so they pass that filter. A Monday turn is
recallable on Thursday from the raw path alone, in about half a second, with no
batch involved. Writes are on by default (`executor/handlers/whatsapp.py:133`),
and the reply path does no LLM extraction at all — `memory/service.py:61-67`:
"There is intentionally no LLM-based extraction here."

**The architectural commitment does not.** Blueprint 1.1 says "Mem0 wrapping
it." What is live is sqlite-vec wrapping nothing, with Mem0 demoted to a
background chain that has no guarantee of running.

- **Throughput on an idle queue is about 25 messages per hour.** One turn per
  job (`executor/handlers/distill.py:90`), a 15s busy cooldown (`:93`), a 5s
  poll interval (`executor/poller.py:44`), on top of ~55s extraction
  (`docs/scalability-review.md:66`). One WhatsApp message produces two turns
  (`whatsapp.py:211-212`). The reply path handles ~20 messages per minute
  (`scalability-review.md:27`).
- **Throughput under live traffic is zero, by design.**
  `executor/handlers/distill.py:264-270` yields the whole pass whenever any
  queued non-distill row is ready. That is the correct anti-starvation
  mechanism. It also means the backlog drains only in idle gaps.
- **The chain has a terminal state.** `DISTILL_MAX_ATTEMPTS = 3`
  (`distill.py:109`) and the successor is enqueued last, after extraction
  (`distill.py:289`). Three consecutive extraction failures dead-letter the row
  with no successor ever written. The repo's own test asserts this —
  `tests/executor/test_distill_handler.py:711-726`. Recovery needs an executor
  restart: `_seed_distill_chain()` runs once before the loop
  (`poller.py:228`) and never inside it.
- **Nothing measures the backlog.** `bus/status.py:80-104` carries queue depths,
  last job, provider health and retry health, and nothing about undistilled
  turns. A dead chain and a drained one look identical from outside.
- **Nothing is lost when turns outrun the chain, but nothing converges.** Turns
  stay `distilled: false` and stay fully recallable. What never happens is dedup,
  contradiction resolution and consolidation — the entire reason the blueprint
  chose Mem0. `mark_distilled` (`conversation.py:94-96`) sets a flag and does not
  delete the raw turn, so after distillation the same content sits in the index
  twice, both eligible for the same recall.

**Blueprint 1.2 (choose the corpus) is done** — `ingest/data/me.txt`, 9,716
bytes. **1.3 (backfill) ran once and stopped** —
`ingest/data/.checkpoints/5dbee562….json` is
`{"next_chunk_index": 1, "updated_at": "2026-08-26T19:28:24Z"}`. **1.4's review
loop has never run.** That loop — the user interrogating it with ten things it
should know, deleting wrong facts, naming exclusion patterns — is the actual
acceptance gate for Phase 1, and it is Class C.

**Verdict: not complete, and the blocker is not the one `state.md` lists.**

### Phase 2 — FL Studio: scaffolding only, blocked three ways

`docs/state.md:16` calls it "scaffolding started in parallel
(blueprint-authorized), blocked." Accurate. The block is deeper than the docs
record.

- `executor/flp/sort.py` is built and unit-tested against fakes — `flp_backup`,
  `load`/`save`, `apply_rules`, `diff_report`, `verify`,
  `build_flp_sort_handler`. Registered as `flp_sort` in `executor/poller.py:82`.
  **Nothing enqueues it.**
- **The interpreter is still wrong, and the lane knows it.** `.venv311` is
  Python 3.11.9. PyFLP 2.2.1 needs 3.11.0–3.11.5: the empty-enum guard was
  backported in 3.11.6 and is present in this machine's
  `Python311/Lib/enum.py:1116-1117`. The other session proved the boundary tag by
  tag and holds a high-confidence verdict to install 3.11.5
  (`docs/consults/2026-08-27-lane-a-was-approved-to-install/verdict.json`). As of
  17:22 it was not executed, and `requirements-flp.txt` does not exist.
- **The new real-FLP test file has a circular skip guard.**
  `tests/flp/test_flp_real.py:26` is
  `PYFLP_OK = (3, 8) <= sys.version_info[:3] < (3, 11, 6)`, and `:41-44` skips
  with "Use .venv311." `.venv311` **is** 3.11.9. Running the documented command
  in that environment skips all three tests and tells the operator to use the
  environment they are already in. This is the false-green shape
  `docs/blockers/pyflp-python-312.md` itself warns about. The lane is live and
  may still fix it, but a green `realflp` run before 3.11.5 is installed proves
  nothing.
- **Blueprint 2.1 is untouched.** `test_projects/` does not exist. The mixer
  convention has never been dictated, so `apply_rules()` is written against a
  placeholder ruleset shape. Both are Class C.
- **Blueprint 2.4 (pywinauto) has zero code.** grep for
  `pywinauto|flaui|autohotkey` across the tree returns nothing.

**Verdict: roughly a tenth of Phase 2, gated on one mechanical fix and two Class
C inputs from the user.**

### Phase 3 — voice: not started

grep for `whisper|kokoro|pipecat|openwakeword|silero|piper` across all code,
requirements and config returns two hits, both irrelevant: a docstring in
`executor/handlers/whatsapp.py:48` listing unhandled message types, and the
user's own corpus file. No dependency, no module, no benchmark script.

### Phase 4 — always-on split: not started

`infra/` contains a single `.gitkeep`. No Oracle, no terraform, no OCI config, no
`needs_laptop` classifier, no Cowork or Cloud Routine integration. grep for
`oracle|oci|terraform|hetzner|cowork|routine|needs_laptop` across code returns
one hit, in the user's corpus file.

Worth stating: the whole stack runs on the laptop today. `state.md`'s open
blocker 3 — the ephemeral tunnel, "nothing receives messages while the laptop is
off" — is not a defect. It is Phase 4's entire premise, being carried as a
blocker against Phase 1.

### Phase 5 — vision fallback: not started

Zero code. Correctly so — it is optional and last.

### Outside the phases: the one Ongoing deliverable, never built

The blueprint's "Ongoing" section specifies "a monthly facts-check job —
re-verify the Agent SDK pause, DeepSeek rates, free-model rosters, promo
expiries, and write you a one-page diff report." No such tool, no scheduled task,
no cron entry. It is the only mechanism the blueprint has for defending itself
against rot, and it is the exact mechanism that would have caught the +50% Claude
promo expiring in four days.

---

## 2. Where a doc claims something the code or the world contradicts

Organised by document. Each entry is the claim, then the contradiction.

### `docs/state.md`

**"No personal corpus has been read or ingested"** (`state.md:39`).
`ingest/data/me.txt` exists at 9,716 bytes, and
`ingest/data/.checkpoints/5dbee562….json` records a backfill that ran on
2026-08-26T19:28Z and wrote through the real `remember()` path
(`ingest/backfill.py:54` → `ingest/mem0_sink.py:24`). `memory.db` is 3.2 MB.
**The privacy rule itself was honoured** — the file is inside the opt-in intake
folder and is gitignored by `ingest/data/.gitignore:2`. The claim is what is
wrong, and it is the claim a reader would rely on.

**"Dedups by Meta's message id"** (`state.md:31`) reads as if duplicate
deliveries are handled. They are handled at the *handler*
(`executor/handlers/whatsapp.py:66-98`), which suppresses duplicate replies.
`bus/main.py:97` still enqueues unconditionally, so duplicate *jobs* are still
created and still claimed. `tests/test_integration.py:44` pins that behaviour
deliberately. `docs/blockers/supabase-unreachable-from-laptop.md` recorded the
gap explicitly and it was never closed or refused.

**"Bus logging | uvicorn's access log redacts `hub.verify_token`"**
(`state.md:36`) was true and insufficient. A real handshake on 27 Aug 2026
carried both `hub.verify_token` and `hub_verify_token`; only the dotted spelling
matched, and the underscore duplicate went to `tools/bus.out.log` in plaintext.
The fix is in flight and uncommitted, widening the regex to
`hub[._]verify_token`. `tools/*.log` is gitignored so nothing reached git, but a
live credential is on disk. Rotation is the user's call.

**Open blocker 4** still says "Blocks all of Phase 2 until a Python 3.11
environment is set up." `.venv311` exists. The blocker is now the *patch
release*, not the minor version, and `state.md` does not say so.

**The four open blockers do not include the Phase 1 throughput limit.**
`docs/history/whatsapp-reply-failures.md:124-125` states it "is recorded in
`docs/state.md` as the open blocker it is rather than being papered over." It is
not there. `state.md:108-110` records the 250× extraction/embedding asymmetry but
files it as design rationale, not as a limit.

**The extraction model is never named.** `state.md:38` names Ollama and
`nomic-embed-text`. `llama3.1:8b` (`memory/mem0_wrapper.py:35`) is the single
most consequential component in the Phase 1 bottleneck and appears nowhere in the
component table.

### `docs/history/whatsapp-reply-failures.md`

**"Phase 1's memory goal is NOT MET on this hardware"** — half true, and its
premise is gone. It was written when the only write path was Mem0 extraction and
writes had just been switched off (`129de3a`). Twelve hours later `603cec6`
replaced the write path. Raw-turn memory works. The *hardware* claim is still
true and still unmitigated: local extraction is 20–130s per call, and the
distilled layer is bound by exactly that.

**"(default off)"** for `JARVIS_MEMORY_WRITES` (`:113`). It is on by default —
`executor/handlers/whatsapp.py:133`.

History is append-only, correctly, so these are not errors to fix in place. They
are conclusions a reader will act on that the code has since overtaken, and
nothing in `state.md` supersedes them.

### `README.md`

Three claims contradicted by `state.md` itself:

- `README.md:29-31` — "Nothing calls memory during a conversation. The plumbing
  exists, it just isn't wired into the message path." It is wired:
  `executor/handlers/whatsapp.py` does recall → route → send → `remember_turn`.
- `README.md:32-33` — "the migration hasn't been applied to the live database."
  `state.md:21` says 0001 and 0002 are applied live.
- `README.md:40-41` — "Phases 2 through 5 … None started." Phase 2 scaffolding
  landed in `607bde1`.

Minor: `README.md:45` says "You need Python 3.11+", while `.venv` is 3.12.10 and
`requirements.txt` pins `pyflp==2.2.1`, which cannot run on 3.12.

### `.env.example`

**It is not a usable template, and `README.md:47` tells the user to copy it.**
Eleven variables the code reads are absent, and one that is present is read by
nothing.

- `SUPABASE_SECRET_KEY` — **required**. `db/jobs.py:283` reads only it or
  `SUPABASE_SERVICE_ROLE_KEY`. `.env.example` instead lists `SUPABASE_KEY`, which
  no code path reads.
- Also read, also absent: `SUPABASE_QUEUE_TIMEOUT_SECONDS`,
  `JARVIS_MEMORY_WRITES`, `JARVIS_DISTILL`, `JARVIS_POLL_INTERVAL_SECONDS`,
  `JARVIS_EXECUTOR_HEARTBEAT`, `OLLAMA_EMBEDDING_TIMEOUT_SECONDS`,
  `OLLAMA_FACT_EXTRACTION_MODEL`, `OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS`,
  `OPENROUTER_BASE_URL`, `OPENROUTER_DEEPSEEK_MODEL`.
- Plus the six `providers.yaml` variables named in section 1.

`OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS` is now a startup precondition, not a
tuning knob: set it above the handler timeout and `python -m executor.poller`
refuses to start (`poller.py:214` → `distill.py:172-189`). That is documented
only in source comments.

### `docs/blueprint.md`

**1.3 still specifies "constrained JSON-schema structured decoding."**
`docs/tasks/mem0_wrapper.md` withdrew that in favour of Mem0's shipped Ollama
adapter with `json_object` plus pydantic validation and one retry, and
`memory/mem0_wrapper.py:363` does exactly that. The sibling amendment in the same
blueprint sentence — NIM geo-blocking — *was* written into the blueprint. This
one was not. A reader of 1.3 today will believe the pipeline does something it
does not.

**The routing chain is presented as 8 rungs.** `providers.yaml` has 9: Mistral
was inserted at priority 6, shifting DeepSeek to 7, Claude Max to 8, Claude API
to 9. The blueprint mentions Mistral only as an unnumbered "spare lane."

Provider pricing, model-name and rate-limit claims: section 2b.

### `docs/tasks/` — the briefs

**Ownership is unattributable.** `docs/tasks/injection-forensics.md` says "Do not
touch `tools/start_jarvis.py`, `executor/`, `bus/` … report the exact change and
stop." `docs/tasks/distill-chain-verification.md` says
"`executor/handlers/whatsapp.py` — docstring only, no behaviour change" and "You
do not own `executor/handlers/distill.py`." The uncommitted diff has
`whatsapp.py +37/−4` (a real behaviour change — recalled memory moved from
`role: system` to a fenced `role: user`), `distill.py +158`, `bus/logging.py
+13`, `start_jarvis.py +18`, `db/jobs.py +42`, `poller.py +9`. The code looks
correct and is tested. What is missing is the record of whether the orchestrator
applied reported fixes (allowed) or a lane exceeded ownership (not). That
distinction is the whole point of the rule.

**About a third of the briefs left no artifact.** `next_work_scan.md`,
`status_recovery.md`, `blueprint_alignment.md`, `push_readiness.md`,
`tunnel_recovery.md`, `phase0_final_suite.md`, `full_suite_final.md`,
`offline_integration_validation.md`, `acceptance_security.md`,
`live_memory_smoke.md`, `ollama_readiness.md`, `l3.md`, `l4.md` — their outputs
went to an orchestrator's context and nowhere else. They are unauditable.

**Two deviations worth recording.** The DeepSeek off-peak gate *skips the rung*
rather than *deferring the job*: `_deepseek_allowed` returns False and
`ordered_providers` filters DeepSeek out. Blueprint 0.6 and `router.md` both say
"wait." A peak-hour non-urgent job needing 1M context fails now instead of
waiting three hours, and the queue has a `run_after` column that could express
the deferral. Separately, the backfill checkpoint keys on content hash rather
than file+offset (`ingest/pipeline.py`, `tools/run_backfill.py`) — rename-safe
and tamper-evident, but editing an ingested file resumes from chunk 0 and
re-remembers everything.

**`requirements-flp.txt` was specified twice and does not exist.** Meanwhile
`pyflp==2.2.1` is pinned into the main `requirements.txt`, the 3.12 environment
where it provably cannot parse or save.

### Recommendations neither implemented nor refused

These are the audit's core findings. A recommendation that was never done and
never rejected leaves no trace that anyone decided anything.

- **The replay harness.** `docs/scalability-review.md:126-130` — "What found them
  was replaying real failing job payloads through the real handler with only the
  outbound send faked. That belongs in the standard toolkit." It found all three
  live bugs. It was recommended into the toolkit twice. It does not exist:
  `tools/` holds six scripts and none of them is it.
  `build_whatsapp_webhook_handler` already takes `send_text_message=` as its only
  outbound seam (`executor/handlers/whatsapp.py:141`), which is exactly the shape
  needed.
- **Webhook-level dedup.** Recorded as "Not fixed as part of this session" in
  `docs/blockers/supabase-unreachable-from-laptop.md`, then masked by
  `state.md:31`.
- **The orphaned `queue-durability-probe-` row.**
  `docs/handoff/queue_durability.md:135-141` flags one live `jobs` row left
  `running` by an early probe. No sweep, no follow-up, no refusal. Its
  consequence has since changed: with 0002 applied, `claim_next_job`'s
  stale-lease branch will reclaim it, fail it as an unknown kind, and dead-letter
  it — polluting `retry_health`'s `dead_letter_count`.
- **`deps-mem0_wrapper.txt`** — named as unaddressed twice in
  `docs/workflow_overview.md` §12.5 and §12.6, still absent. Acknowledged rather
  than silently dropped.

### What the test suite proves, and where it cannot see

The suite is well-built and it has a specific blind spot: everything that
crosses a process boundary except sqlite is faked.

**The regression test for the worst live bug cannot fail.** Migration 0002 was
never applied live, `column jobs.attempts does not exist`, retries themselves
failed, four messages stranded. The only live-schema probe is
`tests/db/test_jobs_integration.py:92-120`, and it calls `pytest.skip(...)` at
`:114` on exactly that condition. That file is also `--ignore`d by both
`CLAUDE.md`'s documented command and `.githooks/pre-commit`, so it never runs.
The migration tests that do run are text greps —
`tests/db/test_jobs.py:289` asserts `"add column if not exists attempts" in
migration`. No SQL is executed by any test, offline or live.

**Two of the three anchor bugs have no regression test.** Revert `max_tokens`
from 512 to 128 in `memory/mem0_wrapper.py:330` and the suite stays green — grep
for `512` or `LlmConfig` across `tests/` returns nothing. Move `consult.py`'s
prompt back into argv and the suite stays green —
`tests/tools/test_consult.py:86` is
`monkeypatch.setattr(consult.subprocess, "run", lambda *a, **k: _Completed())`,
which discards the arguments the fix was about. Only bug 2 (the non-idempotent
prompt patch) has a real guard.

**Also untested:** `tools/repoint_webhook.py` has no test file at all, so the
64-character `META_VERIFY_TOKEN` limit and the whole re-point path are
uncovered; `resolves_on_public_dns` (`tools/start_jarvis.py:268`) is untested, so
the ISP-DNS false-negative has no guard; `OpenAIChatClient` is never constructed
by any test, so real header casing and SDK-exception mapping are unexercised; and
nothing asserts the poller calls `touch_heartbeat()` — deleting
`executor/poller.py:235` breaks no test.

**No conformance checking exists for 11 production Protocols.** No
`@runtime_checkable`, no `isinstance` assertion, no mypy, no ruff, no
`pyproject.toml`. `ChainQueue` (`executor/handlers/distill.py:112-118`) documents
the workaround in its own docstring: it is "deliberately separate from
`db.jobs.JobRepository` so that Protocol stays exactly as wide as it is and every
existing test double keeps satisfying it." Two overlapping Protocols now describe
one object, split specifically to avoid stranding test doubles. That is a
mitigation for the missing check, not a fix.

**`tests/live/` has one test**, and it drives a code path the reply handler no
longer uses. `tests/live/test_memory_roundtrip.py:35-59` writes and reads one
synthetic fact in one process against a `tmp_path` database that is then
discarded, via `open_local_mem0_memory` — while
`executor/handlers/whatsapp.py:23` imports `open_conversation_memory`. The actual
reply path has zero live coverage.

### One security item, mid-fix

`docs/blockers/tool-result-injection.md` (untracked, 16 KB) records that on
27 Aug ~10:07–10:12 UTC, text claiming "## Exited Plan Mode" plus an instruction
to stop using file tools and route everything through shell appeared attached to
the output of a read-only `Get-CimInstance Win32_Process` call. The session had
never been in plan mode. The instruction was not followed. The file's framing is
right: **the vector is the finding, not the payload.**

Forensics covered 10,971 files, `.git` objects, 23 session transcripts, shell
snapshots and temp dirs, with one honestly-named gap — `.pytest_cache/` is
permission-denied. H1 (string on disk) and H3 (hook/plugin) are ruled out. H2 —
`consult.py` passing sub-model output through unframed — was confirmed as a real
capability, ruled out as this event's cause on timing, and **fixed**
(uncommitted, with tests). H4 (harness mode-transition text not persisted to
JSONL) is open and best-supported, with a corroborating sighting on 25 Aug.

Two things to carry forward:

- **The cross-lane fix landed but the blocker file was not updated.** It still
  reads "What was found and NOT fixed," while `executor/handlers/whatsapp.py:190`
  now fences recalled context into the user role. Anyone reading it today gets a
  stale picture of a live fix.
- **The framing in `consult.py` is forward-only.** Two archived consults on disk
  are unframed sub-model text a future agent will read:
  `docs/consults/2026-08-27-path-smoke-test/response.md`, which closes by asking
  the reader a direct question, and
  `docs/consults/2026-08-27-distill-scheduling-mechanism/response.md`. Only the
  17:05 lane-a verdict carries `_untrusted`.

On truncated consults: `consult.py` shipped in `b89e203` (26 Aug 21:53) and was
broken until ~15:17 on 27 Aug — about 17 hours in which `agents.md`'s "every
Class B stop runs a consult" could not have been satisfied. Only one archived
consult predates the fix, and its verdict is the low-confidence fallback. **The
decision taken on it is safe anyway**: the sub-model noticed it had received one
line, read the prompts off disk itself, and diagnosed the `cmd.exe` truncation
correctly. No action rests on a confidently-wrong answer. What cannot be
established is whether any Class B stop in that window was resolved without a
consult.

---

## 2b. Blueprint provider claims versus the world

Re-verified 27 Aug 2026 against provider-owned sources. The blueprint is dated
23 Aug 2026; per the project's own rules its pricing, model names, rate limits
and free tiers are claims, not facts.

### The two urgent ones

**The +50% Claude weekly promo is still live and still ends 31 Aug 2026 — four
days out. No fourth extension has been announced.**

Anthropic's promo article opens with "We've extended this promotion. Increased
weekly limits now run through August 31, 2026," and its terms read "valid from
May 13, 2026 through August 31, 2026 at 11:59 PM PT."

- https://support.claude.com/en/articles/15910845 — updated ~19 Aug 2026

There have been three extensions (13 Jul → 19 Jul → 19 Aug → 31 Aug), each
announced on or near the prior expiry. Anthropic says it hopes to make the
increase permanent but has not committed, citing capacity. A fourth extension on
or about 31 Aug is likely on that pattern and is **not** a fact. The blueprint's
planning consequence stands: budget scheduled jobs against the smaller weekly cap
from 1 Sep unless it lands.

Two adjacent claims: the 6 May 2026 permanent doubling of Claude Code 5-hour
limits and removal of peak-hour throttling is confirmed and permanent
(https://www.anthropic.com/news/higher-limits-spacex). Fable 5 being capped at
50% of the weekly allowance on Max is confirmed verbatim. The blueprint's further
claim that Fable 5 "weighs roughly 2× an Opus session" is **not** in Anthropic's
article, which says only that it uses limits faster. That multiplier is
unverified.

**The Agent SDK billing split is still paused. `tools/consult.py` has no
per-call cost and nothing to budget.**

The Help Center article still opens with the pause note verbatim: "Update
June 15: We're pausing the changes to Claude Agent SDK usage described below. For
now, nothing has changed: Claude Agent SDK, `claude -p`, and third-party app
usage still draw from your subscription's usage limits."

- https://support.claude.com/en/articles/15036540 — last updated 16 Jun 2026

No newer announcement exists. The blueprint is correct and unchanged here.

### What is stale

**Cerebras: the free tier was abolished on 17 Aug 2026 — six days before the
blueprint called it "confirmed."** It was replaced by a $5 free trial requiring a
verified payment method, expiring 30 days after grant. The 1M tokens/day figure
survives only as that trial's cap. The context cap is 65k on free, not 8K. The
catalogue is `gpt-oss-120b` and `gemma-4-31b` — **no GLM model of any version is
served**, so the blueprint's `GLM-4.7` is wrong on two counts.

This fully explains `state.md`'s "authenticates, chat returns 402." The key is
valid; there is no credit behind it. Unblocking needs a card on file, which is
Class C.

- https://inference-docs.cerebras.ai/support/rate-limits
- https://www.cerebras.ai/pricing

**Groq: `llama-3.1-8b-instant` was shut down on 16 Aug 2026** — seven days before
the blueprint named it as Groq's permissive lane. The replacement is
`openai/gpt-oss-20b`. The ~14,400 RPD figure the blueprint attributes to it now
belongs to `llama-prompt-guard-2-22m`/`-86m`, which are classifiers, not chat
models. Everything else about Groq holds: the per-model TPD shape, the
30 RPM / 1K RPD / 8K TPM / 200K TPD numbers for gpt-oss-120b and 20b, org-level
limits, cached tokens excluded, and `whisper-large-v3-turbo` still free at
20 RPM / 2K RPD. Groq's models page still lists the retired model under
Production while its deprecations page gives a shutdown date 11 days past — treat
the models page as stale.

**NVIDIA NIM: the blueprint contradicts itself, and one claim is false.** It
lists NIM as rung 3 and as a free DeepSeek-class lane, while its own §1.3
amendment in the same file states NIM is geo-blocked from Pakistan.
`docs/state.md` resolves this correctly as Deferred; the blueprint prose was never
reconciled. The geo-block is mechanical — signup needs phone verification and +92
is absent from the country dropdown, with nine forum threads and zero staff
resolutions. The "200 RPM raise can be requested" claim is **false**: NVIDIA staff
stated on 11 May 2026 that there is no way to obtain an increase on that tier. The
~40 RPM cap is real and is global across all models, not per-model.

**Mistral: the tier was renamed and every model ID the blueprint's briefs named
is retired.** "Experiment" is now "Free mode"; the old tier URL 404s. Mistral no
longer publishes numeric free-tier limits — both docs and help centre redirect to
a per-workspace page. `magistral-small` and `open-mistral-nemo` both retired
31 Jul 2026, and `mistral-small-latest` is absent from current docs. Mistral
Medium 3 and 3.1 retire 31 Aug 2026, four days out. **This cannot break the
repo**: `providers.yaml` sets `discover_chat_model: true` and pins no ID. The
cause of the 403 is not documented anywhere — Mistral's error glossary lists 403
with no explanation at all.

**Gemini: the free tier is alive, its numbers are now login-gated, and the model
line has moved five generations.** Google removed the per-model free-tier limit
table from the docs on or before 18 Aug 2026. The training claim is unchanged and
explicit — "Google uses the content you submit… to provide, improve, and develop
Google products," human reviewers "may read, annotate, and process your API input
and output," and "Do not submit sensitive, confidential, or personal information
to the Unpaid Services." **Non-negotiable 3 in `CLAUDE.md` is correctly
grounded.** Current line is `gemini-3.7-flash` down to `gemini-2.5-flash-lite`;
`gemini-2.0-flash` and `-lite` are shut down.

**DeepSeek: the blueprint is right on every price digit, with three
corrections.** Model names, the 24 Jul 2026 retirement of `deepseek-chat` and
`deepseek-reasoner`, $0.22/$0.66 off-peak, $0.44/$1.32 peak, $0.007/M cache-hit,
1M context, 384K output, and the 01:00–04:00 / 06:00–10:00 UTC windows are all
confirmed verbatim. Corrections:

1. **Peak hours are Monday through Friday only.** The pricing page says so
   verbatim. Weekends are entirely off-peak. The blueprint omits this, and so does
   the code — see below.
2. Pro is 3× Flash on cache-miss input and output, but 3.14× on cache-hit input
   ($0.007 → $0.022).
3. The blueprint's caveat that DeepSeek "signaled further price changes without
   publishing rates or dates" is **stale and should be deleted** — that was the
   6 Aug warning, resolved by the 13 Aug announcement and the 16 Aug effective
   date. The newest changelog entry (21 Aug) contains no pricing content.
4. A third model shipped 21 Aug 2026, two days before the blueprint:
   `deepseek-v4-flash-vision-exp`, multimodal at Flash rates. Missing from the
   blueprint entirely.

**Confirmed unchanged and correct:** OpenRouter (50/day free, $10 for 1,000/day,
20 RPM, `openrouter/free` live with its own model page, zero free DeepSeek or
Gemini variants), Oracle Cloud Always Free (2 OCPU/12GB A1, 1,500 OCPU-hrs +
9,000 GB-hrs, 200GB storage, 10TB egress, 18 Aug enforcement passed — and
over-limit instances are auto-terminated, which makes the "provision at exactly
2/12" advice load-bearing), and Mem0/Graphiti (Mem0 Apache-2.0 and actively
released; Zep's self-hosted CE retired Apr 2025; Graphiti standalone,
Apache-2.0, no Zep Cloud requirement).

One incidental: `z-ai/glm-5.2:free` is on OpenRouter's current free roster. If
GLM access was the reason Cerebras sat at rung 2, OpenRouter now carries a much
newer GLM for free, on an account that already works.

**Cowork and Cloud Routines: both exist, but they are two different things and
the blueprint conflates them.** HTTP triggering is real, so Phase 4's design is
viable — but the mechanism is a Claude Code **routine**
(`POST /v1/claude_code/routines/{id}/fire`), not a Cowork scheduled task. Cowork
scheduled tasks do run in Anthropic's cloud as claimed, but have no documented
HTTP trigger; cron cadence only. Six caveats before Phase 4 leans on this: it is
a research preview behind a beta header, the id is prefixed `trig_` not
`routine_`, token generation and revocation are UI-only with no programmatic
rotation, the payload arrives wrapped in an untrusted `<routine-fire-payload>`
block the routine must opt into acting on, there is **no idempotency key** so a
retrying webhook creates duplicate sessions, and it requires claude.ai
subscription login — Console API keys, Bedrock, Vertex and Foundry auth are all
rejected, and it is in no Anthropic SDK.

### The real rung count: four

The blueprint presents 8 rungs as live capacity. `providers.yaml` configures 9.
Actually routable today:

| # | Provider | Routable | Why |
|---|---|---|---|
| 1 | Groq | **Yes** | Working, header capture proven |
| 2 | Cerebras | No | Free tier abolished 17 Aug; 402 without a card |
| 3 | NVIDIA NIM | No | Geo-blocked at signup; no key, so `_configured()` filters it |
| 4 | Gemini | **Yes** | Working |
| 5 | OpenRouter | **Yes** | Working via `openrouter/free` |
| 6 | Mistral | No | 403 on chat |
| 7 | DeepSeek | **Yes (paid)** | Working; gated off during peak for non-urgent |
| 8 | Claude Max | No | `not_a_router_target: true` |
| 9 | Claude API | No | `emergency_only`, and `ANTHROPIC_API_KEY` is absent from `state.md`'s confirmed-present list |

**Four routable — three free plus one paid. Three during DeepSeek peak windows.**

### Three router defects this exposes

**1. A Cerebras 402 aborts the whole chain, permanently, with no cooldown.**
`routing.py:227` falls through only on 429 and 5xx. A 402 is neither, so it
reaches the bare `raise` at `:238`. Unlike Mistral, **no cooldown is recorded**,
so it recurs on every subsequent request forever. For a `batch` profile the order
is Groq(1) → Cerebras(2) → OpenRouter(5) → Mistral(6) → DeepSeek(7): any batch
job that sees Groq 429 dies at Cerebras and never reaches OpenRouter or DeepSeek.
This is the one genuine defect of the three.

**2. Mistral's 403 also aborts the chain — but deliberately.** `routing.py:236`
records a cooldown and then re-raises, and the comment above it states the
reasoning: "surface the denial to the caller rather than silently moving the
request to another (possibly paid) provider." That is a decision, not a bug. Its
consequence is still worth surfacing: one request per 60-second cooldown window
fails outright at priority 6 instead of reaching the paid overflow valve at 7. If
that trade is no longer wanted, changing it is a decision to make, not a fix to
apply.

**3. The DeepSeek off-peak gate has no weekday check.**
`routing.py:19` is `PEAK_DEEPSEEK_WINDOWS_UTC = ((1, 4), (6, 10))` and
`_deepseek_allowed` at `:286-287` tests only
`self._now().astimezone(UTC).hour`. DeepSeek's published peak window is Monday
through Friday. So every Saturday and Sunday the router refuses non-urgent
DeepSeek work during seven hours that are actually off-peak — the cheapest hours
of the week.

### Stale model IDs

`providers.yaml` hardcodes exactly two model strings, and **both are current**:
`openrouter/free` (`:40`) and `deepseek-v4-flash` (`:58`). Everything else defers
to environment variables, none of which are in `.env.example` — so **the repo
cannot tell you what models it is actually calling.**

**The highest-value follow-up in this audit is one command.** If
`GROQ_DEFAULT_MODEL` in `.env` is set to `llama-3.1-8b-instant` — the model the
blueprint names as Groq's headline lane, retired 16 Aug — then Groq is dead too
and the routable count is three, not four. That is a Class A check the owning
session can run.

Blueprint prose IDs: `llama-3.1-8b-instant` **retired**; `GLM-4.7` on Cerebras
**never served**; `deepseek-chat` and `deepseek-reasoner` **retired** (blueprint
correct); `magistral-small` and `open-mistral-nemo` **retired**;
`mistral-small-latest` unverifiable. Current: `openai/gpt-oss-120b`/`-20b`,
`whisper-large-v3-turbo`, `gpt-oss-120b` on Cerebras, `openrouter/free`,
`deepseek-v4-flash`, `deepseek-v4-pro`. Gemini Flash is current but the
blueprint's generation is five behind. DeepSeek V4 on NIM is contested —
NVIDIA's catalogue lists it, its own forum reports EOL on 7 Aug 2026 — and moot,
since NIM is unreachable from Pakistan either way.

---

## 3. Proposed blueprint adjustments

**All Class C. Proposed, not applied.** The blueprint is a decisions document;
architecture, component choices, dependency selection and phase ordering are not
mine to change. Each item is reasoning plus a proposal, and each needs a yes or
no.

### 3.1 Phase 1's acceptance criterion cannot be tested as written

"You tell it something on Monday and it uses it unprompted on Thursday" makes
three claims: cross-process persistence, unprompted use, and a real corpus behind
it. The one live test makes none of them.

**Propose:** keep the sentence as the human criterion, and add two mechanised
ones beneath it.

1. A live probe that writes a turn through `memory/conversation.py`, exits the
   process, and recalls it from the persisted `memory.db` in a new process.
2. A live end-to-end that pushes a real webhook payload through the real handler
   with only the Graph API send faked, asserting the reply reflects an earlier
   fact.

The second is the replay harness from section 2, which pays for itself twice.

### 3.2 The Mem0 commitment needs an amendment or a re-decision

The blueprint chose Mem0 for consolidation, dedup and contradiction resolution.
On this hardware that layer runs at roughly 25 messages per hour when idle and
zero under live traffic, can terminate permanently after three failures, and is
unobservable. Raw-turn recall carries the product instead. That is a real
architectural change, and it is currently recorded only as a trade-off being
*considered* — `docs/scalability-review.md:96`, "Partly met."

Three ways out, and the choice is the user's:

1. **Accept it.** Declare raw-turn recall the Phase 1 product, demote Mem0 to
   opportunistic compaction, and write that into the blueprint. Cheapest, and
   honest. Cost: recall returns contradictory turns and nothing reconciles them.
2. **Move extraction off-box.** Collides head-on with non-negotiable 3 —
   loopback-only, fail closed, no hosted fallback. Amending a non-negotiable is
   the most Class C thing in this document.
3. **Change the extraction model.** `phase1.md:170-175` records `qwen3:4b` at
   0/10 schema-valid, which is why `llama3.1:8b` was chosen. The space between 4B
   and 8B was never searched.

**Propose option 1**, with a named threshold at which option 3 gets revisited.
Whatever is chosen, the blueprint should stop implying Mem0 is doing work it is
not.

### 3.3 State the routing chain as 9 rungs, with live status delegated

The blueprint presents 8 rungs as capacity. The code has 9. **Four are routable
today** — Groq, Gemini, OpenRouter and paid DeepSeek — and three during DeepSeek
peak windows. A reader budgeting free-tier headroom from the blueprint is reading
fiction, and two of the dead rungs (Cerebras, NIM) are dead for reasons the
blueprint itself now gets wrong.

**Propose:** the blueprint carries the ladder as a decision — which providers, in
what order, why — and delegates live/dead status to `state.md`'s "Provider rungs"
table, which already tracks it accurately. Add Mistral to the numbered chain,
since the code has it there. Reconcile the NIM contradiction: the blueprint lists
NIM as rung 3 and free DeepSeek-class capacity in two places, while its own §1.3
amendment in the same file says it is geo-blocked from Pakistan.

Two further decisions this raises, both yours:

- **Whether Cerebras stays at rung 2.** Its free tier no longer exists; reaching
  it requires a card. Leaving a rung that always 402s at priority 2 is what makes
  defect 1 in section 2b bite.
- **Whether Mistral's deliberate raise-on-403 is still the right trade.** The
  code chose to surface the denial rather than silently spend money at the next
  rung. That was a sound call when Mistral was expected to work. It now means one
  request per cooldown window fails outright.

### 3.4 Specify the cooldown ledger's lifetime

Blueprint 0.6 says "a cooldown ledger so a limited provider gets skipped instead
of hammered" without saying across what scope. The per-call construction today is
a defensible reading of an underspecified sentence.

**Propose:** specify process-lifetime. That turns `routing.py:372-376` from an
interpretation into a defect with an obvious fix, and makes `/status`'s provider
health meaningful for the first time — though only if the executor, not the bus,
is the process reporting it.

### 3.5 Give the monthly facts-check job a phase and an owner, or delete it

It is the blueprint's only defence against its own rot, it is the mechanism that
would have caught the promo expiry, and it does not exist. Leaving it in
"Ongoing" has produced nothing.

**Propose:** make it a numbered Phase 0 deliverable (0.8) so it is gated like
everything else, or cut it and accept that provider facts get re-verified
manually when something breaks.

### 3.6 Reorder Phase 2 behind its own inputs

The blueprint says "do the PyFLP proof-of-concept THIS WEEK alongside Phase 0."
That was followed, and produced a lane blocked on an interpreter and on two Class
C inputs — real `.flp` copies and the dictated mixer convention. Because the
convention does not exist, `apply_rules()` is written against a placeholder
ruleset and will likely be rewritten once it does.

**Propose:** keep the parallel start — the interpreter and the backup/verify work
were worth doing early — but move 2.1's two inputs ahead of 2.2 explicitly, so
the rules engine is not written twice. This is phase *ordering*, exactly the kind
of decision the rules say to stop and ask about.

### 3.7 Amend 1.3's extraction sentence

Replace "using constrained JSON-schema structured decoding" with what shipped:
Mem0's Ollama adapter with `json_object` response format, pydantic validation,
and one retry. Small, but 1.3 is the only place a reader would look.

### 3.8 Four factual corrections to the provider section

These are claims, not decisions, so they can be corrected rather than debated —
but they live in the blueprint, so the edit is still the user's.

- **Add "Monday through Friday" to the DeepSeek peak windows.** Weekends are
  entirely off-peak. The omission is currently mirrored as a live code bug
  (section 2b, defect 3).
- **Delete the "signaled further price changes without publishing rates or
  dates" caveat.** It described the 6 Aug warning, which the 13 Aug announcement
  and 16 Aug effective date resolved.
- **Correct Cerebras and Groq.** Cerebras's free tier was abolished 17 Aug 2026,
  six days before the blueprint called it confirmed, and it has never served GLM.
  Groq's `llama-3.1-8b-instant` was shut down 16 Aug 2026, seven days before.
- **Reconcile NIM.** Rung 3 and the §1.3 geo-block amendment contradict each
  other inside one file. Also drop "200 RPM raise can be requested" — NVIDIA
  staff stated on 11 May 2026 that no increase is available on that tier.

Both of the first two were wrong on the day the blueprint was written, which is
the strongest argument for 3.5.

---

## 4. What could not be determined

Each item names the single observation that would settle it.

- **Whether the distill chain is currently alive in the live queue, or already
  dead-lettered out of existence.** One query: rows where
  `kind = 'distill_memory'`, grouped by status. No `queued`/`running` row plus at
  least one `dead_letter` means no distillation has happened since it died.
  `/status` would answer it, but requires the bearer token from `.env`, which
  this audit did not read.
- **The real undistilled backlog size.** A count over `memory.db` of
  `source LIKE 'whatsapp:%'` with `distilled` unset. Querying `memory.db` was
  blocked, and it holds personal content — this is the user's to run.
- **Whether the orphaned `queue-durability-probe-` row still exists.** Same live
  queue query, filtered to that kind prefix.
- **Whether Phase 0's sleep/wake criterion has ever been met.** Send a message
  with the laptop asleep, wake it, watch the job reach `done`. Ten minutes, and
  it is the one Phase 0 criterion with no evidence behind it.
- **What `GROQ_DEFAULT_MODEL` is set to. This is the highest-value single check
  in the audit.** If it is `llama-3.1-8b-instant` — retired 16 Aug 2026 — then
  Groq is dead too and routable capacity is three rungs, not four. One `grep` of
  `.env` by the session that owns it settles it. The same check applies to
  `CEREBRAS_DEFAULT_MODEL`, `NVIDIA_DEFAULT_MODEL`, `GEMINI_DEFAULT_MODEL` and
  the two `CLAUDE_API_*` variables; none are in `.env.example`, so the repo
  cannot say what models it calls.
- **Whether the Claude weekly promo gets a fourth extension.** Nothing announced
  as of 27 Aug. Settles on or about 31 Aug, when Anthropic either updates article
  15910845 or lets it lapse.
- **Gemini's free-tier RPM/TPM/RPD per model.** Google removed the public table
  on or before 18 Aug 2026 and moved the numbers behind a login. Settles by
  reading response headers at runtime, which this project's rules already
  mandate. Third-party figures found during this audit contradicted each other
  and were not adopted.
- **The true cause of Mistral's 403.** Mistral's error glossary lists 403 with no
  explanation, causes, or remediation. One logged-in look at
  `admin.mistral.ai/plateforme/limits` settles it. The observed pattern —
  `/v1/models` works, chat 403s — is most consistent with a plan not activated on
  the workspace, but that is inference, not a sourced fact.
- **Whether DeepSeek V4 still answers on NIM**, and **DeepSeek's ~5M new-account
  free grant**, which appears in no DeepSeek-owned source. Both are moot for this
  project — NIM is unreachable from Pakistan regardless.
- **The numeric per-plan daily Cloud Routine run cap.** Login-gated at
  claude.ai/code/routines. Matters only when Phase 4 starts.
- **Whether the uncommitted `whatsapp.py` / `distill.py` / `logging.py` /
  `start_jarvis.py` edits were orchestrator-applied or lane overreach.** Only the
  diff is visible. A line in the relevant brief recording which would settle it.
- **Whether any Class B stop in the 17-hour broken-`consult.py` window was
  resolved without a consult.** No artifacts survive either way.
- **Whether the 27 Aug plaintext `hub_verify_token` in `tools/bus.out.log` means
  the token should be rotated.** Requires reading that log, which this audit did
  not do. It is a secret-handling decision regardless.
- **The tool-result-injection event itself.** H4, H5 and H6 remain open, and no
  artifact on the machine carries the text.
- **Whether the in-flight PyFLP lane reaches a working state.** It was editing
  the tree throughout this audit. The finding that `.venv311` on 3.11.9 cannot run
  PyFLP is reproduced and solid as of 17:22; the lane holds a verdict to install
  3.11.5 and may execute it at any moment.
- **Nothing here was verified by running the test suite.** Another session owns
  this tree and pytest writes scratch directories. Every "built" judgement is a
  code-reading judgement.
