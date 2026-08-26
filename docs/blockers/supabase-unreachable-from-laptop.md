# Supabase briefly unreachable from this laptop (26 August 2026) — RESOLVED, self-recovered

**Update:** this was transient, not a persistent block. Connectivity to
Supabase recovered on its own a few minutes later with no network change on
this end — see "Resolution" below. Kept as a historical record since the
diagnostic evidence ruling out several other causes is still useful if this
recurs, but do not treat the "best-supported explanation" below as confirmed;
it was the working theory *before* the outage turned out to be temporary.

## Reproduction

With the bus, tunnel, and executor all running and Meta's webhook correctly
re-pointed at the live tunnel (confirmed by a successful `GET /webhook` 200
handshake), a real WhatsApp message sent to the test number reached the bus's
`POST /webhook`. Several consecutive deliveries (Meta's own retry) failed
before a job could be created:

```
httpcore.ConnectError: [WinError 10054] An existing connection was forcibly closed by the remote host
```

raised from `httpx`'s `start_tls` step while the bus's Supabase client tried
to reach `SUPABASE_URL`. The executor's independent `claim_next` polling
(every 3s) hit the same failure mode continuously for at least 10 consecutive
attempts — not a one-off blip in the moment, but see "Resolution" below.

## Evidence gathered while this looked like a persistent block

- **Not a code bug.** Nothing in `bus/main.py`, `db/jobs.py`, or the new
  `whatsapp_webhook` handler executes before this call; the failure was purely
  in reaching Supabase.
- **Not the project being paused.** Checked the Supabase dashboard directly
  (account `ali.abid444444@gmail.com`) — the project showed active/healthy
  throughout. The Supabase MCP connector available in this session is
  authenticated to a *different* account/org and cannot see this project at
  all (`evauinppptyamkttwfdd`/"whatsapp-bot", initially suspected as a
  possible mismatch, was confirmed by the user to be unrelated).
- **Not general internet loss.** `https://api.cloudflare.com` and
  `https://graph.facebook.com` both responded normally (404/400 — TLS and
  HTTP completed) from the same machine, same terminal, around the same time.
- **Not DNS.** `nslookup yhbymzznlahbxrrqqpof.supabase.co` resolved cleanly to
  `172.64.149.246` / `104.18.38.10` (Cloudflare-fronted, as expected for
  Supabase) throughout.
- **Direct `curl` probes to the resolved host failed 3/3** with `connect:
  0.000000s` (full timeout, TCP never completed) or the same forcibly-closed
  reset.
- Working theory at the time (now unconfirmed either way, since nothing was
  changed to fix it): DNS resolving fine plus other Cloudflare-fronted hosts
  working, but only this hostname failing at TCP/TLS, looked like
  SNI/hostname-based filtering rather than an IP-range block — the same class
  of restriction `docs/context.md` documents for NVIDIA NIM from Pakistan.
  **This was not verified and should not be assumed true.**

## Resolution

No action was taken to fix connectivity — no VPN, no network change, nothing
in `.env` or code touched. A few minutes after the failures above, the bus
log shows four consecutive `POST /webhook` requests returning `200 OK`
(Meta's queued retries of the same message, now landing successfully once the
path cleared), and the executor picked up a job, ran the full
`whatsapp_webhook` handler (`recall` → `route` → `remember` ×2 → send), and
the user confirmed receiving a real, coherent WhatsApp reply about ~6 minutes
after sending the original message. That delay is consistent with Meta's own
retry/backoff schedule during the outage window plus one cold Mem0/Ollama
extraction, not evidence of an ongoing problem.

## If this happens again

Don't assume it's the same cause. Re-run the diagnostic steps above (dashboard
status, DNS, a control host like `api.cloudflare.com`, direct `curl` to the
Supabase host) before concluding anything, since this instance turned out to
be transient. If it repeats and does *not* self-resolve within a few minutes,
*then* the earlier theory (try a VPN or different network path) is worth
testing.

## Known side effect surfaced by this test, not yet fixed

Meta redelivered the same inbound message multiple times during the outage
window, and `bus/main.py`'s webhook handler enqueues unconditionally on every
delivery — there is no dedup by Meta's own message id
(`messages[].id`/`wamid...`). At least one duplicate job was enqueued this
session; whether it produced a duplicate reply wasn't separately confirmed.
Not fixed as part of this session — noted here rather than silently ignored.
