# Test-coverage batch 1

Four independent, disjoint-file jobs from `docs/plan.md`'s "Available now" /
"Tests for things that have none" lists. Claimed as one lane
(`work-item: test-coverage-batch-1`, claim tool) because each piece is small
enough that separate dispatches would cost more than doing them together.
BUILD role: do not commit, do not touch `requirements.txt` (append deps to
`docs/tasks/deps-test-coverage-batch-1.txt` if any are needed — none should
be).

## 1. `reframe-archived-consults`

Files: `docs/consults/2026-08-27-distill-scheduling-mechanism/response.md`,
`docs/consults/2026-08-27-path-smoke-test/response.md`.

Both predate the `tools/consult.py` fix that frames sub-model output as
untrusted at every exit (`UNTRUSTED_OPEN`/`UNTRUSTED_CLOSE`/`UNTRUSTED_NOTICE`,
`frame_untrusted()` — see `tools/consult.py` and
`docs/blockers/tool-result-injection.md`'s "What was fixed" section for the
exact framing shape). Wrap each file's existing content in that same framing
so a future agent reading either file off disk sees it marked as untrusted
data, not live instructions. Do not alter the substantive content, only add
the frame. `path-smoke-test/response.md` is itself a description of a prompt-
injection-adjacent bug (prompt truncation) — frame it too, for consistency,
even though it's about the tool rather than a live decision.

## 2. `test-distill-memory-cli`

New file: `tests/tools/test_distill_memory.py`. `tools/distill_memory.py` has
zero tests. Its structural twin, `tools/run_backfill.py`, has seven — read
that twin's tests (find them via `tests/tools/test_run_backfill.py` if it
exists, or grep for `run_backfill` under `tests/`) and mirror the pattern:
same kind of heartbeat-guard test, same kind of `--force`/`--dry-run`
behavior test, same kind of argument-parsing test. `tools/distill_memory.py`
remains the manual path for the distill chain and is still heartbeat-guarded
per `docs/state.md`'s "Batch distillation" row — a batch tool refusing while
`executor/heartbeat.py`'s heartbeat is fresh is the core invariant to prove,
plus `--dry-run` never being blocked.

## 3. `test-start-jarvis-uncovered-paths`

New file: `tests/tools/test_start_jarvis.py` (or extend if one already
exists — check first). `tools/start_jarvis.py` has these untested paths per
`docs/plan.md`:
- `resolves_on_public_dns` — guards the ISP-DNS false-negative; read
  `docs/state.md`'s "Startup" row for why this check exists (QUIC/DNS
  resolution issues with the Cloudflare tunnel).
- `tunnel_protocol()` — reads `JARVIS_TUNNEL_PROTOCOL`, defaults matter
  (http2 is forced because QUIC is unroutable on this network — see
  `docs/state.md` "Startup").
- `wait_for_tunnel_url` — the polling loop that waits for cloudflared to
  mint a URL.
- shutdown deadline — the Ctrl+C / child-death handling described in
  `docs/state.md`'s "Startup" and "Single-instance guard" rows.

Test these as pure functions against fakes/mocks — no real network calls, no
real subprocess launches of cloudflared/uvicorn.

## 4. `bus-branch-test-gaps`

Files: `tests/bus/test_whatsapp_client.py`, `tests/test_integration.py`.
Untested branches in `bus/whatsapp_client.py`'s `WhatsAppClient`:
- the timeout path (an outbound send that times out)
- a non-JSON error body from the Graph API
- `_default_jobs()`'s fallback behavior in `tests/test_integration.py`

Read `bus/whatsapp_client.py` and the existing tests in both files first to
match established fake/mock patterns rather than introducing new ones.
`bus/whatsapp_client.py` itself is a hot file per `docs/plan.md` — you are
not editing it, only adding tests against its existing public behavior.

## Verification

After all four: run the full offline suite exactly as CLAUDE.md specifies:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp --ignore=tests/db/test_jobs_integration.py
```

Cite the output. Do not report done without it. Do not commit — report back
with a summary of what was added, the exact test counts before/after, and
anything specified above that you could not complete (with why).
