# JARVIS component state

Semi-fixed tier. What is true about each component right now, and what is
blocking it. Facts here survive a session but not a phase.

Do not record what happened here, only what is. Evidence and narrative go in
`docs/history/`. What is in flight right now goes in `docs/context.md`. If you
find yourself writing a date and a story, you are in the wrong file.

## Phase position

Phase 0 complete and verified. Phase 1 underway.

Phase order: 0 bus, 1 memory, 2 FL Studio, 3 voice, 4 VPS/laptop split,
5 vision fallback. Phases 2 to 5 have not started.

## Built and working

| Component | State |
|---|---|
| FastAPI bus | HMAC-verified webhooks, bearer auth elsewhere, request-ID JSON logging, protected `/status` |
| Supabase queue | Migration `0001` applied live. RLS on, no public policies, RPCs service-role only |
| Queue client | Rejects publishable/anon credentials, requires `SUPABASE_SECRET_KEY` |
| Executor | Atomic claim, checkpoint, complete. Retry, backoff, per-job timeout, dead-letter |
| Memory | SQLite facts, sqlite-vec index, loopback Ollama, self-hosted Mem0 wrapper. `remember()` and `recall()` both verified end to end |
| Conversation wiring | `whatsapp_webhook` handler registered: recall, route, remember, send. Live-verified end to end 26 August 2026, see `docs/history/whatsapp-live-roundtrip.md`. Dedups by Meta's message id (`SeenMessageStore`) so a redelivered webhook doesn't send a duplicate reply |
| Outbound WhatsApp | `WhatsAppClient.send_text_message()`. A real send through the live Graph API succeeded 26 August 2026 |
| Process tooling | `tools/consult.py`, `tools/repoint_webhook.py`, `tests/live/`, pre-commit hook |

Ollama 0.32.15 and `nomic-embed-text` are active on loopback. `memory.db` and
corpus inputs are gitignored. No personal corpus has been read or ingested.

## Provider rungs

| Rung | State |
|---|---|
| Groq | Working. Rate-limit header capture proven here |
| Gemini | Working |
| DeepSeek direct | Working through `https://api.deepseek.com/v1`. No rate-limit headers, so cooldown parsing is unexercised |
| OpenRouter | Working through `openrouter/free`. No retry headers, cooldown correctly stays empty |
| Cerebras | Authenticates, chat returns `402 payment_required`. Do not route work here |
| Mistral | Integrated, model discovery works, live chat returns `403`. Needs account or workspace resolution |
| NVIDIA NIM | Deferred. Geo-blocked from Pakistan, and removed from the fact-extraction plan by the blueprint 1.3 amendment |
| Claude Max | Used through `tools/consult.py`, not as a router target |

DeepSeek proxy mode is off. OpenRouter proxy routing is disabled.

## Open blockers

1. **Migration `0002` is not applied live.** Retry, backoff and dead-letter
   columns and RPCs are written and tested but the live Supabase project does
   not have them. Needs a Postgres driver or the Supabase CLI, which means a
   `requirements.txt` change, plus explicit approval for a live schema write.
2. **`retry_health()` is not wired into `/status`.** It exists in
   `bus/status.py` as an optional dependency. `bus/main.py` does not pass it.
3. **No opted-in backfill.** No corpus has completed the fact-extraction and
   review acceptance loop.
4. **`memory_extract` has no registered handler.** Nothing enqueues that kind
   on its own, because the WhatsApp handler does recall and remember inline.
   This is a design consequence, not an omission.
5. **Meta app is unpublished.** Dashboard test events arrive, production data
   does not.
6. **The tunnel is ephemeral.** A Cloudflare Quick Tunnel URL dies whenever
   cloudflared or the laptop stops. `tools/repoint_webhook.py` fixes the Meta
   side. Restarting cloudflared is still manual. A named tunnel is deferred to
   Phase 4.
7. **Uvicorn's access log can print `META_VERIFY_TOKEN` in plaintext** as part
   of the `GET /webhook` query string during Meta's handshake. Surfaced
   26 August 2026, not fixed. Needs `--no-access-log` or a logging filter.

## Meta account

- One WhatsApp app, **WA 1st**, in development. The test recipient allow-list
  already has the user's Pakistani number. Do not re-verify it.
- System user **whatsapp-bot** is Admin with full access to the app and test
  WABA. Do not create another system user or reassign assets.
- The system-user access token is permanent (`expires_at: 0`) with the right
  scopes, verified against the live test number. Its value is not recorded
  anywhere in the repo.
- If the token ever reads invalid, check it with `debug_token` through the
  Graph API before regenerating. Meta's dashboard has a separate rendering bug
  that has produced a false invalid reading before.
- Dashboard path, redesigned layout: **Use cases**, **Settings**,
  **Configurations**, the WhatsApp card's **Connect**, **Basic setup**,
  **Step 2. Production setup**, **Configure Webhooks**. Traditional layout:
  **WhatsApp**, **Configuration**.

## Local configuration

Confirmed present without reading values: Groq, Cerebras, Gemini, OpenRouter,
Mistral, DeepSeek direct, Supabase URL, Supabase publishable key, Supabase
secret key, Meta verify token, Meta phone number ID, Meta app ID, Meta app
secret, Meta system-user access token, bus bearer token.

No credential, token, password or database secret is committed or recorded in
any file in this repository. `.env` is gitignored and `.env.example` holds
empty placeholders.
