# JARVIS component state

Semi-fixed tier. What is true about each component right now, and what is
blocking it. Facts here survive a session but not a phase.

Do not record what happened here, only what is. Evidence and narrative go in
`docs/history/`. What is in flight right now goes in `docs/context.md`. If you
find yourself writing a date and a story, you are in the wrong file.

## Phase position

Phase 0 complete and verified. Phase 1 underway. Phase 2 scaffolding started
in parallel (blueprint-authorized), blocked — see open blocker 6.

Phase order: 0 bus, 1 memory, 2 FL Studio, 3 voice, 4 VPS/laptop split,
5 vision fallback. Phases 3 to 5 have not started.

## Built and working

| Component | State |
|---|---|
| FastAPI bus | HMAC-verified webhooks, bearer auth elsewhere, request-ID JSON logging, protected `/status` |
| Supabase queue | Migrations `0001` and `0002` applied live. RLS on, no public policies, RPCs service-role only |
| Queue client | Rejects publishable/anon credentials, requires `SUPABASE_SECRET_KEY`. PostgREST timeout pinned to 10s (`SUPABASE_QUEUE_TIMEOUT_SECONDS`) — supabase-py's 120s default let one hung connection stall the serial poll loop for two minutes |
| Executor | Atomic claim, checkpoint, complete. Retry, backoff, per-job timeout, dead-letter |
| Memory | SQLite facts, sqlite-vec index, loopback Ollama. Two paths: conversation turns embed-and-store inline (fast), and `tools/distill_memory.py` folds them into Mem0 facts as an offline batch |
| Conversation wiring | `whatsapp_webhook` handler: recall, route, **send**, then store the turn. Reply-first is an authorized amendment to the blueprint's step order. Turns are stored verbatim via `memory/conversation.py` (~0.5s embed), **not** Mem0 extraction. Dedups by Meta's message id. See `docs/history/whatsapp-reply-failures.md` |
| Outbound WhatsApp | `WhatsAppClient.send_text_message()`. A real send through the live Graph API succeeded 26 August 2026 |
| Process tooling | `tools/consult.py`, `tools/repoint_webhook.py`, `tests/live/`, pre-commit hook |
| `/status` | Reports `retry_health` (dead-letter and retried-job counts) from the live queue, additive to the existing payload |
| FL Studio sort (`executor/flp/sort.py`) | `flp_backup`, `load`/`save`, `apply_rules`, `diff_report`, `verify`, `build_flp_sort_handler` built and unit-tested against fakes (16 tests). Registered as job kind `flp_sort` in `executor/poller.py`'s `DEFAULT_HANDLERS`, but nothing enqueues it yet. Reordering mixer inserts raises `ReorderNotSupported` rather than silently no-op'ing: PyFLP has no insert-move API. Cannot be exercised against a real or synthetic `.flp` yet — see open blocker 6 |
| Startup | `start-jarvis.bat` -> `tools/start_jarvis.py` brings up Ollama check, bus, tunnel, Meta re-point and executor in order, waiting for each to answer before the next. Ctrl+C stops the set together; a child dying reports which and shuts the rest down |
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

1. **Batch distillation is not scheduled.** Mem0 fact extraction costs ~55s
   per turn, so it is off the reply path: turns are stored verbatim and
   `tools/distill_memory.py` folds them into facts later. Nothing runs it, so
   distilled facts lag until it is invoked by hand. It refuses to start while
   the executor is polling (`executor/heartbeat.py`), so scheduling it needs a
   window with the executor stopped, or `--force` and slower replies.
2. **No opted-in backfill.** No corpus has completed the fact-extraction and
   review acceptance loop.
3. **Meta app is unpublished.** Dashboard test events arrive, production data
   does not.
4. **The tunnel is ephemeral.** A Cloudflare Quick Tunnel URL dies whenever
   cloudflared or the laptop stops. `start-jarvis.bat` now mints a new one and
   re-points Meta automatically on each run, so this is no longer a manual
   step — but nothing receives messages while the laptop is off. A named
   tunnel, and moving the bus off the laptop, are both Phase 4.
5. **PyFLP does not work on this machine's Python (3.12).** A stdlib
   `enum.py` change breaks `pyflp.parse()` on any input, and `pyflp.save()`
   cannot create a project from scratch either — reproduced on both an empty
   project and a real PyFLP test fixture. PyFLP's own support matrix only
   claims 3.8–3.11. Blocks all of Phase 2 until a Python 3.11 environment is
   set up for this project; not worked around. Also still needs blueprint
   2.1: real guinea-pig `.flp` files and the user's dictated mixer-sorting
   convention, neither of which exist yet.

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

## This machine and network

- **The ISP DNS resolver lags on fresh records.** It returned NXDOMAIN for a
  Quick Tunnel hostname that `1.1.1.1` and `8.8.8.8` both resolved correctly.
  Meta resolves independently, so a tunnel this laptop cannot look up is still
  reachable from the internet. `tools/start_jarvis.py` therefore gets a
  second opinion from public DNS before believing a tunnel is dead, and passes
  `--skip-probe` to `repoint_webhook.py` in that case. Do not "fix" a
  local-probe failure by assuming the tunnel is broken.
- **Supabase connectivity is intermittently flaky here**, occasionally failing
  TLS with `WinError 10054` for minutes at a time before recovering on its
  own. The queue client's 10s timeout keeps that from stalling the poll loop.
- **Ollama is a single serial resource.** Any batch job using it blocks live
  replies for its whole duration. That is what `executor/heartbeat.py` guards.
- **Local fact extraction is CPU-only** and roughly 250x slower than
  embedding (~55s vs ~0.5s), which is the reason for the two-path memory
  design above.
- The system `TEMP` directory is locked down; pytest needs
  `-p no:cacheprovider --basetemp=.pytest-basetemp` to run.

## Local configuration

Confirmed present without reading values: Groq, Cerebras, Gemini, OpenRouter,
Mistral, DeepSeek direct, Supabase URL, Supabase publishable key, Supabase
secret key, Meta verify token, Meta phone number ID, Meta app ID, Meta app
secret, Meta system-user access token, bus bearer token.

No credential, token, password or database secret is committed or recorded in
any file in this repository. `.env` is gitignored and `.env.example` holds
empty placeholders.
