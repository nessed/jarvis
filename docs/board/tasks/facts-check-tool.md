---
id: facts-check-tool
status: done
lane: AUTO
priority: 2
phase: 0
blocked-on: none
files: tools/facts_check.py, tests/tools/test_facts_check.py, docs/tasks/facts-check-reports/
resources: none (report runs use network read-only)
---

# facts-check-tool — the blueprint's anti-rot check

## Goal

The blueprint's "Ongoing" section specifies a monthly facts-check job and
it has never been built — it is the mechanism that would have caught the
Claude promo expiry and the Groq/Cerebras model retirements that were
wrong on the day the blueprint was written. The 1 Sep docs audit found
~12% of checkable claims drifted in four days: the empirical case.

## Steps

1. Build `tools/facts_check.py`. It maintains a checklist of volatile
   claims as data (a list in the module or a yaml beside it): Agent SDK
   billing pause, DeepSeek prices/windows, Groq/Gemini/OpenRouter model
   rosters and limits pages, Cerebras tier, Claude promo/limits, Oracle
   free-tier terms. Source URLs live with each claim.
2. Each run fetches what it can (plain HTTP GETs; anything login-gated is
   reported as "unverifiable, check by hand"), diffs against the claim's
   recorded value, and writes a dated one-page report to
   `docs/tasks/facts-check-reports/<date>.md`: changed / unchanged /
   unverifiable.
3. It never edits the blueprint — it produces the diff; blueprint edits go
   through Q10-style approval.
4. Staleness nudge with no scheduler: `board-audit`'s guide already says
   "run facts-check if the newest report is >30 days old". Print the age
   of the last report at the top of every run.
5. Tests: fake the fetcher; cover diffing, the unverifiable path, and
   report writing.
6. Run it once for real and commit the first report.

## Verification

Full offline suite green; first real report exists and is cited.

## Done when

Tool + tests + first dated report landed; `docs/state.md` process-tooling
row updated.

## Log

**2 Sep 2026 — done.**

`tools/facts_check.py` + `tests/tools/test_facts_check.py` + the first report,
`docs/tasks/facts-check-reports/2026-09-02.md`. Twelve claims, each carrying
the blueprint line it guards, a source URL, and literal markers.

It sends nothing and reads no key. Every request is an unauthenticated GET, so
there is no credential to leak and nothing here can spend money or change an
account. A login-walled or JS-rendered page is reported `unverifiable`, which
is a first-class verdict rather than a failure — a checker that quietly says
"unchanged" when it could not read the page is the exact rot this tool exists
to catch.

### Offline suite

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp
1129 passed, 9 deselected, 2 warnings in 59.30s
```

### First real run

```
.venv\Scripts\python.exe -m tools.facts_check
No previous report. This is the first facts-check run.

  unchanged     agent-sdk-billing-pause
  unverifiable  claude-weekly-promo
  unchanged     deepseek-pricing
  unchanged     deepseek-model-names
  unchanged     groq-rate-limits
  unchanged     groq-whisper-free
  changed       cerebras-free-tier
  unchanged     gemini-free-tier
  unchanged     openrouter-free-roster
  unverifiable  openrouter-limits
  unverifiable  nvidia-nim-free
  unchanged     oracle-always-free

1 changed. Report: docs\tasks\facts-check-reports\2026-09-02.md
```

### The one changed claim

**Cerebras' catalogue no longer mentions GLM.** The blueprint (`:45-46`) says
the catalogue narrowed to "gpt-oss-120b and GLM-4.7". Neither
`inference-docs.cerebras.ai/support/rate-limits` nor `.../models/overview`
mentioned GLM on 2 Sep 2026; both list `gpt-oss-120b`. If that is a real
removal, the Cerebras routing lane has one model, not two. Not fixed here —
the report is a diff, and blueprint edits are Ali's.

### Three unverifiable, each with a stated reason

- `claude-weekly-promo` — the promo expiry is announced in-product, not on a
  diffable page. Today is already past the ~Aug 31 2026 date the blueprint
  records, so it should be treated as lapsed until Ali checks his usage screen.
- `openrouter-limits` — the daily allowance is account-scoped and needs the key
  endpoint. This tool sends no credentials, by design.
- `nvidia-nim-free` — `build.nvidia.com` renders client-side, and NIM is
  geo-blocked from Pakistan, so a fetch from this machine proves nothing.

### Two of my own bugs, caught before the report was committed

Worth recording, because both would have made the tool worse than useless — a
checker that cries wolf gets ignored inside two months.

**A false `changed` on the Agent SDK pause.** The first run reported the
blueprint's most consequential claim as broken. It was not. Two faults, both
mine:

- The recorded URL was a `support.anthropic.com` article ID that now redirects
  to `support.claude.com/.../11145838-use-claude-code-with-your-pro-or-max-plan`
  — a *different* article. The Agent SDK one moved to `.../15036540-...`.
- The marker was `"pause"`. The live sentence reads *"Update June 15: We're
  **pausing** the changes to Claude Agent SDK usage described below."*
  `"pause"` is not a substring of `"pausing"`.

Both fixed; the claim now matches `"pausing the changes"` and `"still draw from
your subscription"`, and reports `unchanged` — which is the true answer. **The
billing split is still paused.**

**A whitespace bug that would have broken half the markers.**
`test_tags_are_removed_but_their_text_survives` failed on first run:
`<b>Always</b> <i>Free</i>` stripped to `"  Always   Free  "`, so the marker
`"always free"` could never match. Six of the twelve claims use multi-word
markers. `strip_markup` now collapses whitespace, and the docstring says why.

### Report dates are local, not UTC

The first run filed itself as `2026-09-01.md` at 01:00 PKT, because PKT is
UTC+5. Every other dated artifact under `docs/` is written in Ali's timezone,
and a report that looks a day stale on arrival undermines the staleness nudge
it exists to drive. Switched to `date.today()`, with the reasoning in the code.

### Staleness, without a scheduler

Nothing schedules this. Every run prints the age of the newest report first,
read from the *filename* rather than the mtime — a checkout or a rebase
rewrites mtimes and would silently reset the very clock this tool keeps.
`board-audit`'s guide already says to run it when that age passes 30 days.

### Specified but not done

`docs/state.md`'s process-tooling row. `docs/state.md` was held by the
`enqueue-classifier` lane for the whole of this task and both tasks before it;
the row is one line, and is handed to whoever holds it next.
