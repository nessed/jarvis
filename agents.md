# JARVIS build rules

`docs/blueprint.md` is the technical spec. Read it before task work. Treat
provider claims in it about pricing, rate limits, model names, and free tiers
as claims to verify with current sources before relying on them. Architecture,
component choices, dependency selection, and phase ordering are decisions, not
claims. If a specified component appears wrong, unavailable, or unnecessary,
stop and report before writing code; never substitute it. `docs/context.md` is
the source of truth for the current build state; read it rather than assuming
the current phase. Update it after every completed subtask with the result,
remaining blocker, and any changed operational detail.

If a task cannot be completed as specified, report the blocker and stop. Do
not build an alternative and document it afterward. A deviation that reaches a
commit is a failure whether or not the code passes tests.

## Parallelism is the default

- Before any multi-part task, decompose the work and identify independent
  lanes. Use sequential work only for genuine dependencies.
- Dispatch independent work to subagents. Avoid serializing work that has
  disjoint ownership.
- Give every subagent strict, disjoint file ownership. A lane that needs to
  touch another lane's paths reports that need instead of editing them.
- Write each lane's self-contained brief to `docs/tasks/<lane>.md` before
  dispatch. Include the relevant blueprint detail so the brief is a recovery
  path if context is lost.
- No subagent edits `requirements.txt`. Append dependencies to
  `docs/tasks/deps-<lane>.txt`; the orchestrator integrates them.
- No subagent commits. The orchestrator commits after integration.

## How we work

- Delegate all executable code, file, and terminal work to agents; do not give
  the user commands or files to create.
- The user handles only logins/2FA/captchas, card entry, final Save/Confirm
  clicks on third-party dashboards, and sensory verification (for example,
  listening to TTS or checking FL Studio edits by ear).
- Batch user-hand steps into a single interruption. Do not wait if another
  lane can make progress.
- Do not ask permission for ordinary shell commands. Ask once and wait only
  before genuinely destructive work, including `rm -rf`, `DROP TABLE`, deleting
  cloud resources, writing to any original `.flp`, or global Git configuration
  such as `git config --global --add safe.directory`; use copies for FLP work.
- Keep reports terse: what landed, what broke, what is needed, and what was
  specified but not done.
- Every claim that something works must name the command or test that produced
  it and its output. A dispatched subagent returning no completion is failed
  verification, not a result. Do not delete test data or artifacts before the
  outcome has been reported.

## Secrets

- Never print, echo, log, commit, or ask for API keys, tokens, passwords, or
  card details.
- `.env.example` contains empty placeholders only. The user normally fills
  `.env` by hand. If the user explicitly overrides that rule for specified
  credentials, an agent may write only those values to the local ignored `.env`
  file; never copy them elsewhere or expose them in output.
- Verify `.gitignore` contains `.env` before the first commit; do not assume.
- In browser mode, never type into password, 2FA, or card fields. Stop and
  hand over.

## Browser mode

- Drive navigation and reading. The user performs logins, 2FA, captchas, and
  every final Save/Confirm click.
- Provider consoles may flag automated key creation. Navigate to each key page
  and let the user click Create.

## Stack and provider routing

- Python 3.11+, FastAPI, Supabase, and the OpenAI SDK using `base_url` swapping
  for providers. Pin dependencies, use `.venv`, and keep tests alongside code.
- Never hardcode provider rate limits or free-model IDs. Read response headers
  at runtime.
