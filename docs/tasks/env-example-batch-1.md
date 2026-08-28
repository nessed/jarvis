# Lane: env-example-batch-1

## Ownership

Own only `.env.example`. Claimed under work-board claim `env-example-batch-1`
— already held by the orchestrator; do not re-claim or release it. Do not
touch any other file. Do not commit. This is a documentation-only change: you
are adding empty-value placeholder lines, never a real secret, never a value
read from the real `.env`.

## Context

`.env.example` is what `README.md` tells a new setup to copy to `.env`. It is
currently missing 18 variables the code actually reads, so a fresh clone
cannot reach the queue (`SUPABASE_SECRET_KEY` is required and simply absent).
It also has a stale entry: `SUPABASE_KEY` is present but nothing in the
codebase reads it — grep to confirm before removing it (don't remove on the
brief's word alone).

Add these, grouped with a one-line comment per group matching the existing
file's style (no blank-value assumptions — leave every value empty, exactly
like the existing lines):

- **bus/db**: `SUPABASE_SECRET_KEY`, `SUPABASE_QUEUE_TIMEOUT_SECONDS`
- **router**: `GROQ_DEFAULT_MODEL`, `CEREBRAS_DEFAULT_MODEL`,
  `NVIDIA_DEFAULT_MODEL`, `GEMINI_DEFAULT_MODEL`, `MISTRAL_DEFAULT_MODEL`,
  `CLAUDE_API_BASE_URL`, `CLAUDE_API_DEFAULT_MODEL`, `OPENROUTER_BASE_URL`,
  `OPENROUTER_DEEPSEEK_MODEL`
- **executor/memory**: `JARVIS_MEMORY_WRITES`, `JARVIS_DISTILL`,
  `JARVIS_POLL_INTERVAL_SECONDS`, `JARVIS_EXECUTOR_HEARTBEAT`,
  `OLLAMA_EMBEDDING_TIMEOUT_SECONDS`, `OLLAMA_FACT_EXTRACTION_MODEL`,
  `OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS`

For each variable, grep the codebase for where it's actually read
(`os.environ.get(...)` / `os.getenv(...)` / `environ.get(...)`) before adding
it, to confirm the exact name and that it's real — don't transcribe this list
blind, it was written from a snapshot and may already be stale (check whether
any of these 18 were added by someone else since). If a name in this list
turns out not to exist in the code, or already exists in `.env.example`, skip
it and say so in your report rather than adding a dead or duplicate line.

`OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS` is a **startup precondition**, not a
tunable knob: `executor/handlers/distill.py`'s `assert_timeouts_ordered()`
(called from `executor/poller.py:main()`) requires it to be set above the
distill handler's own timeout, or the executor refuses to start. Say so in
the comment above that line, briefly, in the file's existing comment style.

Also confirm whether `SUPABASE_KEY` is genuinely dead (grep for
`SUPABASE_KEY` across the codebase, excluding this file and docs) before
removing it. If it's dead, remove it and say so; if anything reads it, leave
it and say so.

## Verification

There is no test file for `.env.example` itself. Verify by grep: every
variable name you added must have at least one real reader in the codebase
(cite the file:line for each). Run the full offline suite to confirm nothing
broke (this file isn't imported by tests, so this is a sanity check, not a
direct test of your change):

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp-env --ignore=tests/db/test_jobs_integration.py
```

## Report

The final variable list added, each with its grep-confirmed file:line reader.
Any of the 18 you skipped and why. Whether `SUPABASE_KEY` was removed and why.
