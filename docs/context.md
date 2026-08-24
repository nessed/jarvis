# JARVIS project context

Last updated: 24 August 2026 — Phase 0 active, pending replacement Meta callback Save and final phone acceptance.

## Current state

The repository rules in `agents.md` make parallel, disjoint-file agent lanes
the default. Every completed subtask updates this handoff. `docs/blueprint.md`
is the architecture spec, but all fast-moving provider claims require current
verification before use.

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

- Callback URL: `https://iii-loose-ventures-flow.trycloudflare.com/webhook`
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
- The prior Meta callback configuration pointed at the earlier Quick Tunnel,
  which failed at Cloudflare. A fresh, externally verified tunnel now exists;
  Meta must be updated to its `/webhook` endpoint and saved once more. The
  existing local verify token remains the correct value; `messages` remains
  subscribed.
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

The remaining user acceptance check is to send a WhatsApp message while the
laptop is asleep, then wake it and observe the job lifecycle. The bus, tunnel,
and local executor are already running for that test.

## Acceptance still required

- With the laptop asleep: WhatsApp the test number, wake the laptop, and watch
  the job move queued → running → done.
- Unsigned local POST to `/webhook` returned 403 on 24 August 2026.
- The executor's independent live lifecycle probe passed. No inbound
  `whatsapp_webhook` job has yet appeared, so phone-originated delivery remains
  the final acceptance proof.
