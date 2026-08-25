# JARVIS project context

Last updated: 26 August 2026 — reconciled. Two parallel lanes landed and
committed in `8fb271f` (queue durability: attempts/backoff/timeout/dead-letter
mechanism; and the Mem0 self-host wrapper baseline). A third change — the
Mem0 300s-extraction-timeout root-cause fix — is complete but **uncommitted**
on top of that. This pass collapses superseded diagnostic entries (failed
Qwen/Llama timeout attempts, the invalid first model comparison, the blocked
async-memory plan) into short historical notes; their full text is still in
git history (see `3256779`, `8fb271f`) if needed. Current blockers below
reflect actual git/tree state, not each intermediate attempt.

## Current state

The repository rules in `agents.md` make parallel, disjoint-file agent lanes
the default. Every completed subtask updates this handoff. `docs/blueprint.md`
is the architecture spec, but all fast-moving provider claims require current
verification before use. `docs/workflow_overview.md` and
`docs/workflow_review_prompt.md` (25 August 2026) separately describe *how*
work gets done on this repo (process, not architecture or build state) and
feed an external process-improvement review — not maintained here.

Phase 0 (bus + durable queue + executor + router) is complete and verified.
Phase 1 (local-first memory) is underway. The SQLite fact store, sqlite-vec
semantic index, loopback-only Ollama adapter, injected `remember()`/`recall()`
service, opt-in resumable ingestion foundation, and the self-hosted Mem0
wrapper are all implemented and committed. Ollama 0.32.15 and local
`nomic-embed-text` are active on loopback. `memory.db` and corpus inputs are
git-ignored. No personal notes, chats, or external corpus have been read or
ingested.

Phase 1's concrete remaining gaps:

1. **No conversation wiring.** No inbound/outbound path calls `recall()`
   before or `remember()` after a model call. `executor/poller.py`'s
   `DEFAULT_HANDLERS` is deliberately empty — `memory_extract` (or any kind)
   is not registered to a handler. Building the mechanism and wiring
   `memory_extract` into it are separate, not-yet-authorized steps.
2. **No opted-in backfill.** `ingest/` remains empty by design; no corpus has
   completed the fact-extraction + backfill/review acceptance loop.
3. **Queue durability mechanism is built and tested, not live.**
   `db/migrations/0002_job_retries.sql` (attempts/max_attempts/timeout_seconds
   columns, `retry_or_dead_letter_job`/`set_job_timeout` RPCs) has not been
   applied to the live Supabase project — this venv has no Postgres driver or
   Supabase/psql CLI to apply it, and adding one means touching
   `requirements.txt`, outside that lane's ownership. `bus/status.py` gained
   an optional `retry_health()` reader, but it is not yet wired into the real
   `/status` route in `bus/main.py`.
4. **Mem0's extraction-timeout fix is uncommitted.** The compact-prompt fix
   (below) changes `memory/mem0_wrapper.py` and
   `tests/memory/test_mem0_wrapper.py` and is only verified via raw `ollama`
   client calls replicating the real extraction call — it has not yet been
   smoke-tested end-to-end through `open_local_mem0_memory()` / `remember()`.
5. **Meta's stored access token is invalid.** A read-only Graph API check
   returned OAuth error 190 as of 25 August 2026; outbound Graph API sends
   are blocked until it is regenerated and smoke-tested.

Source checkpoints:

- `699c92d` — complete Phase 0 bus foundation.
- `c991f5e` — secure queue, live-provider verification, tests, context, and
  recoverable lane briefs.
- `f77d7af` — complete Phase 0 executor lifecycle and live queue status.
- `4700407` — add local-first persistent memory foundations.
- `3256779` — reconcile Phase 1 context (superseded by this entry).
- `8fb271f` (current `HEAD`) — lands, together and committed: the queue
  durability mechanism (`db/migrations/0002_job_retries.sql`,
  `executor/poller.py` handler registry + backoff + timeout,
  `bus/status.py` `retry_health()`), the full Mem0 self-host wrapper baseline
  (`memory/mem0_wrapper.py`, pinned `mem0ai==2.0.19` + `ollama==0.6.2` in
  `requirements.txt`), and the blueprint 1.3 amendment (local Ollama +
  structured decoding replaces the original NIM/Gemini fact-extraction
  routing — NIM is geo-blocked from Pakistan, Gemini's free tier may train on
  prompts).
- The complete repository history is published to
  `https://github.com/nessed/jarvis` on `main`. `HEAD` (`8fb271f`) is pushed;
  the Mem0 timeout fix described below is a local, uncommitted change on top
  of it.

No credential, token, password, or database secret is committed or recorded in
this file. `.env` is ignored and `.env.example` has empty placeholders.

## Completed and verified

- FastAPI bus with HMAC-verified Meta webhooks, bearer-protected non-webhook
  routes, request-ID JSON logging, real protected `/status` queue metadata, and
  enqueue-only webhook behavior. The local bearer token is configured without
  recording its value.
- Supabase durable queue migration (`0001`) was applied successfully to the
  live target. `public.jobs` has RLS enabled with no public policies;
  public/anon/authenticated table and RPC access is revoked; queue RPCs are
  service-role-only. Migration `0002` (retry/backoff/dead-letter columns and
  RPCs, see below) is written and tested but not yet applied live.
- Queue client rejects publishable/anon credentials and requires
  `SUPABASE_SECRET_KEY` (or legacy `SUPABASE_SERVICE_ROLE_KEY`).
- Live queue proof passed: enqueue → atomic claim → checkpoint → complete, plus
  failure path. Publishable credentials remain rejected.
- Router verification:
  - Groq and Gemini minimal routed calls returned 200.
  - Direct DeepSeek (`deepseek-v4-flash`) returned 200 through
    `https://api.deepseek.com/v1`; OpenRouter proxy routing is disabled.
  - DeepSeek's successful response had no rate-limit headers, so its live
    cooldown parsing is unexercised. Real successful-header capture is proven
    with Groq; router unit tests cover the rest.
  - Cerebras authenticates but its chat calls currently return
    `402 payment_required`; do not route work there as a free fallback.
  - OpenRouter live smoke testing passed through `openrouter/free`; no
    retry/rate-limit headers, so cooldown capture correctly stayed empty.
  - Mistral model discovery succeeds and the router is fully integrated
    (official `https://api.mistral.ai/v1` endpoint ahead of paid DeepSeek,
    dynamic model discovery via `/v1/models`, no hardcoded free model ID,
    401/403 puts it in cooldown rather than silently falling through), but a
    live chat request still returns 403 — account/workspace resolution is
    still needed before that rung is usable.

## Queue durability — attempts, backoff, dead-letter (landed & committed, 8fb271f)

Built and tested; **not yet live**. Full design in
`docs/tasks/queue_durability.md`, handoff detail in
`docs/handoff/queue_durability.md`.

- **Handler registry at startup.** `executor/poller.py` adds
  `HandlerRegistration(handler, timeout_seconds)` and `DEFAULT_HANDLERS`
  (empty by design — no kind is registered yet), built once in `main()` and
  passed to every `poll_once` call. An unregistered kind raises before any
  checkpoint/dispatch, logs at `WARNING` with only the job id, and is routed
  through the same retry/backoff/dead-letter path as any other failure — it
  never crashes the poll loop.
- **Schema** (`db/migrations/0002_job_retries.sql`, additive only): adds
  `attempts`, `max_attempts` (default 5, overridable via
  `enqueue(..., max_attempts=...)`), `timeout_seconds` (default 300), and a
  `dead_letter` status. New RPCs `retry_or_dead_letter_job` and
  `set_job_timeout`.
- **Backoff:** `backoff_seconds(attempts) = min(300, 5 * 2**(attempts-1))` —
  base 5s, cap 5 minutes.
- **Per-job timeout:** the handler runs on a daemon `threading.Thread`; on
  timeout the poller retries immediately without waiting for the orphaned
  thread. The claimed row's `timeout_seconds` is pushed from the registry
  right after claim, so the DB's own stale-lease check uses the real per-kind
  value.
- **Crash-mid-run recovery:** `claim_next_job` also reclaims a `running` row
  whose lease (`updated_at + timeout_seconds`) has expired, and dead-letters
  it instead if `max_attempts` is already exhausted — this is what actually
  recovers a job when the whole executor process dies, not just a hung
  handler.
- **Atomic single-claim semantics preserved:** same single-statement
  `for update skip locked` shape, wider `WHERE`. Proven with an in-memory
  16-thread/8-job lock-based test (always runs) and a live-Supabase-gated
  integration test (skips until `0002` is applied).
- **`/status` gains `retry_health()`** (`{"dead_letter_count", "retried_job_count"}`)
  as an optional, default-`None` dependency on `bus/status.py`'s
  `status_payload`/`create_status_handler` — every existing call is
  byte-identical unless a caller opts in.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/executor tests/db` →
  **31 passed, 1 skipped** (the skip is the live-concurrency integration test,
  self-skipping because `0002` isn't applied live yet).

What is needed:

1. Apply `db/migrations/0002_job_retries.sql` to the live Supabase project
   (needs a Postgres driver or Supabase/psql CLI not currently in the venv —
   requires a `requirements.txt` change plus an explicit live-schema-write
   authorization, neither of which this lane could do on its own).
2. Wire `retry_health=` into the actual `/status` route in `bus/main.py`
   (same pattern as the existing `queue_depths`/`last_job` wiring).
3. Register `memory_extract` (and any other real kind) in
   `DEFAULT_HANDLERS` — deliberately left undone; this lane built mechanism
   only.
4. One orphaned probe row (`kind` prefixed `queue-durability-probe-`, status
   `running`) remains in the live `jobs` table from an early version of a
   test's schema-readiness probe, before it had a cleanup-on-failure path.
   Harmless (unique disposable kind), not manually swept.

## Phase 1 — Mem0 wrapper and extraction-timeout fix

The authorized custom `SQLiteVecMem0Store` (delegating to the existing SQLite
fact store and sqlite-vec index, no Qdrant/Chroma/FAISS substitution) is
implemented in `memory/mem0_wrapper.py` and committed in `8fb271f`, including
the validating-retry wrapper around Mem0's Ollama adapter (one retry on
schema-validation failure, then a clear `Mem0WrapperError`) and a bounded
`OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS` (default 30) that fails closed.

**Superseded diagnostic history (25 August 2026, before root cause was
found):** an early synthetic (non-personal, 10-sentence) comparison found
`qwen3:4b` and `llama3.1:8b` both schema-conforming 10/10 and picked
`llama3.1:8b` on raw-JSON latency (17.4s vs. Qwen's 20.1s timeout); a full
live-Mem0 smoke with real extraction then timed out for both models
regardless of choice; an async-memory dispatch was blocked pending the
queue/executor lane (now landed, see above); and a real-prompt cold-run
measurement confirmed the extraction call itself timed out at exactly 300.018s
with `num_ctx=16384`. All of these conclusions are superseded by the root
cause below; full exact commands/output are preserved in git history at
`3256779` if needed.

**Root cause (confirmed against installed mem0ai 2.0.19 source, not docs):**
`Memory.add`/`AsyncMemory.add` (`mem0/memory/main.py:942` and `:2604`) hardcode
`system_prompt = ADDITIVE_EXTRACTION_PROMPT` — a 33,653-character prompt — as
a bare module-global read inside the only LLM-extraction path in this version.
No supported config or argument selects a shorter prompt:
`mem0.memory.utils.get_fact_retrieval_messages`/`_legacy` and
`USER_MEMORY_EXTRACTION_PROMPT`/`FACT_RETRIEVAL_PROMPT` are unreferenced dead
code in `main.py`, and `MemoryConfig.version` is telemetry-only.
`mem0/llms/ollama.py`'s `OllamaLLM.generate_response` builds its Ollama
`options` from only `temperature`/`max_tokens`/`top_p` — `num_ctx` and
`keep_alive` are not reachable through Mem0's shipped Ollama adapter at all.
Literal "subclass Memory and override the system prompt" is not mechanically
available (the prompt is a local variable inside one ~250-line method, not an
overridable attribute) — reported rather than reimplementing Mem0's pipeline.

**Fix landed, uncommitted:** `memory/mem0_wrapper.py` now defines
`COMPACT_ADDITIVE_EXTRACTION_PROMPT` (2,419 characters, a 93% reduction) and
`_install_compact_extraction_prompt()`, called before `Memory` is constructed,
which reassigns the module global `mem0.memory.main.ADDITIVE_EXTRACTION_PROMPT`
at runtime — no site-packages edit, no LLM-adapter replacement, and the exact
`{"memory": [...]}` output contract the wrapper's `ExtractionResponse` model
requires is preserved (the shipped lighter prompts use an incompatible
`{"facts": [...]}` shape and were deliberately not used verbatim). A drift
guard (`_SHIPPED_PROMPT_MINIMUM_LENGTH = 20_000`) refuses to patch if a future
mem0ai upgrade already shrank the shipped prompt. `LlmConfig` now also sets
`max_tokens=128` (previously unset, defaulted to 2000).

**Re-measurement** (raw `ollama` client calls against the real compact system
prompt + the real `generate_additive_extraction_prompt` user prompt, since
Mem0's adapter can't accept `num_ctx`/`keep_alive` through any config): warm,
`keep_alive=-1`, `num_predict=128`, `num_ctx=2048` (sized from the actual
~2,677-character prompt, 8x smaller than the previous 16384) —
**5.998 seconds** (`prompt_eval_duration` 159ms for 636 prompt tokens,
`eval_duration` 5.82s for 38 generated tokens, CPU-only Ollama). This is well
under the ~15s gate, so the fair ten-run comparison ran with identical
prompt/caps for both models: **llama3.1:8b — 10/10 schema-valid, median
6.313s**; **qwen3:4b — 0/10 schema-valid, median 11.770s** (every run hit
`"done_reason":"length"` with its 128-token budget consumed by Qwen3's hidden
`thinking` output before any JSON content). `DEFAULT_FACT_EXTRACTION_MODEL`
stays `llama3.1:8b`, now confirmed by this fair comparison. Focused tests:
`.venv\Scripts\python.exe -m pytest -q tests\memory` → **44 passed**.

**Still needed:** commit this fix once a live end-to-end smoke through
`open_local_mem0_memory()` / `Mem0Memory.remember()` (not just raw `ollama`
calls) has been run and recorded here.

## Phase 1 offline foundations

- The local-only resumable backfill runner is complete. It accepts only a
  caller-selected, manifest-verified source, persists through an injected
  sink, and advances its serializable checkpoint only after a successful write.
  It supports resume and rejects mismatched, negative, or out-of-bounds
  checkpoints. Focused ingestion tests: **11 passed**.
- The executor dispatches registered job kinds through an injected seam.
  Unknown kinds fail deterministically with type-only safe diagnostics and no
  payload/provider leakage (now additionally routed through retry/backoff/
  dead-letter — see queue durability above). Focused executor tests: **9
  passed** pre-durability-lane; **31 passed, 1 skipped** for
  `tests/executor tests/db` combined after it landed.
- The local-memory runtime lane is complete: startup performs its fixed,
  non-personal dimension probe before constructing stores, handles explicit
  environment configuration, and closes resources on partial initialization
  failure. Offline focused memory tests: **31 passed** (pre-Mem0-wrapper
  baseline); **44 passed** with the Mem0 wrapper and timeout fix (see above).
- Offline integration validation passed on 25 August 2026:
  `.venv\\Scripts\\python.exe -m pytest -q --ignore=tests/db/test_jobs_integration.py`
  completed **82 passed in 3.46s**. The excluded file is credential/live-
  Supabase dependent. An earlier broad run reached that test but failed before
  connecting with `WinError 10013`; it made no external change. That same test
  flaked once more during the queue-durability lane's combined run and passed
  on every isolated and subsequent rerun — a known characteristic of the live
  network dependency, not a regression.
- Pull-based Phase 0 executor is implemented and running locally. It atomically
  claims one job, checkpoints it, then completes it; transient repository errors
  are retried with type-only diagnostics. A live disposable probe completed
  queued → running → done on 24 August 2026.

## Local runtime

The FastAPI bus and Cloudflare Quick Tunnel were running as of 25 August 2026.

- Callback URL (as of 25 August): `https://gas-clubs-pennsylvania-farming.trycloudflare.com/webhook`
- The external protected health route returned 401 after that tunnel was
  registered, confirming reachability and bearer protection.
- This is a Quick Tunnel. Its URL dies when cloudflared or the laptop stops —
  **reverify before relying on it**, since it may already have rotated since
  25 August. Meta must be updated after each restart until a named tunnel or
  Phase 4 Oracle deployment replaces it.

## Local configuration presence

Confirmed present without reading values: Groq, Cerebras, Gemini, Supabase URL,
Supabase publishable key, Supabase Secret key, DeepSeek direct key, Meta verify
token, Meta Phone Number ID, Meta App ID, Meta App Secret, Meta's durable
system-user access token (currently invalid, see below), and bus bearer token.
DeepSeek proxy mode is false/unset. OpenRouter and Mistral keys are configured.
NVIDIA NIM is explicitly deferred (and, per the blueprint 1.3 amendment, no
longer part of the fact-extraction plan at all — it's geo-blocked from
Pakistan).

## Meta state

- One WhatsApp app: **WA 1st**, in development. Its test recipient allow-list
  already contains the user's Pakistani number; do not re-verify it.
- Existing system user **whatsapp-bot** is Admin and already has full access to
  the WA 1st app and test WABA. Do not create another system user or reassign
  assets.
- The active callback is the current Quick Tunnel `/webhook` endpoint; Meta
  save and the closed-lid inbound acceptance have passed. `messages` remains
  subscribed.
- A read-only Graph API check using the stored Meta access token returned OAuth
  error 190 as of 25 August 2026. Treat that token as invalid until it is
  regenerated and smoke-tested; its value is not recorded here. This does not
  prevent inbound webhook HMAC validation, but it blocks outbound Graph API
  sends.
- In Meta's redesigned dashboard: **Use cases** → **Settings** →
  **Configurations** → the WhatsApp card's **Connect** → **Basic setup** →
  **Step 2. Production setup** → **Configure Webhooks**. Traditional layout:
  **WhatsApp** → **Configuration**.
- The app is unpublished: dashboard test events work, but production data will
  not be delivered until publication.

## Immediate user handoff

Regenerate and smoke-test the invalid Meta system-user token before
implementing any outbound Graph API calls. No inbound-acceptance action
remains.

## Acceptance evidence

- With the laptop closed, a phone-originated WhatsApp message arrived after
  wake and created durable `whatsapp_webhook` jobs that reached `done` with
  executor checkpoints on 24 August 2026.
- Unsigned local POST to `/webhook` returned 403 on 24 August 2026.
- The executor's independent live lifecycle probe also passed.
