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

The FastAPI bus and a temporary Cloudflare Quick Tunnel were running when this
note was last updated. The laptop is now being closed, so treat both local
processes as stopped and the quick-tunnel address as expired until regenerated.
Before pausing, the tunnel had been checked against the protected health route;
its `401` response confirmed the route was reachable and bearer protection was
active.

- Previous callback URL (expired once the laptop closes):
  `https://injured-drew-wells-partner.trycloudflare.com/webhook`
- A Quick Tunnel changes whenever its process stops. On resume, restart the
  FastAPI bus and Cloudflare Tunnel, record the replacement URL here, then use
  `<replacement-url>/webhook` for the eventual Meta configuration.
- Do not press Save in Meta configuration until the callback URL and local
  verify token fields have both been reviewed.

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
