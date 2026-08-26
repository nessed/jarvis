# Why live WhatsApp replies failed while every test passed (26-27 August 2026)

Frozen record. All three bugs below are fixed and verified. Live component
status belongs in `docs/state.md`, not here.

The first live round trip (`docs/history/whatsapp-live-roundtrip.md`) worked,
so the handler was believed done. In real use it mostly did not reply. The
full offline suite was green throughout — 137 passing tests never caught any
of this, because each bug only appears against a real long-running process, a
real database, or real conversational content.

## Bug 1 — migration `0002` was never applied live

`docs/state.md` listed this as an open blocker but nothing connected it to
"no replies". The live `jobs` table had no `attempts` column, so
`retry_or_dead_letter_job` failed with
`postgrest.exceptions.APIError: column jobs.attempts does not exist`. The
happy path never touches those columns, which is why the very first live test
passed. The moment any job failed once, the retry mechanism *itself* failed,
and the job stayed `running` forever — four of the user's messages were
stranded that way.

Applied by the user through Supabase's SQL Editor. Confirmed by reading back
`attempts`/`max_attempts`/`timeout_seconds` on live rows, after which stuck
jobs began being reclaimed by the stale-lease branch of `claim_next_job`.

## Bug 2 — `_install_compact_extraction_prompt()` was not idempotent

The drift guard refuses to patch if `mem0.memory.main.ADDITIVE_EXTRACTION_PROMPT`
is shorter than `_SHIPPED_PROMPT_MINIMUM_LENGTH` (20k chars). After the first
patch in a process, the module global *is* the ~2.4k-character compact
prompt, so every later call saw its own earlier patch and raised
`Mem0WrapperError: ... missing or unexpectedly short`.

The executor is one long-running process that opens a fresh `Memory` per job,
so exactly one message per executor restart could ever succeed. Reproduced
directly: two `remember()` calls in one process, first `OK in 5.1s`, second
`Mem0WrapperError after 0.5s`.

Fixed by returning early when the global already equals
`COMPACT_ADDITIVE_EXTRACTION_PROMPT`. Regression test:
`test_install_compact_extraction_prompt_is_idempotent_within_one_process`.
Verified live: three consecutive `remember()` calls in one process all
succeeded (5.9s, 10.3s, 11.5s).

## Bug 3 — `max_tokens=128` truncated real extraction JSON

`max_tokens` maps to Ollama's `num_predict`. 128 was tuned against a
single-sentence synthetic test fact. Real conversation turns produce several
facts with longer text fields, and generation was cut off mid-string:

```
pydantic_core.ValidationError: Invalid JSON: EOF while parsing a string at line 1 column 399
  input_value='{"memory": [{"id": "9", ...istant", "linked_memory'
```

The validating retry then burned both attempts on the same truncation and
raised. Whether a given message worked was pure luck of output length.
Raised to 512, which still bounds generation well under mem0's 2000 default.

## The amendment: reply first, then remember

Blueprint step 1.4 specified recall -> route -> remember -> send. Local CPU
fact extraction costs 60-130s per call and runs twice per message, so that
order made every reply wait on the slowest component in the system, and any
extraction failure discarded an already-generated reply and re-ran the whole
job from scratch. Raising the token cap to fix bug 3 made extraction slower
still, pushing it into the timeout instead — fixing one symptom moved the
failure rather than removing it.

Reordered to recall -> route -> **send** -> mark-sent -> remember, with the
`remember()` pair wrapped so a failure past the send is logged and the job
still completes. Rationale: once the reply is delivered and deduped, a retry
can only re-run extraction forever — it cannot resend. Losing one
conversation turn from memory is the smaller loss.

**This deviates from the blueprint and was authorized by the user on
26 August 2026** after repeated live dead-letters traced to extraction alone.
It is recorded here rather than silently applied. Tests:
`test_the_reply_is_sent_before_memory_is_written` and
`test_a_memory_write_failure_after_sending_does_not_fail_the_job`.

## What this says about the tests

Every one of these passed the offline suite. The gap is that the suite fakes
memory, routing, and sending — correctly, for unit tests — so it cannot see
process-lifetime state (bug 2), live schema drift (bug 1), or real model
output length (bug 3). The thing that actually found all three was replaying
real failing job payloads through the real handler with only the *send*
faked. That technique belongs in the toolkit for anything that works in a
test and fails in the field.

Full offline suite after the fixes: **150 passed, 1 deselected**.

## Postscript — two more causes found the same evening

**A backfill run was starving replies.** A parallel session started
`tools/run_backfill.py --user-id 923000413777` over the opted-in intake
folder. It drives the same single local Ollama that every reply depends on,
so inbound messages sat `queued` with `attempts=0` — never claimed — while
the batch job held the model. Eight messages piled up. Killing the backfill
(it is resumable, so nothing was lost) drained the backlog immediately.

Worth stating plainly because nothing in the design prevents a recurrence:
**Ollama is a single shared serial resource, and any batch job that uses it
will block live replies for as long as it runs.** Backfill and conversation
cannot both run on this machine.

**Memory writes were failing 100% of the time.** Once the backfill was out of
the way, every drained job still logged `reply sent but memory write failed`.
Not one succeeded. Each failure cost ~20s of timeout before giving up, on
every message, for zero benefit. `remember()` is now gated behind
`JARVIS_MEMORY_WRITES` (default off) — the writes were pure latency with a 0%
success rate. `recall()` is unaffected: it is an embedding lookup, not
extraction, and stays on, so anything already in `memory.db` is still used.

Result after both changes: the 11-message backlog drained clean with no
errors in the log.

The honest position is that Phase 1's memory goal is **not met on this
hardware**. Local fact extraction with `llama3.1:8b` on CPU cannot keep up
with conversation. The wrapper, store, index, and dedup are all correct and
tested; the model is too slow. That is a hardware/model-choice problem, not a
code problem, and it is recorded in `docs/state.md` as the open blocker it
is rather than being papered over with a longer timeout.
