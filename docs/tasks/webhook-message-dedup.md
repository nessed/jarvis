# webhook-message-dedup

A real, previously-flagged gap: `docs/plan.md`'s `bus/main.py` job list names
this without a spec (a genuine gap in that board — it was only ever named in
a summary line). The actual finding, with full context, is in
`docs/blockers/supabase-unreachable-from-laptop.md`'s "Known side effect
surfaced by this test, not yet fixed" section (bottom of the file) and
`docs/audit/blueprint-drift.md:375-377`. Read both before starting.

## The gap, precisely

`bus/main.py`'s `POST /webhook` (`receive_webhook`, around line 88-96) calls
`enqueue("whatsapp_webhook", payload, repository=repository)`
**unconditionally on every delivery**. Meta redelivers a webhook it didn't
get a fast `200` for — confirmed live on 26 August 2026, during a transient
Supabase connectivity gap, several redeliveries of the *same* message each
created a separate job. `docs/state.md`'s "Conversation wiring" row says
"Dedups by Meta's message id," which is true only at the very end of the
pipeline: `executor/handlers/whatsapp.py`'s `SeenMessageStore`
(`sent_replies` sqlite table, lines ~65-93) stops a *duplicate reply* from
being sent, but a duplicate *job* still gets created, claimed, and fully
processed (a wasted provider call, a wasted memory-recall/store cycle) before
that check catches it at the send step. `docs/state.md` calling this
"dedup'd" is real drift — the audit calls it "masked" — worth a one-line
correction there once this lane's fix lands.

## What to build

Dedup at the point of enqueue, not just the point of send, using the exact
same pattern already proven at `executor/handlers/whatsapp.py`'s
`SeenMessageStore` — read that class in full and mirror its shape (an
injectable sqlite path, `CREATE TABLE IF NOT EXISTS ... message_id TEXT
PRIMARY KEY`, an `INSERT OR IGNORE`-based mark, so concurrent marks are safe
without a lock).

**Do not touch `db/jobs.py` or the `JobRepository` Protocol.** That Protocol
has no query/lookup method today (only `enqueue`, `claim_next`, `checkpoint`,
`complete`, `fail`, `retry_or_dead_letter`, `set_timeout`) and widening it is
a shared-interface change with implementers this lane does not own
(`tests/db/test_jobs.py`, `tests/test_integration.py`,
`tests/executor/test_poller.py`, `tests/executor/test_distill_handler.py` —
see `docs/plan.md`'s "Cross-lane test doubles" section). **This also must not
require a live Supabase schema migration** — those are blocked pending Ali's
explicit approval (`docs/plan.md`'s "Blocked on Ali" table). The fix is
scoped specifically to avoid both: a bus-local sqlite table of seen inbound
message ids, checked before `enqueue()` is ever called, is sufficient and
matches the existing `SeenMessageStore` precedent exactly.

**New module**: `bus/webhook_dedup.py`. Something like a
`SeenWebhookMessageStore` (name it as fits) with `has_seen(message_id) ->
bool` and `mark_seen(message_id) -> None`, sqlite-backed, path injectable
(default path pattern: check how `MEMORY_DB_PATH` or
`executor/heartbeat.py`'s heartbeat path env var are read/defaulted, and
follow the same convention for a new env var, e.g.
`JARVIS_WEBHOOK_DEDUP_DB_PATH`).

**Message-id extraction**: a raw Meta webhook payload can carry more than one
message per delivery (`entry[].changes[].value.messages[]`). **Do not import
`executor.handlers.whatsapp`'s `parse_inbound_text_message` or
`InboundMessage`** — `executor/handlers/whatsapp.py` already imports *from*
`bus` (`bus.whatsapp_client`), so importing the reverse direction from `bus`
would create a circular import. Write a small, local extraction helper in
`bus/webhook_dedup.py` that walks the same `entry`/`changes`/`value`/
`messages` shape and collects every present `message.get("id")` — it does
not need the sender/text/type filtering `parse_inbound_text_message` does,
only the ids, and every message in the array (not just `type == "text"`)
should count for dedup purposes, since a redelivered non-text message is
still a redelivery.

**Wire into `receive_webhook`**: extract every message id in the incoming
payload. If the payload has one or more message ids and *every one* of them
has already been seen, skip `enqueue()` entirely and return a response
indicating the duplicate rather than a fresh `job_id` (decide the exact
response shape — e.g. `{"accepted": True, "duplicate": True}` — and say what
you chose and why; do not silently return a fake/stale job id). If the
payload has no extractable message ids at all (a status callback, a
malformed/empty body, or any other shape `parse_inbound_text_message`
already treats as a no-op elsewhere in this codebase), behavior must be
byte-for-byte unchanged from today — still enqueue, exactly as now. Mark
every extracted id as seen only *after* a successful `enqueue()` call (mirror
`SeenMessageStore`'s own reasoning: mark only after the action actually
happened, never before, so a crash between the check and the enqueue doesn't
permanently blackhole a message).

## Tests

New file: `tests/bus/test_webhook_dedup.py` — unit tests for the store
itself (`has_seen`/`mark_seen`, `INSERT OR IGNORE` idempotency on a repeated
mark).

Extend `tests/test_integration.py` (the existing home for `bus/main.py`'s
webhook tests — check it first for the existing `TestClient`/fixture
pattern, match it): a first delivery of a payload enqueues a job as today; a
second delivery of the *same* payload (same message id) does not call
`enqueue` again (assert against whatever fake `JobRepository`/spy the
existing tests already use) and returns the duplicate response instead; a
delivery with a different message id enqueues normally; a payload with zero
extractable message ids (a status-callback-shaped payload) still enqueues,
proving no regression for the existing no-op case.

## Verification

Run the full offline suite exactly as CLAUDE.md specifies:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Cite the output. Do not report done without it. Do not commit; BUILD role,
no `requirements.txt` changes needed (sqlite3 is stdlib). Report back: the
exact response shape you chose for a detected duplicate, the new env var
name and default path, test counts before/after, and anything above you
could not complete and why.
