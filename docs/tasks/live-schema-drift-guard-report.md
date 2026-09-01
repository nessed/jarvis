# Lane report: `live-schema-drift-guard`

Role BUILD. Claim `89d4106cdb7f469c8b9f042fd15cf779`. Not released, not
committed. Files written: `tests/db/test_jobs_integration.py` only.

## The defect, and what replaced it

`_live_repository_with_0002_applied()` wrapped its probe in `except Exception`
and called `pytest.skip("0002 migration ... is not applied")` on **any**
exception. Migrations 0001 and 0002 are applied live, so the one thing the file
exists to catch became a green skip, and the machine's documented transient TLS
failures were reported as a missing migration.

The probe is now `_probe_0002_schema(repository)`. It takes the repository as an
argument, so every branch is drivable with a fake and no database. Three
outcomes, one of which may skip:

| condition | behaviour |
|---|---|
| no credentials configured | `skipif` on the test, unchanged |
| credentials present, connection never established | `pytest.skip`, message names the **network** and explicitly denies a migration cause |
| credentials present, server answered, schema wrong | the original exception propagates — **red** |

## How network failure was separated from schema drift

By exception **type**, read out of the installed source, not by string-matching
a message I had not observed.

`.venv/Lib/site-packages/postgrest/_sync/request_builder.py` — `execute()`
calls `self.session.request(...)` **outside** its `try/except`, and only
converts a non-2xx *response* into `postgrest.APIError`:

```
        r = self.session.request(
            self.http_method,
            self.path,
            json=self.json,
            params=self.params,
            headers=self.headers,
        )
        try:
            if r.is_success:
                ...
            else:
                json_obj = model_validate_json(APIErrorFromJSON, r.content)
                raise APIError(dict(json_obj))
        except ValidationError as e:
            raise APIError(generate_default_error_message(r))
```

`.venv/Lib/site-packages/postgrest/_sync/client.py:7` — that session is a plain
`httpx.Client` (`from httpx import Client, Headers, QueryParams, Timeout`).
postgrest wraps no transport exception of its own.

So the split is clean at the source:

- **never reached the server** → `httpx.TransportError`, or a bare `OSError`
  leaking from the socket/TLS layer.
- **server answered** → `postgrest.APIError`, carrying `PGRST202` for a missing
  RPC or `42703` for a missing column.

Hierarchy confirmed in the venv rather than assumed:

```
$ .venv/Scripts/python.exe -c "...tree(httpx.HTTPError)..."
HTTPError
  RequestError
    TransportError
      TimeoutException
        ConnectTimeout
        ReadTimeout
        WriteTimeout
        PoolTimeout
      NetworkError
        ReadError
        WriteError
        ConnectError
        CloseError
      ProxyError
      UnsupportedProtocol
      ProtocolError
        LocalProtocolError
        RemoteProtocolError
    DecodingError
    TooManyRedirects
  HTTPStatusError
---
TransportError is OSError? False
postgrest.APIError bases: (<class 'postgrest.exceptions.APIError'>, <class 'Exception'>, <class 'BaseException'>, <class 'object'>)
SSLError->OSError True gaierror->OSError True ConnectionResetError->OSError True
```

`WinError 10054` is `ConnectionResetError`, DNS is `socket.gaierror`, TLS is
`ssl.SSLError` — all `OSError` subclasses, none of them `httpx` types and none
of them `APIError`. There is no overlap between the two buckets.

`_is_connection_failure()` walks `__cause__` (cycle-guarded), and checks
`APIError` **first** at every level: if the server answered, no transport error
underneath it can turn the result into a skip.

### Where I defaulted to failing, and why

A 5xx from the edge during a blip (Cloudflare 502/520 with a non-JSON body)
arrives as an `APIError` whose `code` is the raw HTTP status, and I classify it
as **drift, i.e. red**. That is deliberate, per the brief's tie-break: a false
red is re-runnable in a minute, a permanent green over real drift is the bug
being fixed. Real drift never produces a 5xx-with-non-JSON-body — a missing RPC
is a 404 with a JSON `PGRST202`, a missing column a 400 with JSON — so widening
the skip to cover 5xx would only widen the blind spot. **Everything that is not
a transport-layer exception fails.**

## Can the file go red now? Proved by mutation

Yes. Verified by restoring the exact old behaviour through a pytest plugin in
my scratch dir (`_is_connection_failure` forced to always return `True`, which
is what a bare `except Exception: pytest.skip(...)` amounts to) and re-running:

```
$ PYTHONPATH="$SP" .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider \
    --basetemp=.pytest-basetemp-drift -p mutate_back_to_bare_except \
    tests/db/test_jobs_integration.py
FAILED tests/db/test_jobs_integration.py::test_probe_fails_loudly_on_schema_drift[missing retry_or_dead_letter_job RPC-retry_or_dead_letter-error0]
FAILED tests/db/test_jobs_integration.py::test_probe_fails_loudly_on_schema_drift[missing attempts column-enqueue-error1]
FAILED tests/db/test_jobs_integration.py::test_probe_fails_loudly_on_schema_drift[renamed claim RPC-claim_next-error2]
FAILED tests/db/test_jobs_integration.py::test_probe_fails_when_the_claim_rpc_returns_no_row
FAILED tests/db/test_jobs_integration.py::test_probe_fails_when_an_rpc_returns_an_empty_result
FAILED tests/db/test_jobs_integration.py::test_probe_parks_its_row_before_failing_on_drift
FAILED tests/db/test_jobs_integration.py::test_an_api_error_is_never_a_connection_failure_even_when_nested
FAILED tests/db/test_jobs_integration.py::test_connection_classifier_does_not_treat_ordinary_bugs_as_network_failures
FAILED tests/db/test_jobs_integration.py::test_connection_classifier_terminates_on_a_self_referential_cause
9 failed, 14 passed, 2 deselected in 0.42s
```

The first mutation run came back **`3 failed, 14 passed, 6 skipped`** — the
drift guards reported as *skipped*, not failed, because `pytest.skip` raises
`Skipped`, a `BaseException` that sails straight through
`with pytest.raises(APIError)`. A skip is not a red. That is the same defect
one level up, so `_probe_strictly()` was added: it converts a wrongful skip
into an `AssertionError`. After that, the mutation produces **0 skipped and 9
failed**, quoted above.

`test_probe_fails_when_the_claim_rpc_returns_no_row` also had to stop matching
`"schema drift"` (text present in both the probe's message and the wrapper's)
and match `"claim_next_job returned no row"` instead, which only the probe
emits. Before that change it survived the mutation.

### The precise conditions that now make this file go red

Running `pytest -m live tests/db/test_jobs_integration.py` with credentials
configured and the connection working:

1. any `postgrest.APIError` from `enqueue`, `claim_next`,
   `retry_or_dead_letter` or `fail` — a missing/renamed RPC (`PGRST202`), a
   missing column (`42703`), an RLS or type change;
2. `claim_next_job` returning no row for a job enqueued one call earlier
   (`AssertionError`);
3. `KeyError("job was not found")` from `db.jobs._one_job` — an RPC that
   returns an empty result;
4. any `TypeError`/`ValueError`/`KeyError` from `Job.from_row` — a dropped or
   renamed column in the returned row.

Only `httpx.TransportError` and bare `OSError` still skip, and their message
says so.

## Verification

### 1. Collect-only

```
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-drift --collect-only tests/db/test_jobs_integration.py
tests/db/test_jobs_integration.py::test_the_two_live_tests_stay_behind_the_live_marker

23/25 tests collected (2 deselected) in 0.87s
```

The 2 deselected are the two live tests. See "Scope expansion" below.

### 2. `tests/db/`

```
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-drift tests/db/
........................................                                 [100%]
40 passed, 2 deselected in 1.27s
```

### 3. Full offline suite

```
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-drift --ignore=tests/db/test_jobs_integration.py
952 passed, 7 deselected, 2 warnings in 145.73s (0:02:25)
```

Green. Baseline was 862 passed / 7 deselected at `52e2c03`; the extra ~90 are
the concurrent `voice-cli-tests` lane's new tests, which landed during this
lane's run.

Three earlier full-suite runs were red **entirely inside `tests/voice/`**
(1, 21 and 1 failures) while that lane was mid-edit on
`voice/try_stt.py` / `voice/listen_wakeword.py`. None of them touched anything
this lane owns. Isolated at the time:

```
$ .venv\Scripts\python.exe -m pytest -q ... --ignore=tests/db/test_jobs_integration.py --ignore=tests/voice
729 passed, 7 deselected, 2 warnings in 131.48s (0:02:11)
```

and the final run's failures-outside-`tests/voice` list was empty.

### 4. Live Supabase was never contacted

Required by the brief. The evidence:

- Every new guard test drives `_ScriptedRepository`, an in-memory fake. No
  socket is opened.
- Both live tests carry `@pytest.mark.live`, so `pytest.ini`'s
  `addopts = -m "not live and not realflp and not guiauto"` deselects them from
  every command run above. The `2 deselected` in runs 1 and 2 is exactly them.
- `pytest -m live --collect-only` was used to confirm the marker routes
  correctly. It collects, it does not execute:

```
$ .venv\Scripts\python.exe -m pytest -q ... -m live --collect-only tests/db/test_jobs_integration.py
tests/db/test_jobs_integration.py::test_real_supabase_full_job_lifecycle
tests/db/test_jobs_integration.py::test_real_supabase_concurrent_claims_never_double_claim_or_drop_a_job

2/25 tests collected (23 deselected) in 0.22s
```

- `pytest -q -m live tests/live` was **not** run, and no `-m live` execution of
  any kind was performed.
- No row was enqueued, claimed, mutated or failed in the live `jobs` table.

## Scope expansion: the `live` marker

Adding `@pytest.mark.live` to the two live tests was not in the brief, and it
turned out to be load-bearing for the brief's own verification command.

`_env_has_supabase_credentials()` returns `True` on this machine — checked as a
bare boolean, no values printed:

```
$ .venv\Scripts\python.exe -c "...print('credentials configured (bool only, no values):', m._env_has_supabase_credentials())"
credentials configured (bool only, no values): True
```

The two live tests were gated **only** by `skipif(not
_env_has_supabase_credentials())`. With credentials configured, the brief's own
command `pytest ... tests/db/` would have executed both against the live
project — enqueuing, claiming and failing rows in the exclusive `jobs` table
this lane has not claimed, while an executor claims from it. The `live` marker
is what makes that command safe. `test_the_two_live_tests_stay_behind_the_live_marker`
now asserts the marker stays on.

## Recommendation on the `--ignore` (not owned — CORE decides)

**Remove `--ignore=tests/db/test_jobs_integration.py` from both `CLAUDE.md`
(line 60) and `.githooks/pre-commit`.** The `live` marker now does the job the
`--ignore` was doing, and does it better.

What it buys: the 23 offline guard tests in this file — the ones that keep the
drift detector honest — currently never run in any routine verification,
because the `--ignore` is path-based and takes the guards out with the live
tests. That is the same class of defect as the original bug: a test that cannot
go red.

What it costs: nothing measurable. Verified by running the full offline suite
with the `--ignore` dropped:

```
$ .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-drift
973 passed, 9 deselected, 2 warnings in 170.39s (0:02:50)
```

Green. 9 deselected = the 7 pre-existing plus the 2 live tests. No live contact:
`addopts` deselects them before any code in them runs.

Suggested edits, for CORE to make or reject:

- `CLAUDE.md` line 60 — drop the `--ignore=...` flag from the documented
  full-suite command.
- `.githooks/pre-commit` — drop the same flag from its `pytest` invocation.

If CORE would rather not touch the hook, the second-best option is to leave
both alone and accept that the guards only run when someone runs `tests/db/` by
hand. That is strictly worse and reintroduces the "never runs" property in a
smaller form.

## Found and left alone

- **The probe writes to the live `jobs` table.** `_probe_0002_schema` enqueues
  a disposable `queue-durability-probe-<uuid>` row and parks it via `fail()`.
  Behaviour is unchanged from before this lane, but it means the concurrency
  test still leaves rows behind in a table an executor polls. A read-only probe
  (`has_open_job_of_kind` against a kind that cannot exist, or a bare RPC
  introspection) would avoid that. Out of scope here; needs the live `jobs`
  resource claim to validate.
- **`test_real_supabase_full_job_lifecycle` never probes the schema at all.**
  It goes straight at the live project and would surface drift as a raw
  traceback rather than a diagnosed one. It is now marked `live`, so it is
  opt-in, and it does fail loudly, so it is not the defect this lane was
  chartered to fix. Left as-is.
- **`_load_supabase_env` and the inline env loader in
  `test_real_supabase_full_job_lifecycle` are duplicates.** Deliberately not
  merged: the diff is meant to be reviewable as a behaviour change, not a
  tidy-up.
- No shared interface changed. `JobRepository` is unmodified;
  `_ScriptedRepository` implements it in full and is local to this file, so no
  test double elsewhere is stranded.

## Rules observed

Did not commit. Did not edit `requirements.txt`. Did not `git stash`. Did not
read or print `.env` contents — only its existence and a boolean derived from
it. Did not remove the `--ignore`. Wrote no file other than
`tests/db/test_jobs_integration.py` and this report.
