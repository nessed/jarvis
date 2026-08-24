# JARVIS project context

Last updated: 24 August 2026 — Phase 0 active, pending final provider and Meta dashboard handoff.

## Current state

The repository rules in `agents.md` make parallel, disjoint-file agent lanes
the default. Every completed subtask updates this handoff. `docs/blueprint.md`
is the architecture spec, but all fast-moving provider claims require current
verification before use.

Source checkpoints:

- `699c92d` — complete Phase 0 bus foundation.
- `c991f5e` — secure queue, live-provider verification, tests, context, and
  recoverable lane briefs.

No credential, token, password, or database secret is committed or recorded in
this file. `.env` is ignored and `.env.example` has empty placeholders.

## Completed and verified

- FastAPI bus with HMAC-verified Meta webhooks, bearer-protected non-webhook
  routes, request-ID JSON logging, protected `/status`, and enqueue-only
  webhook behavior.
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

- Callback URL: `https://insulation-threatened-tip-bind.trycloudflare.com/webhook`
- The external protected health route returned 401, confirming reachability and
  bearer protection.
- This is a Quick Tunnel. Its URL dies when cloudflared or the laptop stops;
  Meta must be updated after each restart until a named tunnel or Phase 4 Oracle
  deployment replaces it.

## Local configuration presence

Confirmed present without reading values: Groq, Cerebras, Gemini, Supabase URL,
Supabase publishable key, Supabase Secret key, DeepSeek direct key, Meta verify
token, Meta Phone Number ID, Meta App ID, and bus bearer token. DeepSeek proxy
mode is false/unset.

OpenRouter and Mistral are now configured locally. NVIDIA NIM is explicitly
deferred and must not block Phase 0. Still absent/pending: Meta App Secret and
Meta durable access token.

OpenRouter live smoke testing passed through `openrouter/free`. Its successful
response had no retry/rate-limit headers, so runtime cooldown capture correctly
remained empty. Mistral model discovery succeeded, but a minimal free Labs chat
request returned 403; treat Mistral as unavailable pending account/workspace
resolution. It is also missing from `router/providers.yaml`, so a router lane
must add the configured Mistral rung before it can ever act as a fallback.

The Mistral router integration is now complete. It uses the official
`https://api.mistral.ai/v1` endpoint ahead of paid DeepSeek, honors an explicit
`MISTRAL_DEFAULT_MODEL` when present, and otherwise dynamically discovers the
key’s unarchived chat-capable models through `/v1/models`; no free model ID is
hardcoded. Current Mistral 401/403 responses put the provider in cooldown and
surface the denial rather than silently falling through to paid work. Focused
router tests: **15 passed**. The live Mistral workspace 403 still needs account
resolution before that rung is usable.

Full suite after the Mistral integration: **30 passed**. The only non-failing
noise remains the Supabase SDK deprecations and pytest-cache filesystem warning.

## Meta state

- One WhatsApp app: **WA 1st**, in development. Its test recipient allow-list
  already contains the user’s Pakistani number; do not re-verify it.
- Existing system user **whatsapp-bot** is Admin and already has full access to
  the WA 1st app and test WABA. Do not create another system user or reassign
  assets.
- App Settings → Basic is open at the masked App Secret **Show** control.
- The system-token wizard is open with WA 1st selected, **Never** expiry, and
  `whatsapp_business_messaging` plus `whatsapp_business_management` selected;
  it awaits only final **Generate token**.
- Existing webhook configuration is still stale `ngrok-free.dev`, with a masked
  verify token and `messages` subscribed. The legacy configuration route did
  not finish loading its callback form in browser automation; resume discovery
  after the credential handoff, fill the current Quick Tunnel callback and
  local verify token, then stop before the user’s final Save.
- The app is unpublished: dashboard test events work, but production data will
  not be delivered until publication.

## Immediate user handoff

The following pages are staged in Chrome. The user performs only login/2FA/
captcha and final Create/Generate/Save actions; do not paste secrets into chat.

1. Create free keys in OpenRouter, NVIDIA NIM, and Mistral, leaving each
   revealed-key page open for secure local capture. NVIDIA may require Developer
   Program email verification. Do not purchase OpenRouter credit.
2. On Meta App Settings → Basic, reveal the App Secret and leave its revealed
   page open.
3. In the existing Meta system-token wizard, click final Generate token and
   leave its revealed-token page open.

OpenRouter’s API Keys page and Mistral’s login/key flow are freshly opened in
Chrome. NVIDIA’s existing sign-in tab remains open; browser safety policy
blocked agent control of that specific NVIDIA page, so the user must complete
its signup/verification directly in that tab.

After this batch, the agent securely writes the values only to local `.env`,
runs the L4 live tests for the three new provider rungs, finishes Meta callback
field staging, and stops only at the final Meta Save. Then run the final full
suite, commit, and execute the two Phase 0 acceptance checks.

## Acceptance still required

- With the laptop asleep: WhatsApp the test number, wake the laptop, and watch
  the job move queued → running → done.
- An unsigned POST to the webhook returns 403.
