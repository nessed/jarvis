---
id: facts-check-tool
status: ready
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

_(empty)_
