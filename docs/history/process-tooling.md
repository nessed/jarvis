# Process tooling archive: 26 August 2026

> Frozen archive. Nothing in this file is edited once written. If a fact here
> stops being true, the live version belongs in `docs/state.md`, and what is in
> flight right now belongs in `docs/context.md`.

## Process tooling (26 August 2026)

Three human touchpoints were replaced with mechanism. Rules in `agents.md`
changed to match; see its "Before you stop, classify the stop" and "Tools that
replace a human step" sections.

- **`tools/consult.py`** — headless `claude -p` second opinion, replacing the
  manual copy-terminal-output-into-a-browser relay. Returns
  `{verdict, reasoning, confidence, what_would_change_this}` and saves the
  exchange under `docs/consults/`. Attachments are screened against live `.env`
  values and known key shapes before sending; `.env` itself is refused.
  Verified: a real `META_ACCESS_TOKEN` planted in an attached file was replaced
  with `<redacted:META_ACCESS_TOKEN>` and reported by name only; a live call
  returned a parsed high-confidence verdict.
- **`tools/repoint_webhook.py`** — re-points Meta's callback at the current
  tunnel via `POST /{app-id}/subscriptions`, replacing the per-restart
  dashboard trip (the same dashboard with the known rendering bug). Probes the
  tunnel before changing anything and reads the subscription back to confirm.
  Verified: `--check` returned the live callback
  `https://gas-clubs-pennsylvania-farming.trycloudflare.com/webhook`. The POST
  path is unexercised — no tunnel was running at the time.
- **`tests/live/`** — phase acceptance probes behind a `live` pytest marker,
  configured in the new `pytest.ini` (default run is `-m "not live"`).

The rules were also made to actually load, which they previously did not:

- **`CLAUDE.md`** now imports `agents.md`. There was no `CLAUDE.md` before, so
  nothing loaded the rules file automatically — it bound only when an agent
  happened to open it. Verified by a clean headless session instructed not to
  read any files, which named the three stop classes and both new scripts from
  context alone.
- **`.githooks/pre-commit`**, with `core.hooksPath` set to `.githooks`, runs the
  full offline suite and refuses a red commit. It pins `--basetemp` inside the
  repo so an unwritable system TMP cannot masquerade as a failing suite.
  Verified by deliberately breaking a test: the commit was blocked and nothing
  landed. This is the only rule in the set that is mechanically enforced rather
  than instruction-followed. A fresh clone needs
  `git config core.hooksPath .githooks` once; `README.md` and `CLAUDE.md` both
  say so.
- **`.claude/settings.json`** allowlists pytest, `consult.py` and
  `repoint_webhook.py` so they run without a permission prompt, and denies
  reading `.env` and `memory.db`.

`docs/workflow_overview.md` §12 records what this changed against the 25 August
baseline, including what was deliberately not addressed.

**Regression fixed:** `tests/test_integration.py`'s `FakeJobs.enqueue` was
still on the pre-`8fb271f` signature, so the full suite was red at `HEAD` while
the focused `tests\memory` run cited in this file was green. A `JobRepository`
Protocol widened in the queue-durability lane; its test double lived in a file
no lane owned. `agents.md` now requires the full offline suite before any
commit, and requires a lane changing a shared interface to name every
implementer including doubles it cannot edit. Full offline suite:
`.venv\Scripts\python.exe -m pytest -q --ignore=tests/db/test_jobs_integration.py`
-> **117 passed, 1 deselected**.
