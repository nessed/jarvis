# Lane: `live-schema-drift-guard`

Role: **BUILD**. Do not commit. Claim ID `89d4106cdb7f469c8b9f042fd15cf779`
is already held for you by the orchestrator — do **not** re-claim, do **not**
release it. Report back and CORE releases it.

## Why this exists

`docs/plan.md` lists this under **Barriers**:

> `tests/db/test_jobs_integration.py:114` calls `pytest.skip` on exactly the
> condition it exists to catch, and the file is `--ignore`d by both the
> documented command and the pre-commit hook. It has never run and cannot go
> red.

Confirmed in the current tree. `_live_repository_with_0002_applied()` wraps
its claim/retry probe in `try/except Exception`, and on **any** exception
calls `pytest.skip("0002 migration ... is not applied to the live Supabase
project yet")`. But `docs/state.md` records that migrations `0001` **and**
`0002` are already applied live. So the one condition this file exists to
detect — the live schema having drifted from what the code expects — is
converted into a green skip.

The `except Exception` is also indiscriminate. A transient network failure is
a documented fact of this machine: `docs/state.md` records Supabase
"intermittently flaky here, occasionally failing TLS with `WinError 10054`
for minutes at a time". Today that reads as "migration not applied", which is
a different and much more alarming claim than "the network blipped".

## Files you own

Write:

```
tests/db/test_jobs_integration.py
```

**That file and nothing else.** The `--ignore=tests/db/test_jobs_integration.py`
flag appears in `CLAUDE.md` and `.githooks/pre-commit`. You do **not** own
either. Do not remove the ignore — doing so would point every lane's routine
verification command at the live Supabase project. Report on it instead.

## Scope

Make the file capable of going red. Three outcomes must be distinguishable,
and only the first may skip:

1. **No credentials configured** → skip, cleanly, as today. This is the
   ordinary offline case.
2. **Credentials present, but the connection failed** (`WinError 10054`, TLS
   error, timeout, DNS) → skip *with a message that says the network failed*,
   not that a migration is missing. Do not report an environment problem as a
   schema problem.
3. **Credentials present, connection succeeded, and the schema does not match
   what the code expects** → **fail**. This is drift. It is the entire reason
   the file exists and it must be loud.

Distinguish (2) from (3) by the exception type and shape, not by a string
match on a message you have not observed. If you cannot separate them
reliably from evidence you can actually obtain, **default to failing** — a
false red on a network blip is recoverable, a permanent green over real drift
is what this lane is fixing. State which way you went and why in your report.

## Hard constraint — read this twice

**Do not run this test against the live Supabase project.** Do not enqueue,
claim, mutate, or fail rows in the live `jobs` table. `docs/plan.md` marks the
live `jobs` table an exclusive resource and this lane has **not** claimed it.
A running executor claims from that table.

Verify your change by **constructing the failure conditions against fakes** —
build a fake repository that raises each exception shape and assert the test
helper's behaviour. If that requires the helper to be callable independently
of a live connection, refactor it so it is; that is within scope and is
probably the real fix.

## Verification — required

Your own scratch directory. Other lanes are running concurrently.

Prove the file is now *collectable and correct* without touching live
Supabase:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-drift --collect-only tests/db/test_jobs_integration.py
```

Run whatever new fake-driven tests you add:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-drift tests/db/
```

Full offline suite before you report:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-drift --ignore=tests/db/test_jobs_integration.py
```

Baseline to beat: **862 passed, 7 deselected** as of `52e2c03`.

## Report

Write `docs/tasks/live-schema-drift-guard-report.md`:

- Exact commands and their **pasted output**.
- How you separated "network failed" from "schema drifted", and the evidence
  for that separation.
- Whether the file can now go red, and the precise condition that would do it.
- Your recommendation on the `--ignore` in `CLAUDE.md` and
  `.githooks/pre-commit`, which you do not own. Say what you would change and
  what it would cost. CORE decides.
- Anything else you found and left alone.

## Rules that override anything above

- Do not commit. Do not edit `requirements.txt`.
- Never `git stash`. The working tree is shared live with concurrent lanes.
- Secrets are never printed, echoed, logged, or requested. `.env` is not read.
- If this cannot be done as specified, report the blocker and stop. Do not
  build an alternative and document it afterward.
