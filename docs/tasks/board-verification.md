# Lane brief: board-verification (read-only)

Dispatched 1 Sep 2026 by CORE during the board rebuild. Model: Opus 5.

## Task

Adversarially verify the freshly written `docs/board/` against the actual
tree at the current working state. Read-only: edit nothing, report only.

Check, with a file/line or command citation per verdict:

1. Every `ready` task in `docs/board/tasks/`: does its premise hold? (e.g.
   `voice-loop` claims no local Pipecat loop exists in `voice/`; the
   replay harness claims `tools/replay_job.py` doesn't exist and that
   `build_whatsapp_webhook_handler` injects its outbound send;
   `facts-check-tool` claims no such tool exists; `pytest-addopts` claims
   `pytest.ini` lacks those addopts; `phase4-prep` claims `infra/` is
   effectively empty.)
2. Every "done/exists" assertion the board relies on: `memory/review.py` +
   `tools/review_facts.py` + `ingest/noise.py` exist and are wired (the
   board treats fact-review and noise-filter as landed);
   `executor/poller.py`'s `--kind` takes exactly one value; the four
   action kinds are registered with no producer; the two live workers are
   pinned to `whatsapp_webhook` / `distill_memory`.
3. `docs/board/README.md`'s NEXT list vs the task files: ids match, every
   listed id has a file, statuses/gates in files match the list.
4. `docs/board/QUESTIONS.md` claims: the five missing `*_DEFAULT_MODEL`
   keys are still absent from `.env` (**check key names only — never read
   or print values**); `providers.yaml` resolves them via `${VAR}` with no
   fallback.
5. Frontmatter `files:` lists vs plan.md's hot-file and test-double rules:
   flag any task that touches a hot file without saying so.

## Constraints

- Read-only. No edits, no claims beyond this brief, no `.env` value reads.
- Return a numbered findings list: VERDICT (holds / wrong / imprecise) +
  citation + suggested one-line correction where wrong. An empty report is
  a failed verification — if everything holds, say so per item with the
  citation that proves it.

## Report (lane returned 1 Sep 2026, Opus 5, read-only — condensed by CORE)

37 checks: 24 hold outright, 4 wrong, 9 imprecise. Nothing fabricated —
every load-bearing number reproduced exactly (17/7/2 FLP split, 28
flp_inspect tests, backfill chunk index 1, the exact five `${VAR}` rungs
with no fallback at `router/routing.py:130-133`, zero producers for the
four action kinds, workers pinned at `tools/start_jarvis.py:503-529`).

Wrong, all fixed by CORE same day:
1. `voice-loop` quoted a 6-state machine against blueprint §5's 7 states
   → now carries all seven, conversational subset active.
2. `pyflp-parse-failures` called the IndexError project "separate" — it is
   `spaceship demo`, one of the 17 "clean" parses (audit never iterated
   channels) → corrected.
3. Three stub tasks hid hot files behind directory globs
   (`cloud-routine-wire`, `bus-offbox-packaging`, `db-maintenance`) →
   frontmatter expanded with explicit `(hot)` markers.
4. Board resource keys (`ollama-extract`, `ollama-embed`,
   `microphone-speakers`, `live-jobs-table`) were undefined in plan.md's
   exclusive-resources rules → canonical key list added there.

Imprecisions fixed: README provenance hash (`3695c05` → `bf15f79`), three
NEXT gate annotations missing task deps, "unblocks 9" → 6 immediate + 3
behind deps, `lane:` vs `--role` confusion noted in README, phase4-prep's
auto-terminate claim re-sourced to the 27 Aug audit and its web-UI
exclusion made explicit, `enqueue-classifier` scope-narrowing vs plan.md
recorded, `tests/router/test_routing.py` marked area-hot.
