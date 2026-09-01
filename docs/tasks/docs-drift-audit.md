# Lane: `docs-drift-audit`

Role: **BUILD**. Do not commit. Claim ID `ff3813ec243541319123eae2825d008b`
is already held for you. Do **not** re-claim, do **not** release it.

## Why this exists

`docs/plan.md` says of `facts-check-job`:

> the blueprint's only defence against its own rot and has produced nothing in
> four days.

Building that job is **Class C** — `docs/plan.md`'s Decisions section says its
scheduling (numbered Phase 0.8 with an owner, or cut) is the user's call, and
CLI-vs-job-kind follows from the answer. **Do not build it.**

This lane does the thing that job would have done, once, by hand: check every
falsifiable claim in the docs against the actual tree, and report the drift.
The output is a report. **You change no documentation and no code.**

## Files you own

Write exactly one file:

```
docs/tasks/docs-drift-audit-report.md
```

Everything else is **read-only to you**, including every file you are
auditing. Two other lanes are editing files concurrently. If you find drift,
you write it down; you do not fix it.

## What to audit

Four documents. For each, extract the claims that are *falsifiable against the
tree* and check them.

1. **`docs/state.md`** — the "Built and working" table, "Provider rungs",
   "Open blockers", "This machine and network". Highest value.
2. **`docs/plan.md`** — every row marked `~~done~~` with a commit hash, and
   every row **not** struck through. Both directions drift.
3. **`docs/context.md`** — the hand-written part only. **Do not audit the
   generated block** between the `BEGIN GENERATED` / `END GENERATED` markers;
   it is produced by `tools/context_status.py` and was regenerated today.
4. **`docs/blueprint.md`** — audit **only** its factual claims about the tree
   (does this module exist, is this wired). Its architecture, component
   choices, dependency selection and phase ordering are **decisions, not
   claims** — per `agents.md` you must not flag those as drift, and must not
   propose substituting any of them.

## What counts as drift, and what does not

Check things a command can settle. Examples of the shape:

- A row says a component is registered — is it actually in
  `executor/poller.py`'s `DEFAULT_HANDLERS`?
- A row cites a file, class, function or line number — does it still exist at
  that name? Line numbers rot fastest; check them.
- A row says something is tested — does a test actually exist and does it
  assert what the row claims?
- A row cites a commit hash — does `git show --stat <hash>` actually contain
  the change described?
- A row says something is "in flight" or "blocked" — is it, still?
- A count (tests, migrations, providers) — recount it.
- A row says X has no producer / no caller — `grep` and confirm.

**Not drift, do not report as such:**

- Anything in `docs/history/`. It is append-only and deliberately preserves
  superseded conclusions, *including wrong ones*, because the reasoning is the
  value. Do not audit it, do not correct it.
- Provider pricing, rate limits, model availability and free-tier claims. Per
  `agents.md` these are claims to re-verify against current sources — but
  verifying them **spends real provider allowance**, which is an exclusive
  resource this lane has not claimed. **Do not call any provider.** If a
  pricing/limit claim looks stale on its face, list it under "not checked, and
  why".
- A blueprint architecture or component decision you disagree with.

## Method

Read-only commands only. `grep`, `git log`, `git show`, `git grep`,
`pytest --collect-only`, reading files. Suggested starting points:

```
git log --oneline -25
git show --stat <hash>
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-audit --collect-only --ignore=tests/db/test_jobs_integration.py
```

Use `--basetemp=.pytest-basetemp-audit`. Two other lanes are running suites
concurrently and must not share your scratch directory.

## Hard constraints

- **Read-only against everything live.** Do not start the bus, the executor,
  Ollama, `whisper-server`, or a tunnel. Do not touch the live Supabase `jobs`
  table. Do not call a provider. Do not run `tools/repoint_webhook.py`.
- **Do not run the mic, speakers, or any UIA automation.** Those are exclusive
  physical resources and this lane has not claimed them.
- Do not read `.env`. Do not print, echo, log or request any secret. If you
  need to know whether a key is *present*, check key names only, never values.
- Never `git stash`. The tree is shared live with concurrent lanes.
- `.pytest_cache/` and `.pytest-typing-diagnosis/` at the repo root are
  **unreadable** on this machine (`Permission denied`) — expected, not a
  finding. Note it and move on.

## Report format

`docs/tasks/docs-drift-audit-report.md`. Rank by consequence, not by file.
For each finding:

| field | content |
|---|---|
| where | file and the exact quoted claim |
| status | `DRIFTED` / `CONFIRMED` / `UNVERIFIABLE` |
| evidence | the command you ran and its **actual pasted output** |
| consequence | what a reader would do wrong because of it |

Then three summary sections:

- **Worst drift first** — the claims that would actually mislead someone into
  wrong work. This is the section that gets read.
- **Confirmed accurate** — a compact list, no evidence dumps. This matters:
  it tells the reader which parts of the docs they can still trust.
- **Not checked, and why** — everything you deliberately did not verify
  because it needed a resource you had not claimed.

A claim you assert without pasting the command output is not a finding. If you
find nothing wrong in a document, say so plainly — "no drift found" is a real
and useful result here, not a failure.
