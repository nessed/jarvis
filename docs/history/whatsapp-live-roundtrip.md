# First live WhatsApp round trip through the whatsapp_webhook handler (26 August 2026)

Frozen record. Blueprint step 1.4 (recall -> route -> remember -> send) is
finished and live-verified. If a fact here stops being true, that belongs in
`docs/state.md`, not here.

## What was proven

With the bus (`uvicorn bus.main:app`), a Cloudflare quick tunnel, and the
executor (`python -m executor.poller`) all running, and Meta's webhook
re-pointed at the live tunnel via `tools/repoint_webhook.py`, a real WhatsApp
message sent from the user's phone to the test number went all the way
through the real stack — not a fake transport: the bus enqueued it, the
executor claimed the job, `executor/handlers/whatsapp.py` recalled memory,
routed the message through the real provider ladder, remembered both turns,
and sent the reply through the real `WhatsAppClient` against Meta's Graph
API. The user confirmed on their phone: "real reply ... took like 6 mins to
send." The ~6 minute delay is attributed to a transient Supabase connectivity
outage during the same window (see
`docs/blockers/supabase-unreachable-from-laptop.md`, resolved) plus one cold
Mem0/Ollama extraction, not handler latency under normal conditions.

## What this session also had to fix to get here

- **`META_VERIFY_TOKEN` in `.env` was longer than the 64-character limit**
  Meta's `POST /{app-id}/subscriptions` enforces on `verify_token`, which
  `tools/repoint_webhook.py`'s POST path had never actually exercised before
  (only `--check` had run live). Failed with `(#100) Param verify_token must
  be at most 64 characters long`. Fixed with the user's explicit go-ahead: a
  new 40-character token generated with `secrets.token_urlsafe` and written
  into `.env` without ever printing it, then the bus was restarted (env vars
  are only read at process start) and the repoint retried successfully,
  confirmed by read-back.
- **A ~10-minute Supabase connectivity outage from this laptop**, unrelated to
  the handler or Meta side — see the blocker file above for the full
  diagnostic trail (ruled out DNS, project pause, general internet loss,
  wrong project reference) and its resolution (self-recovered, cause
  unconfirmed).
- **Uvicorn's own access log printed `META_VERIFY_TOKEN` in plaintext** as
  part of the `GET /webhook?hub.verify_token=...` query string during the
  Meta handshake, in `tools/bus.out.log`. Not something this session's code
  controls (it's uvicorn's default access-log format), but worth fixing
  later — e.g. `--no-access-log` or a logging filter — since the project's
  own non-negotiables say secrets are never logged. Not fixed this session.

## What is still open after this

- **No dedup by Meta's message id.** Meta redelivered the same message
  several times during the connectivity outage, and `bus/main.py` enqueues
  unconditionally on every delivery — at least one duplicate job was created.
  Whether it produced a duplicate reply to the user was not separately
  confirmed. Not fixed this session.
- **`memory.db` now holds one real conversational exchange** (the test
  message and the model's reply, remembered under the sender's WhatsApp
  number as `user_id`). This is expected `remember()`/`recall()` behavior for
  a live conversation, not corpus ingestion, and is consistent with the
  opt-in rule in `agents.md` (no *external corpus* was read) — noted here so
  it isn't mistaken for test data to delete.

## Processes left running by this session

Bus (uvicorn), the Cloudflare tunnel (`tools/cloudflared.exe`, logging to
`tools/cloudflared.log`), and the executor (`python -m executor.poller
--interval 3`) were all still running as background processes when this was
written. Meta's webhook was pointed at
`https://degrees-coleman-exception-schedule.trycloudflare.com/webhook`, a
Quick Tunnel URL that dies whenever `cloudflared` restarts — expect to
re-point again next session.
