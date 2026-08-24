# JARVIS project context

Last updated: 25 August 2026 — Phase 0 inbound acceptance passed; Phase 1 Ollama installation is blocked before model download; Meta outbound-token follow-up remains.

## Current state

The repository rules in `agents.md` make parallel, disjoint-file agent lanes
the default. Every completed subtask updates this handoff. `docs/blueprint.md`
is the architecture spec, but all fast-moving provider claims require current
verification before use.

Phase 1 is underway, local-first. The SQLite fact store, sqlite-vec semantic
index, loopback-only Ollama adapter, injected `remember()` / `recall()` service,
and opt-in resumable ingestion foundation are integrated (`32 focused tests`).
`memory.db` and corpus inputs are ignored by Git. No personal notes, chats, or
external corpus have been read or ingested. Ollama installation is in progress;
memory remains dormant until a locally configured embedding model is available.

Ollama’s non-secret local settings now specify `nomic-embed-text`, the loopback
endpoint, and `memory.db`, but no local Ollama runtime or model is present yet.

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

- On 25 August 2026, checks found no `ollama` command, Windows service, local
  process, loopback listener on port 11434, or reachable `/api/tags` endpoint.
- Windows Package Manager attempts to install the official `Ollama.Ollama`
  package (including silent mode) reported the official installer download but
  did not leave an installed package. An explicit `winget download` attempt
  likewise left no installer file. Treat the local installation/download path
  as blocked, not as a successful partial installation.
- Required recovery action: complete a trusted official Ollama Windows install
  and pull exactly `nomic-embed-text`; then verify `ollama list` and a local
  `POST /api/embed` response before opening the memory runtime. This needs a
  working network/download path but no credentials, login, or personal data.
- Focused memory tests passed independently in the project virtual environment:
  **27 passed** on 25 August 2026. System Python lacks pytest; use
  `.venv\\Scripts\\python.exe` for these checks.

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
- These offline foundations do not make memory active. Ollama itself and the
  `nomic-embed-text` model are still the external local-install blocker before
  a real local embedding/API smoke test or corpus backfill can begin.
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
