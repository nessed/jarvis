# JARVIS component state

Semi-fixed tier. What is true about each component right now, and what is
blocking it. Facts here survive a session but not a phase.

Do not record what happened here, only what is. Evidence and narrative go in
`docs/history/`. What is in flight right now goes in `docs/context.md`. If you
find yourself writing a date and a story, you are in the wrong file.

## Phase position

Phase 0 complete and verified. Phase 1 underway. Phase 2 scaffolding started
in parallel (blueprint-authorized). Its interpreter blocker is cleared; it now
waits on the user for real `.flp` files and a sorting convention — see open
blocker 4.

Phase order: 0 bus, 1 memory, 2 FL Studio, 3 voice, 4 VPS/laptop split,
5 vision fallback. Phases 3 to 5 have not started.

## Built and working

| Component | State |
|---|---|
| FastAPI bus | HMAC-verified webhooks, bearer auth elsewhere, request-ID JSON logging, protected `/status` |
| Supabase queue | Migrations `0001` and `0002` applied live. RLS on, no public policies, RPCs service-role only |
| Queue client | Rejects publishable/anon credentials, requires `SUPABASE_SECRET_KEY`. PostgREST timeout pinned to 10s (`SUPABASE_QUEUE_TIMEOUT_SECONDS`) — supabase-py's 120s default let one hung connection stall the serial poll loop for two minutes |
| Executor | Atomic claim, checkpoint, complete. Retry, backoff, per-job timeout, dead-letter |
| Memory | SQLite facts, sqlite-vec index, loopback Ollama. Two paths: conversation turns embed-and-store inline (fast), and the shared loop in `memory/distill.py` folds them into Mem0 facts as an offline batch |
| Batch distillation | Job kind `distill_memory` (`executor/handlers/distill.py`), self-re-enqueuing. One turn per job; a yield check for ready non-distill work runs **before** any extraction, so a ripe distill row costs one query rather than 55s when a reply is waiting. `run_after` is a duty-cycle throttle only, never a priority — the queue has no priority column and `claim_next_job` orders by `run_after asc, created_at asc`, so the ordering inversion is real and is absorbed by the yield check, not prevented. The successor write carries a veto evaluated **at the write site**: it refuses if this pass no longer owns its row (the poller re-queues what it claimed on timeout, and the abandoned thread would otherwise enqueue beside it) or if a sibling row is already open. Forks never merge, so each one would permanently double the duty cycle. `assert_timeouts_ordered` runs at executor startup and per row; it had no production caller at all until 27 Aug 2026. The executor seeds the chain at startup (not for `--once`), best-effort. Mechanism chosen adversarially: `docs/consults/2026-08-27-distill-scheduling-mechanism/`. `tools/distill_memory.py` remains as the manual path, still heartbeat-guarded |
| Batch-tool liveness guards | Both Ollama-driving batch tools refuse while the executor's heartbeat is fresh: `tools/distill_memory.py` and now `tools/run_backfill.py`. Same `--force` override, same message from `executor/heartbeat.py`. `--dry-run` is never blocked |
| Conversation wiring | Recalled memory is injected as a **user**-role message inside a `<remembered_context>` fence, never as `system`. `remember_turn` stores inbound bodies verbatim, so until 27 Aug 2026 anything a sender said came back wearing the operator's role — a write into the instruction channel for anyone who could get a sentence remembered. Fence markers are stripped from the content so it cannot be closed from inside. `whatsapp_webhook` handler: recall, route, **send**, then store the turn. Reply-first is an authorized amendment to the blueprint's step order. Turns are stored verbatim via `memory/conversation.py` (~0.5s embed), **not** Mem0 extraction. Dedups by Meta's message id. See `docs/history/whatsapp-reply-failures.md` |
| Outbound WhatsApp | `WhatsAppClient.send_text_message()`. A real send through the live Graph API succeeded 26 August 2026 |
| Process tooling | `tools/consult.py`, `tools/repoint_webhook.py`, `tests/live/`, pre-commit hook. **`consult.py` sends the prompt on stdin, never in argv** — `claude.cmd` runs through `cmd.exe`, where a newline in an argv element terminates the command and the line is capped at 8191 chars, so every consult before 27 Aug 2026 delivered only its first line and got a confidently wrong answer back. No pre-fix verdict exists in `docs/consults/`, so nothing archived is suspect. Sub-model output is framed as untrusted data at every exit — stderr, `response.md`, and the `verdict` field when the reply is not JSON |
| `/status` | Reports `retry_health` (dead-letter and retried-job counts) from the live queue, additive to the existing payload |
| FL Studio sort (`executor/flp/sort.py`) | `flp_backup`, `load`/`save`, `apply_rules`, `diff_report`, `verify`, `build_flp_sort_handler` built and unit-tested against fakes (16 tests). Registered as job kind `flp_sort` in `executor/poller.py`'s `DEFAULT_HANDLERS`, but nothing enqueues it yet. Reordering mixer inserts raises `ReorderNotSupported` rather than silently no-op'ing: PyFLP has no insert-move API. PyFLP itself now works — `.venv311` on CPython 3.11.5 parses and saves real `.flp` files (`tests/flp/test_flp_real.py`, marker `realflp`) — but `sort.py` has still never been run against one, because there are no guinea-pig projects yet. See open blocker 4 |
| Startup | Passes `--protocol http2` to cloudflared (`JARVIS_TUNNEL_PROTOCOL` overrides). QUIC is UDP 7844 and is unroutable on this network — every dial failed `wsasendto: unreachable network`, the tunnel never registered, and a URL that resolved nowhere was minted while ordinary TCP to the same edge was fine. http2 registered first try, zero errors. `start-jarvis.bat` -> `tools/start_jarvis.py` brings up Ollama check, bus, tunnel, Meta re-point and executor in order, waiting for each to answer before the next. Ctrl+C stops the set together; a child dying reports which and shuts the rest down |
| Single-instance guard | The launcher binds `127.0.0.1:8765` exclusively (`JARVIS_SINGLETON_PORT` overrides) as `main`'s first side effect, before the Ollama probe and before any child. A second copy refuses, names the holding PID via `netstat -ano`, exits nonzero, and mints no tunnel and re-points nothing. `SO_REUSEADDR` is deliberately never set. Fails open like `executor/heartbeat.py`: the OS releases the bind however the process dies, so no stale lock can wedge a future launch. The refusal never kills anything — it says Ctrl+C in the owning window. Loopback health probes could not catch a duplicate: an HTTP 200 on `127.0.0.1:8000` does not say whose process answered |
| Bus logging | uvicorn's access log redacts the verify token, matching **both** `hub.verify_token` and `hub_verify_token`. A live Meta handshake carried both spellings and only the dotted one was caught, so the value reached `tools/bus.out.log` in plaintext. Logs are gitignored, so it was never committed. `hub[._]challenge` is deliberately left alone: a public nonce, not a credential |

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

1. **No opted-in backfill.** No corpus has completed the fact-extraction and
   review acceptance loop.
2. **Meta app is unpublished.** Dashboard test events arrive, production data
   does not.
3. **The tunnel is ephemeral.** A Cloudflare Quick Tunnel URL dies whenever
   cloudflared or the laptop stops. `start-jarvis.bat` now mints a new one and
   re-points Meta automatically on each run, so this is no longer a manual
   step — but nothing receives messages while the laptop is off. A named
   tunnel, and moving the bus off the laptop, are both Phase 4.
4. **Phase 2 needs two things from the user.** The interpreter half is done:
   `.venv311` on CPython **3.11.5** parses and saves real `.flp` files, proved
   against PyFLP's own `FL 20.8.4.flp` fixture with a rename that survived a
   save-and-re-parse round trip. What is still missing is blueprint 2.1, and
   both halves are the user's:
   - ~~Real guinea-pig `.flp` files.~~ **Done.** A real project is now in
     `test_projects/` (gitignored, copy only). Parsing it exposed a second,
     independent PyFLP failure — see the note below.
   - **The dictated mixer-sorting convention.** `apply_rules()` runs on a
     placeholder ruleset. Guessing it is out of scope.

   Evidence and the full history: `docs/blockers/pyflp-python-312.md`.
   **New, separate from the above:** parsing the real project raises
   `IndexError: list index out of range` inside PyFLP's own channel-grouping
   code (`channel.py:1586`) once it reaches a channel referencing a group
   number PyFLP's own `groups` list doesn't contain. The 3.11.5 interpreter
   fix is confirmed still working — this is a distinct gap in PyFLP itself, hit
   once, not yet investigated further. `docs/blockers/pyflp-channel-groups-indexerror.md`.
5. **One tool-result injection is unexplained.** Text claiming a plan-mode
   transition, and instructing a change of tooling, appeared inside a tool
   result during a session that was never in plan mode. An exhaustive search of
   the tree — untracked, gitignored, logs, consults, transcripts — did not find
   the string anywhere on this machine. The leading account is harness
   mode-transition text rather than anything repo-originated, and a 25 August
   session shows the same shape. Not reproduced, so **not closed**. Two related
   facts on disk: a `PostToolUse` hook that appends text to tool results ships
   in an installed plugin (inert, unset guard variables), and repo-root
   `.pytest_cache/` could not be read. `docs/blockers/tool-result-injection.md`.

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
- **Two Python environments, and the second one is version-locked.** `.venv`
  is Python 3.12.10 and stays the default for everything. `.venv311` is
  CPython **3.11.5** and holds only `pyflp` and `pytest`
  (`requirements-flp.txt`). It must not be upgraded: CPython 3.11.6 backported
  the empty-enum guard that breaks PyFLP, so 3.11.6+ and 3.12+ are both
  unusable. 3.11.5 is unpatched (Aug 2023) and is only acceptable because that
  environment is offline, off `PATH`, two packages wide, and reads nothing but
  the user's own `.flp` copies. Always spell out `.venv311\Scripts\python.exe`;
  never `py`, never bare `python`.

## Local configuration

Confirmed present without reading values: Groq, Cerebras, Gemini, OpenRouter,
Mistral, DeepSeek direct, Supabase URL, Supabase publishable key, Supabase
secret key, Meta verify token, Meta phone number ID, Meta app ID, Meta app
secret, Meta system-user access token, bus bearer token.

No credential, token, password or database secret is committed or recorded in
any file in this repository. `.env` is gitignored and `.env.example` holds
empty placeholders.
