# Phase 0 archive: bus, durable queue, executor, provider routing

> Frozen archive. Nothing in this file is edited once written. If a fact here
> stops being true, the live version belongs in `docs/state.md`, and what is in
> flight right now belongs in `docs/context.md`.

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

## Acceptance evidence

- With the laptop closed, a phone-originated WhatsApp message arrived after
  wake and created durable `whatsapp_webhook` jobs that reached `done` with
  executor checkpoints on 24 August 2026.
- Unsigned local POST to `/webhook` returned 403 on 24 August 2026.
- The executor's independent live lifecycle probe also passed.
