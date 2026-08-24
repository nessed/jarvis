# JARVIS project context

Last updated: 23 August 2026 (Phase 0, paused for laptop shutdown).

## Current state

Repository operating rules were rewritten on 24 August 2026. Parallel,
disjoint-file subagent lanes are now the default; every completed subtask must
refresh this handoff document with its outcome and blocker state.

Phase 0 has a committed foundation plus uncommitted Wave B/Wave C work ready
for final account configuration. The first commit is `bc7fb27` (`Build Phase 0
skeleton`). The worktree intentionally contains the pending queue, router,
security, integration, test, and dependency changes; do not discard them.

On 24 August 2026, `.env` was verified ignored and the Gemini, DeepSeek, and
Supabase configuration variables were confirmed present without reading their
values. DeepSeek is configured for its direct API rather than the OpenRouter
proxy. The live Supabase lifecycle test currently returns `PGRST205` because
`public.jobs` has not yet been migrated; apply `0001_jobs.sql` before treating
the live queue as ready.

L1 verified that the target project is reachable but `public.jobs` is absent.
The original migration is unsafe: it creates an exposed `public.jobs` table
with RLS disabled while the configured application key is publishable. Do not
apply it as written. The corrected design must use a server-only Supabase key
for the bus/executor and enable RLS with no public policies (or use an
unexposed schema). The configured Supabase console integration does not expose
this target project, and no local Supabase CLI or `psql` is installed.

The security remediation is complete locally: the queue client now requires
`SUPABASE_SECRET_KEY` (or the legacy `SUPABASE_SERVICE_ROLE_KEY`) and rejects
publishable/anon credentials. The revised migration enables RLS, has no public
policies, revokes public table/RPC access, and limits its RPC functions to
`service_role`. Focused verification: **6 passed, 1 skipped**; the live test
awaits a server-only key and migration application. Add Secret key creation to
the next user credentials batch, then apply the revised migration through the
Supabase SQL Editor.

L2 verified `deepseek-v4-flash` is configured and the direct-proxy switch is
disabled. The direct DeepSeek smoke test is presently blocked because
`DEEPSEEK_API_KEY` is not present in local `.env`; restore that credential in
the next user credentials batch. Groq and Gemini minimal routed calls returned
200. Cerebras authentication works, but its available chat-model calls returned
`402 payment_required`, so it is currently not a usable free fallback lane.
Router verification added a real successful-header capture path with duration
parsing and a peak-window test proving non-urgent DeepSeek work defers at 06:30
UTC instead of merely warning. `tests/router`: **11 passed**.

L3 restored the local bus; its protected health route returns 401 as expected.
Cloudflare Quick Tunnel creation failed twice (sandbox socket restriction, then
TryCloudflare timeout), so there is no replacement callback URL or running
tunnel yet. Meta reconnaissance found one WhatsApp app, in development, with a
test recipient already allow-listed. Its Phone Number ID and App ID are now in
local `.env`; the dashboard currently has no generated access token. WhatsApp
Configuration still points to a stale `ngrok-free.dev` callback, has a masked
verify token, and is subscribed to messages. Do not overwrite it until a fresh
tunnel exists and the user reviews the new callback/verify-token fields. The
Meta page remains open for the later handoff. Development-mode webhook delivery
is limited to dashboard test events until the app is published.

Stop 1 credential pages are staged in Chrome: Supabase Secret Keys, DeepSeek,
OpenRouter, NVIDIA NIM, and Mistral. No provider key was created by an agent.
The user must complete login/verification and each final Create action, then
place the resulting values locally as `SUPABASE_SECRET_KEY`,
`DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`, and
`MISTRAL_API_KEY`. NVIDIA may require Developer Program signup and email
verification. After presence-only verification, run L4 against the three new
provider rungs and apply the secured Supabase migration.

Presence-only check after the user’s clarification: `SUPABASE_URL` and the
publishable `SUPABASE_KEY` are set, but the required server-only
`SUPABASE_SECRET_KEY` is not present. `DEEPSEEK_API_KEY` is also empty. These
are distinct from the earlier publishable/project credentials and remain Stop 1
requirements; no values were read or recorded.

On 24 August 2026, the Supabase Secret key and DeepSeek API-key forms were
opened and named (`jarvis_queue` and `jarvis_router`) in Chrome, then stopped
at their final Create buttons for the user. OpenRouter, NVIDIA NIM, and Mistral
tabs remain available for their login/key-creation flow. No key value was read,
created, or written by an agent.

The user completed the final key-creation steps. `SUPABASE_SECRET_KEY` and
`DEEPSEEK_API_KEY` are now confirmed present in local `.env` without values
being exposed or documented. The secured queue migration and direct DeepSeek
smoke test can proceed.

The revised `0001_jobs.sql` migration was applied successfully through the
target Supabase SQL Editor. It returned success with no rows, and the project
now has the RLS-protected jobs table plus service-role-only queue RPCs. Run the
real lifecycle test next; do not reapply the migration blindly because its
trigger creation is intentionally first-apply-only.

L2 re-ran the direct DeepSeek rung successfully: `deepseek-v4-flash` returned
HTTP 200 through `https://api.deepseek.com/v1` with the OpenRouter proxy
disabled. DeepSeek’s successful response contained no `Retry-After` or
rate-limit headers, so its real response did not exercise cooldown persistence;
the router correctly leaves that cooldown unset. Real successful-header parsing
remains demonstrated by Groq, while focused router tests remain **11 passed**.

L1’s live secured Supabase lifecycle proof passed: enqueue → atomic claim →
checkpoint → complete, plus the failure path. The focused DB suite has **7
passed**. Publishable/anon credentials remain rejected by the repository, while
RLS stays deny-by-default and queue RPCs remain service-role-only. The only
noise was Supabase SDK deprecations and a pytest-cache filesystem warning.

Full Phase 0 suite after the live migration and direct DeepSeek proof: **26
passed**. The same non-failing Supabase SDK deprecations and pytest-cache
filesystem warning remain. The next checkpoint should include the secure queue
and router-verification changes before the remaining provider/Meta dashboard
handoff.

No provider credential, Supabase credential, Meta secret, access token, or
locally generated token is committed or documented here. `.env` exists only
locally and was verified ignored before the first commit.

## Implemented and verified

- FastAPI bus with a protected health route.
- Meta webhook handshake and `X-Hub-Signature-256` HMAC-SHA256 validation,
  using constant-time comparisons.
- Bearer protection for all non-webhook routes, request-ID JSON-line logging,
  and a protected `/status` endpoint.
- Supabase jobs migration at `db/migrations/0001_jobs.sql`: atomic job claiming
  uses `FOR UPDATE SKIP LOCKED`, with queue lifecycle functions in `db/jobs.py`.
- Eight-rung OpenAI-compatible router in `router/`, with runtime response-header
  cooldowns, profile ordering, DeepSeek off-peak gating, and the OpenRouter
  fallback switch. Claude Max is deliberately excluded as a router target.
- The webhook validates then **only enqueues** `whatsapp_webhook` jobs; it does
  not execute any work inline. `executor/poller.py` has the router entry point.
- Test result: **19 passed** for the local suite. The now-enabled real
  Supabase lifecycle test reaches the project but fails with `PGRST205` until
  `db/migrations/0001_jobs.sql` is applied.

## Live local services

The FastAPI bus and Cloudflare Quick Tunnel are running as of 24 August 2026.
The protected external health route returned `401`, confirming the tunnel and
bearer protection are both live.

- Current callback URL:
  `https://insulation-threatened-tip-bind.trycloudflare.com/webhook`
- This is a Quick Tunnel: its URL dies when the cloudflared process or laptop
  stops. Meta configuration must be updated again after any such restart until
  a named tunnel or the Phase 4 Oracle deployment replaces it.
- Do not press Save in Meta configuration until the callback URL and local
  verify-token fields have both been reviewed.

## Immediate user baton

1. **Browser lane:** Groq is configured locally; its `GROQ_API_KEY` is present
   and format-valid (the value was not exposed). Cerebras is signed in and its
   `jarvis-router` key has been created. A Gemini API key is now available to
   the user for the prepared Google AI Studio `jarvis-router` project. The key
   value is deliberately not recorded here and must be pasted by the user into
   local `.env` as `GEMINI_API_KEY`; the agent can then verify presence and
   resume the sequential provider workflow.
2. **Supabase:** project credentials are configured locally. Apply
   `db/migrations/0001_jobs.sql` through the SQL editor or normal migration
   workflow, then rerun the real lifecycle test.
3. **DeepSeek:** the direct API is configured with the OpenRouter proxy switch
   false/unset. Its small prepaid top-up was reported successful; live routing
   still needs its smoke test.
4. **Meta:** keep the test number available. Later, the user enters its
   verification code, copies the Phone Number ID/App Secret/access token into
   `.env`, and performs every final dashboard Save/Confirm action.

## Next execution order

1. Resume the local bus and generate a new Quick Tunnel URL; do not reuse the
   previous temporary URL.
2. Paste the available Gemini key into local `.env` as `GEMINI_API_KEY`. The
   agent can then verify its presence without displaying it.
3. Finish B4 provider-key harvest, then the Meta test-number and durable-token
   steps (webhook callback remains untouched until that point).
4. With the replacement tunnel running, open Meta WhatsApp Configuration, fill the
   callback URL above and the locally held verify token, then stop before Save
   for user review and approval.
5. Apply the Supabase migration and run the real lifecycle test.
6. Run the full suite again, commit all Phase 0 work, then perform acceptance:
   laptop-sleep WhatsApp queue flow and unsigned webhook returns `403`.
