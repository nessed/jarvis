# Phase 1 archive: local-first memory and conversation wiring

> Frozen archive. Nothing in this file is edited once written. If a fact here
> stops being true, the live version belongs in `docs/state.md`, and what is in
> flight right now belongs in `docs/context.md`.

Diagnostic history is kept verbatim, superseded conclusions included,
because the reasoning is the value.

## Conversation wiring — whatsapp_webhook handler (26 August 2026)

Blueprint step 1.4, the gap the previous entry in this file flagged as the
actual remaining work once the send client and token were both ready.

- **`executor/handlers/whatsapp.py`** (new module):
  `parse_inbound_text_message(payload)` reads a raw Meta webhook payload
  (`entry[].changes[].value.messages[]`) and returns an `InboundMessage
  (sender, text)` for the first inbound text message, or `None` for anything
  else Meta sends to the same webhook — delivery/read status callbacks,
  non-text message types (image/audio/reaction/...), and malformed/empty
  payloads are all silent no-ops, not errors.
  `build_whatsapp_webhook_handler(*, open_memory, complete, send_text_message)`
  returns a plain `JobHandler` closure: `memory.recall(text, user_id=sender)`
  → build a system+context+user message list → `router.route("latency",
  messages, urgent=True)` → `memory.remember()` twice (user turn, then
  assistant turn) → `WhatsAppClient.send_text_message()`. `user_id=sender`
  (the WhatsApp phone number) gives each conversation its own recall/remember
  scope in Mem0. All three dependencies default to the real
  `open_local_mem0_memory` / `router.route` / `WhatsAppClient` but are
  injectable, so the handler is unit-tested without Ollama, a live provider,
  or the Graph API. No new error handling was added on top of what the
  poller already does: recall/route/send failures propagate unchanged into
  the existing retry/backoff/dead-letter path with a type-only diagnostic.
- **Registered** in `executor/poller.py`'s `DEFAULT_HANDLERS["whatsapp_webhook"]`
  — no longer the empty registry described below. `memory_extract` still has
  no handler; nothing enqueues that kind separately, since this handler calls
  `recall()`/`remember()` inline rather than dispatching a second job.
- Tests: `executor/handlers/whatsapp.py` is new; `tests/executor/test_whatsapp_handler.py`
  is new (payload parsing incl. status-only and non-text payloads; the
  no-inbound-message no-op path; the full recall→route→remember→send flow
  with fake dependencies; an unexpected-completion-shape guard so a malformed
  provider response raises instead of sending garbage to the user). Full
  offline suite: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
  --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py` →
  **125 passed, 1 deselected** (117 prior + 8 new).
- **Not yet done:** no real message has been sent or received through this
  handler — only fake-dependency unit tests. That is the next live
  acceptance step (send a real WhatsApp message to the test number and
  confirm a reply arrives), not a build gap.
- The plain `pytest -m pytest -q --ignore=...` form in `CLAUDE.md` fails in
  this environment with `PermissionError` against the system `TEMP` dir; the
  working invocation adds `-p no:cacheprovider --basetemp=.pytest-basetemp`,
  matching `.githooks/pre-commit`. Worth fixing the documented command if it
  keeps tripping this up.

## Queue durability — attempts, backoff, dead-letter (landed & committed, 8fb271f)

Built and tested; **not yet live**. Full design in
`docs/tasks/queue_durability.md`, handoff detail in
`docs/handoff/queue_durability.md`.

- **Handler registry at startup.** `executor/poller.py` adds
  `HandlerRegistration(handler, timeout_seconds)` and `DEFAULT_HANDLERS`
  (now carrying one entry, `whatsapp_webhook` — see "Conversation wiring"
  above), built once in `main()` and
  passed to every `poll_once` call. An unregistered kind raises before any
  checkpoint/dispatch, logs at `WARNING` with only the job id, and is routed
  through the same retry/backoff/dead-letter path as any other failure — it
  never crashes the poll loop.
- **Schema** (`db/migrations/0002_job_retries.sql`, additive only): adds
  `attempts`, `max_attempts` (default 5, overridable via
  `enqueue(..., max_attempts=...)`), `timeout_seconds` (default 300), and a
  `dead_letter` status. New RPCs `retry_or_dead_letter_job` and
  `set_job_timeout`.
- **Backoff:** `backoff_seconds(attempts) = min(300, 5 * 2**(attempts-1))` —
  base 5s, cap 5 minutes.
- **Per-job timeout:** the handler runs on a daemon `threading.Thread`; on
  timeout the poller retries immediately without waiting for the orphaned
  thread. The claimed row's `timeout_seconds` is pushed from the registry
  right after claim, so the DB's own stale-lease check uses the real per-kind
  value.
- **Crash-mid-run recovery:** `claim_next_job` also reclaims a `running` row
  whose lease (`updated_at + timeout_seconds`) has expired, and dead-letters
  it instead if `max_attempts` is already exhausted — this is what actually
  recovers a job when the whole executor process dies, not just a hung
  handler.
- **Atomic single-claim semantics preserved:** same single-statement
  `for update skip locked` shape, wider `WHERE`. Proven with an in-memory
  16-thread/8-job lock-based test (always runs) and a live-Supabase-gated
  integration test (skips until `0002` is applied).
- **`/status` gains `retry_health()`** (`{"dead_letter_count", "retried_job_count"}`)
  as an optional, default-`None` dependency on `bus/status.py`'s
  `status_payload`/`create_status_handler` — every existing call is
  byte-identical unless a caller opts in.
- Tests: `.venv\Scripts\python.exe -m pytest -q tests/executor tests/db` →
  **31 passed, 1 skipped** (the skip is the live-concurrency integration test,
  self-skipping because `0002` isn't applied live yet).

What is needed:

1. Apply `db/migrations/0002_job_retries.sql` to the live Supabase project
   (needs a Postgres driver or Supabase/psql CLI not currently in the venv —
   requires a `requirements.txt` change plus an explicit live-schema-write
   authorization, neither of which this lane could do on its own).
2. Wire `retry_health=` into the actual `/status` route in `bus/main.py`
   (same pattern as the existing `queue_depths`/`last_job` wiring).
3. Register `memory_extract` (and any other real kind) in
   `DEFAULT_HANDLERS` — deliberately left undone; this lane built mechanism
   only.
4. One orphaned probe row (`kind` prefixed `queue-durability-probe-`, status
   `running`) remains in the live `jobs` table from an early version of a
   test's schema-readiness probe, before it had a cleanup-on-failure path.
   Harmless (unique disposable kind), not manually swept.

## Phase 1 — Mem0 wrapper and extraction-timeout fix

The authorized custom `SQLiteVecMem0Store` (delegating to the existing SQLite
fact store and sqlite-vec index, no Qdrant/Chroma/FAISS substitution) is
implemented in `memory/mem0_wrapper.py` and committed in `8fb271f`, including
the validating-retry wrapper around Mem0's Ollama adapter (one retry on
schema-validation failure, then a clear `Mem0WrapperError`) and a bounded
`OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS` (default 30) that fails closed.

**Superseded diagnostic history (25 August 2026, before root cause was
found):** an early synthetic (non-personal, 10-sentence) comparison found
`qwen3:4b` and `llama3.1:8b` both schema-conforming 10/10 and picked
`llama3.1:8b` on raw-JSON latency (17.4s vs. Qwen's 20.1s timeout); a full
live-Mem0 smoke with real extraction then timed out for both models
regardless of choice; an async-memory dispatch was blocked pending the
queue/executor lane (now landed, see above); and a real-prompt cold-run
measurement confirmed the extraction call itself timed out at exactly 300.018s
with `num_ctx=16384`. All of these conclusions are superseded by the root
cause below; full exact commands/output are preserved in git history at
`3256779` if needed.

**Root cause (confirmed against installed mem0ai 2.0.19 source, not docs):**
`Memory.add`/`AsyncMemory.add` (`mem0/memory/main.py:942` and `:2604`) hardcode
`system_prompt = ADDITIVE_EXTRACTION_PROMPT` — a 33,653-character prompt — as
a bare module-global read inside the only LLM-extraction path in this version.
No supported config or argument selects a shorter prompt:
`mem0.memory.utils.get_fact_retrieval_messages`/`_legacy` and
`USER_MEMORY_EXTRACTION_PROMPT`/`FACT_RETRIEVAL_PROMPT` are unreferenced dead
code in `main.py`, and `MemoryConfig.version` is telemetry-only.
`mem0/llms/ollama.py`'s `OllamaLLM.generate_response` builds its Ollama
`options` from only `temperature`/`max_tokens`/`top_p` — `num_ctx` and
`keep_alive` are not reachable through Mem0's shipped Ollama adapter at all.
Literal "subclass Memory and override the system prompt" is not mechanically
available (the prompt is a local variable inside one ~250-line method, not an
overridable attribute) — reported rather than reimplementing Mem0's pipeline.

**Fix landed, uncommitted:** `memory/mem0_wrapper.py` now defines
`COMPACT_ADDITIVE_EXTRACTION_PROMPT` (2,419 characters, a 93% reduction) and
`_install_compact_extraction_prompt()`, called before `Memory` is constructed,
which reassigns the module global `mem0.memory.main.ADDITIVE_EXTRACTION_PROMPT`
at runtime — no site-packages edit, no LLM-adapter replacement, and the exact
`{"memory": [...]}` output contract the wrapper's `ExtractionResponse` model
requires is preserved (the shipped lighter prompts use an incompatible
`{"facts": [...]}` shape and were deliberately not used verbatim). A drift
guard (`_SHIPPED_PROMPT_MINIMUM_LENGTH = 20_000`) refuses to patch if a future
mem0ai upgrade already shrank the shipped prompt. `LlmConfig` now also sets
`max_tokens=128` (previously unset, defaulted to 2000).

**Re-measurement** (raw `ollama` client calls against the real compact system
prompt + the real `generate_additive_extraction_prompt` user prompt, since
Mem0's adapter can't accept `num_ctx`/`keep_alive` through any config): warm,
`keep_alive=-1`, `num_predict=128`, `num_ctx=2048` (sized from the actual
~2,677-character prompt, 8x smaller than the previous 16384) —
**5.998 seconds** (`prompt_eval_duration` 159ms for 636 prompt tokens,
`eval_duration` 5.82s for 38 generated tokens, CPU-only Ollama). This is well
under the ~15s gate, so the fair ten-run comparison ran with identical
prompt/caps for both models: **llama3.1:8b — 10/10 schema-valid, median
6.313s**; **qwen3:4b — 0/10 schema-valid, median 11.770s** (every run hit
`"done_reason":"length"` with its 128-token budget consumed by Qwen3's hidden
`thinking` output before any JSON content). `DEFAULT_FACT_EXTRACTION_MODEL`
stays `llama3.1:8b`, now confirmed by this fair comparison. Focused tests:
`.venv\Scripts\python.exe -m pytest -q tests\memory` → **44 passed**.

**Live end-to-end smoke, 26 August 2026 (passed, after one more fix):** ran
the actual wrapper entry point, not raw `ollama` calls. Command:
`PYTHONPATH=. .venv/Scripts/python.exe -c "from memory.runtime import open_local_mem0_memory; runtime = open_local_mem0_memory('memory/mem0-smoke-compact-prompt.db', environ={'OLLAMA_EMBEDDING_MODEL': 'nomic-embed-text', 'OLLAMA_BASE_URL': 'http://127.0.0.1:11434', 'OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS': '60'}); runtime.remember('The generic workshop opens at nine.'); runtime.recall('When does the generic workshop open?'); runtime.close()"`.
`remember()` succeeded first try: `35.146s` (cold — Ollama had just been
(re)started for this test, consistent with the earlier ~36s cold measurement),
returning `{'results': [{'id': '...', 'memory': 'The generic workshop opens at
nine', 'event': 'ADD'}]}` — the compact prompt correctly drove real
extraction end-to-end.

`recall()` then failed with `ValueError: Top-level entity parameters
frozenset({'user_id'}) are not supported in search(). Use
filters={'user_id': '...'} instead.` — a second, independent bug in
`memory/mem0_wrapper.py`'s `Mem0Memory.recall()`, unrelated to the extraction
prompt: it called `self._memory.search(query, user_id=user_id, limit=limit)`,
but installed mem0ai 2.0.19's `Memory.search(query, *, top_k=20,
filters=None, ...)` rejects `user_id`/`agent_id`/`run_id` as top-level kwargs
and has no `limit` parameter at all (the count parameter is `top_k`; the old
call's `limit=limit` was silently absorbed into unused `**kwargs`). Fixed,
uncommitted, in the same file: `search(query, filters={"user_id": user_id},
top_k=limit)`. Added regression test
`test_mem0_recall_passes_user_id_through_filters_not_as_a_top_level_kwarg`
(fake-memory call-shape assertion, no live Ollama needed). Re-ran the same
smoke command's `recall()` call after the fix: `RECALLED {'results':
[{'id': 'dde54620-76f3-4bea-9955-9d4d217bf689', 'memory': 'The generic
workshop opens at nine', 'hash': '4fedaf9ba4b65ce58fd365981f3214ff',
'metadata': {'_mem0_collection': 'jarvis_memories'}, 'score':
0.7087123951006583, 'created_at': '2026-08-25T20:53:24.009514+00:00',
'updated_at': '2026-08-25T20:53:24.009514+00:00', 'user_id': 'jarvis',
'attributed_to': 'user'}]}` — round trip confirmed. The temporary
`memory/mem0-smoke-compact-prompt.db` and
`memory/mem0-smoke-compact-prompt.mem0-history.db` were deleted after this
result was recorded. No personal data was read or ingested. Focused tests:
`.venv\Scripts\python.exe -m pytest -q tests\memory` → **45 passed**.

**Locked in as a runnable probe.** The manual smoke command above is now
`tests/live/test_memory_roundtrip.py`, marked `live` and excluded from the
default run. Run it with
`.venv\Scripts\python.exe -m pytest -q -m live tests/live`. Until it existed,
Phase 1's actual success criterion was a transcript in this file rather than
something anyone could re-execute.

## Phase 1 offline foundations

- The local-only resumable backfill runner is complete. It accepts only a
  caller-selected, manifest-verified source, persists through an injected
  sink, and advances its serializable checkpoint only after a successful write.
  It supports resume and rejects mismatched, negative, or out-of-bounds
  checkpoints. Focused ingestion tests: **11 passed**.
- The executor dispatches registered job kinds through an injected seam.
  Unknown kinds fail deterministically with type-only safe diagnostics and no
  payload/provider leakage (now additionally routed through retry/backoff/
  dead-letter — see queue durability above). Focused executor tests: **9
  passed** pre-durability-lane; **31 passed, 1 skipped** for
  `tests/executor tests/db` combined after it landed.
- The local-memory runtime lane is complete: startup performs its fixed,
  non-personal dimension probe before constructing stores, handles explicit
  environment configuration, and closes resources on partial initialization
  failure. Offline focused memory tests: **31 passed** (pre-Mem0-wrapper
  baseline); **44 passed** with the Mem0 wrapper and timeout fix (see above).
- Offline integration validation passed on 25 August 2026:
  `.venv\\Scripts\\python.exe -m pytest -q --ignore=tests/db/test_jobs_integration.py`
  completed **82 passed in 3.46s**. The excluded file is credential/live-
  Supabase dependent. An earlier broad run reached that test but failed before
  connecting with `WinError 10013`; it made no external change. That same test
  flaked once more during the queue-durability lane's combined run and passed
  on every isolated and subsequent rerun — a known characteristic of the live
  network dependency, not a regression.
- Pull-based Phase 0 executor is implemented and running locally. It atomically
  claims one job, checkpoints it, then completes it; transient repository errors
  are retried with type-only diagnostics. A live disposable probe completed
  queued → running → done on 24 August 2026.
