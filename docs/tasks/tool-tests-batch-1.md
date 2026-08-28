# Lane: tool-tests-batch-1

## Ownership

Own only `tools/repoint_webhook.py`, `tests/tools/test_repoint_webhook.py`,
`tests/tools/test_context_status.py`, `tests/tools/test_consult.py`,
`tests/tools/test_precommit_hook.py`. Claimed under work-board claim
`tool-tests-batch-1` — already held by the orchestrator; do not re-claim or
release it. Do not touch any other file, including `tools/consult.py` and
`tools/context_status.py` themselves (test them as black boxes; if you find a
real bug in either, report it, don't fix it — out of scope). Do not edit
`requirements.txt`; append any dependency to
`docs/tasks/deps-tool-tests-batch-1.txt`. Do not commit.

## Context

Four independent additions. `tools/repoint_webhook.py` has no test file at
all today (7.5KB, the whole Meta re-point path uncovered) and is also missing
a length guard on `META_VERIFY_TOKEN`; the other three add tests for existing
files that already have no coverage.

### 1. `test-repoint-webhook`

Read `tools/repoint_webhook.py` in full first — it's short. Write
`tests/tools/test_repoint_webhook.py` covering, at minimum:
`discover_tunnel_url()` (picks the newest-mtime log's last match across the
three log candidates), `tunnel_is_live()` (200 and any HTTPError both count as
"live"; a connection error/timeout does not), `current_callback()` (finds the
`whatsapp_business_account` entry, returns `None` if absent), and `main()`'s
exit-code contract (0 changed/already-correct, 1 usage/config error, 2 tunnel
unreachable, 3 Graph API rejected) — mock `urllib.request.urlopen` and
environment/file reads; never make a real network call or read the real
`.env`. Also add the missing guard: `main()` reads `META_VERIFY_TOKEN` from
`.env` (line 141) with no length check anywhere in this file. Meta's verify
token has a documented maximum length — confirm the current limit from Meta's
own WhatsApp Cloud API docs (do not guess a number) — and add a check in
`main()` that rejects (exit 1, clear stderr message, before any Graph API
call) a token exceeding that limit, alongside the existing `missing = [...]`
check. Test that guard too.

### 2. `test-context-status`

`tools/context_status.py` has no tests and `.githooks/pre-commit` runs it on
every commit — a break there breaks every commit for every lane. Read it and
write `tests/tools/test_context_status.py` covering its actual public
behavior (read it first; do not assume the surface — this brief intentionally
doesn't enumerate its functions since the file wasn't read for this brief).
Cover at minimum: the `--check` mode's exit-code contract, and what happens
when the generated block markers are missing or malformed in `docs/context.md`.

### 3. `consult-untested-paths`

`tools/consult.py` has an argv-vs-stdin fix with no regression test (the
existing mock discards its arguments — find that mock in whatever test file
currently covers `consult.py`, if any, and note it in your report). Nothing
tests `screen()`, `REFUSED_NAMES`, or `SECRET_SHAPES` — the entire mechanism
enforcing `CLAUDE.md` non-negotiable #1 (secrets never printed/logged/
committed/requested) and the explicit refusal to attach `.env`. Write
`tests/tools/test_consult.py` covering: `screen()` rejects a `.env` attachment
outright regardless of content; `screen()` catches each pattern in
`SECRET_SHAPES` when it appears in a would-be-attached file's content, using
**synthetic** key shapes only (fabricated strings matching the shape, e.g.
`sk-` + 48 zeros — never a real-looking production key, and never anything
derived from this repo's actual `.env`); `REFUSED_NAMES` rejects each listed
filename by name regardless of content; the argv-vs-stdin path actually
passes the question through stdin (or argv, whichever the current fix uses —
read the code, don't assume) with a mock that inspects what was actually
passed, not one that discards arguments.

### 4. `hooks-path-invariant-test`

`.githooks/pre-commit` only fires if someone has run
`git config core.hooksPath .githooks` — its own comment says a rule that
depends on being remembered doesn't hold. Write
`tests/tools/test_precommit_hook.py` that asserts something enforceable: e.g.
that `.githooks/pre-commit` exists and is the script `CLAUDE.md` describes
(offline suite + refuse red commit), and/or that repo setup documentation
(`README.md`, `CLAUDE.md`) actually tells a new clone to run the `git config`
command — whatever gives future setup an actual regression signal. This one
can't test the runtime enforcement itself (that needs a real git checkout);
be honest in your report about exactly what this test does and does not
guard against.

## Verification

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-tools tests/tools/test_repoint_webhook.py tests/tools/test_context_status.py tests/tools/test_consult.py tests/tools/test_precommit_hook.py
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-tools --ignore=tests/db/test_jobs_integration.py
```

## Report

For each of the four items: what you found, what you wrote, and confirmation
no `.env` value or real secret shape appears anywhere in your new test files.
Name the Meta verify-token length limit and its source.
