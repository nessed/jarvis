# JARVIS project context

Last updated: 25 August 2026 — Phase 0 inbound acceptance passed; Phase 1's specified local Mem0 wrapper is implemented and focused-tested, while its live end-to-end probe remains incomplete; Meta outbound-token follow-up remains.

## Current state

The repository rules in `agents.md` make parallel, disjoint-file agent lanes
the default. Every completed subtask updates this handoff. `docs/blueprint.md`
is the architecture spec, but all fast-moving provider claims require current
verification before use.

Phase 1 is underway, local-first. The SQLite fact store, sqlite-vec semantic
index, loopback-only Ollama adapter, injected `remember()` / `recall()` service,
opt-in resumable ingestion foundation, and Mem0 wrapper are integrated. Ollama
0.32.15 and the local `nomic-embed-text` model are active on loopback.
`memory.db` and corpus inputs are ignored by Git. No personal notes, chats, or
external corpus have been read or ingested.

Phase 1 remains incomplete: although the blueprint-specified Mem0 self-host
wrapper is implemented, no inbound/outbound conversation path calls
recall-before or remember-after, no opted-in corpus has completed the
fact-extraction and backfill/review acceptance loop, and the live Mem0 probe
did not complete within its 30-second attempt.

Source checkpoints:

- `699c92d` — complete Phase 0 bus foundation.
- `c991f5e` — secure queue, live-provider verification, tests, context, and
  recoverable lane briefs.
- `f77d7af` — complete Phase 0 executor lifecycle and live queue status.
- The complete repository history is published to
  `https://github.com/nessed/jarvis` on `main`.

No credential, token, password, or database secret is committed or recorded in
this file. `.env` is ignored and `.env.example` has empty placeholders.

## Completed and verified

- FastAPI bus with HMAC-verified Meta webhooks, bearer-protected non-webhook
  routes, request-ID JSON logging, real protected `/status` queue metadata, and
  enqueue-only webhook behavior. The local bearer token is configured without
  recording its value.
- Supabase durable queue migration was applied successfully to the live target.
  `public.jobs` has RLS enabled with no public policies; public/anon/authenticated
  table and RPC access is revoked; queue RPCs are service-role-only.
- Queue client rejects publishable/anon credentials and requires
  `SUPABASE_SECRET_KEY` (or legacy `SUPABASE_SERVICE_ROLE_KEY`).
- Live queue proof passed: enqueue → atomic claim → checkpoint → complete, plus
  failure path. Publishable credentials remain rejected.
- Router verification:
  - Groq and Gemini minimal routed calls returned 200.
  - Direct DeepSeek (`deepseek-v4-flash`) returned 200 through
    `https://api.deepseek.com/v1`; OpenRouter proxy routing is disabled.
  - DeepSeek’s successful response had no rate-limit headers, so its live
    cooldown parsing is unexercised. Real successful-header capture is proven
    with Groq; router unit tests cover the rest.
  - Cerebras authenticates but its chat calls currently return
    `402 payment_required`; do not route work there as a free fallback.
- Full suite: **26 passed**. Non-failing noise: Supabase SDK deprecation
  warnings and a pytest-cache filesystem warning.

## Local runtime

The FastAPI bus and Cloudflare Quick Tunnel are running.

- Callback URL: `https://gas-clubs-pennsylvania-farming.trycloudflare.com/webhook`
- The external protected health route returned 401 after the fresh tunnel was
  registered, confirming reachability and bearer protection.
- This is a Quick Tunnel. Its URL dies when cloudflared or the laptop stops;
  Meta must be updated after each restart until a named tunnel or Phase 4 Oracle
  deployment replaces it.

## Local configuration presence

Confirmed present without reading values: Groq, Cerebras, Gemini, Supabase URL,
Supabase publishable key, Supabase Secret key, DeepSeek direct key, Meta verify
token, Meta Phone Number ID, Meta App ID, and bus bearer token. DeepSeek proxy
mode is false/unset.

OpenRouter, Mistral, and Meta App Secret are now configured locally. NVIDIA
NIM is explicitly deferred and must not block Phase 0. Meta’s durable access
token is also now configured locally.

## Phase 1 Ollama readiness

- **Activated 25 August 2026:** Ollama 0.32.15 is running on the loopback API;
  `nomic-embed-text` was pulled locally. `ollama list` confirmed its presence.
  A non-personal `POST /api/embed` dimension probe returned HTTP 200 with one
  768-dimensional vector, and `open_local_memory()` opened and closed cleanly.
  Focused memory tests: **31 passed in 0.60s**. The external Ollama/model
  blocker is resolved; no personal corpus has been ingested.
- Earlier installation/download diagnostics are obsolete: activation is now
  verified locally. System Python lacks pytest; use
  `.venv\\Scripts\\python.exe` for project checks.

- **25 August 2026 — Mem0 wrapper:** The authorized custom SQLiteVec Mem0
  provider delegates to the existing SQLite fact store and sqlite-vec index.
  The required synthetic non-personal model comparison produced
  schema-conforming output for `qwen3:4b` in **10/10** cases and
  `llama3.1:8b` in **10/10** cases. The user selected `llama3.1:8b` as the
  default extraction model. Default/override focused verification command and
  exact output: `.venv\\Scripts\\python.exe -m pytest -q tests\\memory` ->
  `40 passed in 3.40s`.
  Raw local JSON diagnosis found `qwen3:4b` timed out at **20,094ms**, while
  `llama3.1:8b` succeeded at **17,395ms**. The Mem0 wrapper now uses
  `OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS` (default `30`) and fails closed on
  timeout.
- **25 August 2026 — live Mem0 Qwen smoke (failed):** The full-Mem0 generic
  probe ran with:
  `$env:OLLAMA_EMBEDDING_MODEL='nomic-embed-text'; $env:OLLAMA_FACT_EXTRACTION_MODEL='qwen3:4b'; $env:OLLAMA_BASE_URL='http://127.0.0.1:11434'; $env:OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS='20'; .venv\\Scripts\\python.exe -c "from memory.runtime import open_local_mem0_memory; runtime=open_local_mem0_memory('memory\\diagnosis-qwen-timeout.db'); print('OPENED'); runtime.remember('The generic workshop opens at nine.'); print('REMEMBERED'); runtime.close()"`
  Exact initial warning output was:
  `The 'sqlite_vec' vector store does not support keyword search. Hybrid (BM25) scoring will be disabled and search will use semantic similarity only. To enable hybrid search, switch to a store with keyword_search support (e.g. qdrant, elasticsearch, pgvector).`
  Exact error: `LLM extraction failed: Local Ollama fact extraction timed out. Confirm the configured local model can complete extraction.`
  Exact exception-chain endpoint:
  `mem0.exceptions.LLMError: LLM extraction failed: Local Ollama fact extraction timed out. Confirm the configured local model can complete extraction.`
  The earlier `mem0-live-probe.db` and its SQLite sidecars were deleted after
  their result was documented. Temporary diagnosis databases
  `memory\\diagnosis-open.db`, `memory\\diagnosis-open.mem0-history.db`,
  `memory\\diagnosis-qwen-timeout.db`, and
  `memory\\diagnosis-qwen-timeout.mem0-history.db` were deleted after this
  entry was written. No user corpus was read or ingested.
- **25 August 2026 — default Llama isolated smoke (failed):** With no
  `OLLAMA_FACT_EXTRACTION_MODEL` supplied, this command used the default
  `llama3.1:8b` and an explicit 20-second local timeout:
  `.venv\\Scripts\\python.exe -c "from memory.runtime import open_local_mem0_memory; env = {'OLLAMA_EMBEDDING_MODEL': 'nomic-embed-text', 'OLLAMA_BASE_URL': 'http://127.0.0.1:11434', 'OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS': '20'}; runtime = open_local_mem0_memory(r'memory\\llama-default-smoke-retry.db', environ=env); print('OPENED'); remembered = runtime.remember('The generic workshop opens at nine.'); print('REMEMBERED', remembered); recalled = runtime.recall('When does the generic workshop open?'); print('RECALLED', recalled); runtime.close(); print('CLOSED')"`
  It failed with `LLM extraction failed: Local Ollama fact extraction timed out. Confirm the configured local model can complete extraction.`, ending
  `mem0.exceptions.LLMError: LLM extraction failed: Local Ollama fact extraction timed out. Confirm the configured local model can complete extraction.`
  An earlier default-30 attempt was stopped by the shell at approximately
  30.6 seconds before it produced an error. The temporary files
  `memory/llama-default-smoke.db`,
  `memory/llama-default-smoke.mem0-history.db`,
  `memory/llama-default-smoke-retry.db`,
  `memory/llama-default-smoke-retry.mem0-history.db`,
  `memory/llama-default-smoke-output.txt`, and
  `memory/llama-default-smoke-error.txt` were deleted after this entry was
  written.
- **25 August 2026 — async-memory plan blocked:** Inspection found that
  `db.jobs` can enqueue arbitrary kind/payload, but executor startup supplies
  no registered handlers, so `memory_extract` would fail as unknown. The queue
  also has no retry/requeue lifecycle, attempts/backoff, or worker timeout.
  Under the same ownership and no-invented-contract rule, cold/warm timing,
  cap changes, fair comparison, and an async smoke were not started. External
  queue/executor work is required: registered handler startup wiring, retry
  lifecycle, and a 300-second worker timeout.
- **25 August 2026 — Mem0 measurement blocked:** The queue remains out of
  scope and no code changed. The real Mem0 system prompt measured 33,653
  characters / 5,062 whitespace words, plus 225 characters of generic text.
  The measurement environment used `OLLAMA_KEEP_ALIVE=-1` and request
  `keep_alive=-1`; caps were `num_predict=128` (one-fact JSON; avoids the
  2,000 default) and `num_ctx=16384` (8,192 might truncate this prompt).
  After `ollama stop llama3.1:8b`, cold full-prompt Llama timed out exactly at
  300.018 seconds:
  `{"label":"cold","elapsed_seconds":300.018,"error_type":"ReadTimeout","error":"timed out","num_ctx":16384,"num_predict":128}`.
  It returned no Ollama timing fields, so no load/inference split is available.
  The warm run queued behind abandoned inference was invalid and stopped.
  The ten-run comparison and default selection were not performed; no winner
  was declared.

## Phase 1 offline foundations

- The local-only resumable backfill runner is complete. It accepts only a
  caller-selected, manifest-verified source, persists through an injected
  sink, and advances its serializable checkpoint only after a successful write.
  It supports resume and rejects mismatched, negative, or out-of-bounds
  checkpoints. Focused ingestion tests: **11 passed**.
- The executor now dispatches registered job kinds through an injected seam.
  Unknown kinds fail deterministically with type-only safe diagnostics and no
  payload/provider leakage. Focused executor tests: **9 passed**.
- The local-memory runtime lane is complete: startup performs its fixed,
  non-personal dimension probe before constructing stores, handles explicit
  environment configuration, and closes resources on partial initialization
  failure. Offline focused memory tests: **31 passed**.
- These foundations and the Mem0 wrapper make the local embedding runtime
  active, but do not satisfy the remaining conversation-wiring or opted-in
  backfill/extraction-review requirements.
- Offline integration validation passed on 25 August 2026:
  `.venv\\Scripts\\python.exe -m pytest -q --ignore=tests/db/test_jobs_integration.py`
  completed **82 passed in 3.46s**. The excluded file is credential/live-
  Supabase dependent. An earlier broad run reached that test but failed before
  connecting with `WinError 10013`; it made no external change.

OpenRouter live smoke testing passed through `openrouter/free`. Its successful
response had no retry/rate-limit headers, so runtime cooldown capture correctly
remained empty. Mistral model discovery succeeded, but a minimal free Labs chat
request returned 403; treat Mistral as unavailable pending account/workspace
resolution. Its configured router rung is present; it cannot accept work until
the provider-side denial is resolved.

The Mistral router integration is now complete. It uses the official
`https://api.mistral.ai/v1` endpoint ahead of paid DeepSeek, honors an explicit
`MISTRAL_DEFAULT_MODEL` when present, and otherwise dynamically discovers the
key’s unarchived chat-capable models through `/v1/models`; no free model ID is
hardcoded. Current Mistral 401/403 responses put the provider in cooldown and
surface the denial rather than silently falling through to paid work. Focused
router tests: **15 passed**. The live Mistral workspace 403 still needs account
resolution before that rung is usable.

Full suite after the Mistral integration: **30 passed**. The final regression
run after tunnel recovery and executor/status integration passed: **38 passed,
3 warnings**. The only non-failing noise remains the two Supabase SDK
deprecations and pytest-cache filesystem warning.

- Pull-based Phase 0 executor is implemented and running locally. It atomically
  claims one job, checkpoints it, then completes it; transient repository errors
  are retried with type-only diagnostics. A live disposable probe completed
  queued → running → done on 24 August 2026.

## Meta state

- One WhatsApp app: **WA 1st**, in development. Its test recipient allow-list
  already contains the user’s Pakistani number; do not re-verify it.
- Existing system user **whatsapp-bot** is Admin and already has full access to
  the WA 1st app and test WABA. Do not create another system user or reassign
  assets.
- The active callback is the current Quick Tunnel `/webhook` endpoint; Meta
  save and the closed-lid inbound acceptance have passed. `messages` remains
  subscribed. Quick Tunnel URLs still change on restart, so switch to a named
  tunnel or Phase 4 Oracle deployment before relying on a stable callback.
- Meta’s App Secret and durable system-user token are now present locally.
  The Meta configuration form still fails to load in browser automation. A
  browser-control extension emitted an internal ad-blocker-module error, but
  this is not evidence that the user has an ad blocker installed; do not ask the
  user to disable or whitelist any extension. The tunnel and Meta app state are
  not implicated by the available diagnostics. A clean retry after token setup
  still returned only Meta’s 832-character application shell after nine seconds
  and exposed no callback/verify fields, so this is a reproducible browser-side
  rendering failure rather than a navigation mistake. The in-app browser is not
  available in this session, so there is no alternate authenticated browser
  surface for recovery.
- A read-only Graph API check using the stored Meta access token returned OAuth
  error 190. Treat that token as invalid until it is regenerated and smoke-tested;
  its value is not recorded here. This does not prevent inbound webhook HMAC
  validation, but it blocks future Graph API sends.
- In Meta's redesigned dashboard, use **Use cases** → **Settings** →
  **Configurations** → the WhatsApp card's **Connect** → **Basic setup** →
  **Step 2. Production setup** → **Configure Webhooks**. The traditional layout
  calls the same area **WhatsApp** → **Configuration**. The callback card now
  renders in the signed-in Chrome session.
- The app is unpublished: dashboard test events work, but production data will
  not be delivered until publication.

## Immediate user handoff

No inbound acceptance action remains. Before implementing outbound Graph API
calls, regenerate and smoke-test the invalid Meta system-user token noted above.

## Acceptance evidence

- With the laptop closed, a phone-originated WhatsApp message arrived after
  wake and created durable `whatsapp_webhook` jobs that reached `done` with
  executor checkpoints on 24 August 2026.
- Unsigned local POST to `/webhook` returned 403 on 24 August 2026.
- The executor's independent live lifecycle probe also passed.
