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
| Supabase queue | Migrations `0001` and `0002` applied live. RLS on, no public policies, RPCs service-role only |
| Queue client | Rejects publishable/anon credentials, requires `SUPABASE_SECRET_KEY` |
| Executor | Atomic claim, checkpoint, complete. Retry, backoff, per-job timeout, dead-letter |
| Memory | SQLite facts, sqlite-vec index, loopback Ollama. Two paths: conversation turns embed-and-store inline (fast), and `tools/distill_memory.py` folds them into Mem0 facts as an offline batch |
| Conversation wiring | `whatsapp_webhook` handler: recall, route, **send**, then store the turn. Reply-first is an authorized amendment to the blueprint's step order. Turns are stored verbatim via `memory/conversation.py` (~0.5s embed), **not** Mem0 extraction. Dedups by Meta's message id. See `docs/history/whatsapp-reply-failures.md` |
| Outbound WhatsApp | `WhatsAppClient.send_text_message()`. A real send through the live Graph API succeeded 26 August 2026 |
| Process tooling | `tools/consult.py`, `tools/repoint_webhook.py`, `tests/live/`, pre-commit hook |
| `/status` | Reports `retry_health` (dead-letter and retried-job counts) from the live queue, additive to the existing payload |
| Bus logging | uvicorn's access log redacts `hub.verify_token`'s value instead of printing it in plaintext |

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

1. **Mem0 fact extraction is too slow to run inline** — ~55s per turn
   measured. It is no longer on the reply path: turns are stored verbatim and
   distilled by `tools/distill_memory.py` as a batch. Consequence: distilled
   facts lag until that batch runs, and nothing schedules it yet, so it is
   currently a manual command.
2. **No opted-in backfill.** No corpus has completed the fact-extraction and
   review acceptance loop.
3. **Batch distillation is not scheduled.** `tools/distill_memory.py` must be
   run by hand. It refuses to start while the executor is polling (see
   `executor/heartbeat.py`), so scheduling it needs a window where the
   executor is stopped, or `--force` and slower replies.
4. **Meta app is unpublished.** Dashboard test events arrive, production data
   does not.
5. **The tunnel is ephemeral.** A Cloudflare Quick Tunnel URL dies whenever
   cloudflared or the laptop stops. `tools/repoint_webhook.py` fixes the Meta
   side. Restarting cloudflared is still manual. A named tunnel is deferred to
   Phase 4.

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
