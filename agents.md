# JARVIS build rules

`docs/blueprint.md` is the technical spec. Treat
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

## Before you stop, classify the stop

Stopping is correct for decisions and wrong for lookups. Every halt is one of
three classes; only Class C reaches the user.

- **Class A — determined by evidence you can obtain.** The answer exists in a
  file, a command's output, a log, an API response, or the spec. Obtain it and
  proceed. Do not ask. Examples: which of two signatures the installed library
  actually has, whether a token is still valid, whether a test passes, what a
  provider returns.
- **Class B — a judgment with one defensible answer given the evidence you
  already hold.** Nothing is missing; you are hesitating. Run
  `tools/consult.py` and act on the returned verdict. Record it. If the verdict
  comes back `confidence: low` with a named missing observation, go get that
  observation — that is a Class A step — and consult again. A Class B halt that
  reaches the user without a consult first is a failed halt.
- **Class C — genuinely the user's.** Taste, whether a remembered fact about
  his life is correct, which personal data may enter the system, credentials
  and payment, anything irreversible or outward-facing, sensory checks. Stop
  here every time; never guess these, and never resolve one with a consult.

Substituting a specified component is never Class A or B. That is a Class C
stop regardless of how obvious the substitution seems.

## Parallelism where it pays

- Before any multi-part task, decompose the work and identify independent
  lanes. Use sequential work only for genuine dependencies.
- Dispatch independent work to subagents. Avoid serializing work that has
  disjoint ownership.
- Do not decompose work that is smaller than the decomposition. If a unit
  touches at most two files and has no sibling lane running beside it, do it
  inline — no brief, no dispatch. A brief that takes longer to write than the
  change it describes is overhead, not process.
- Give every subagent strict, disjoint file ownership. A lane that needs to
  touch another lane's paths reports that need instead of editing them.
- Write each lane's self-contained brief to `docs/tasks/<lane>.md` before
  dispatch. Include the relevant blueprint detail so the brief is a recovery
  path if context is lost.
- No subagent edits `requirements.txt`. Append dependencies to
  `docs/tasks/deps-<lane>.txt`; the orchestrator integrates them.
- No subagent commits. The orchestrator commits after integration.
- A lane that changes a shared interface — a `Protocol`, a public signature, a
  schema — names every implementer of it in its report, including test doubles
  that live in files the lane does not own. Disjoint ownership means the lane
  cannot edit them; it does not mean the lane may ignore them.

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
- Before any commit, run the whole offline suite, not the focused subset, and
  cite its output. A focused run proves the lane; only the full run proves the
  tree. A green focused suite over a red tree is a false completion claim.
- Never report to the user with nothing new to say. If the only content of a
  report would be that something is still running or still unchanged, do not
  send it — keep working, or wait, and report when the state actually moves.
- When a task fails the same way twice, stop retrying it. Write
  `docs/blockers/<slug>.md` with the exact reproduction, the exact failure, what
  was already tried, and the single thing the user would have to do to unblock
  it. Then move to other work and raise it once in the next batched handoff.
  A reproducible failure retried across sessions is time spent proving a known
  fact.

## Tools that replace a human step

Use these instead of asking. Each exists because the manual version made the
user a transport layer.

- `tools/consult.py "question" [--file P] [--tail P:N] [--cmd "..."]` — a
  structured second opinion from a stronger model, via headless `claude -p`.
  This is the mechanism for every Class B stop. It screens attachments against
  live `.env` values and known key shapes before sending, and refuses `.env`
  outright; do not defeat that screen, and never attach a secret by hand.
  Returns `{verdict, reasoning, confidence, what_would_change_this}` and saves
  the exchange under `docs/consults/`. Cite the saved path when you act on it.
- `tools/repoint_webhook.py` — re-points Meta's WhatsApp callback at the
  current Cloudflare tunnel through `POST /{app-id}/subscriptions`. It finds
  the live tunnel URL from `tools/cloudflared*.log`, probes it before changing
  anything, and reads the subscription back to confirm. Run this after any
  tunnel restart; do not send the user to the dashboard for it.
- `pytest -q -m live tests/live` — the phase acceptance probes. These are the
  real success criteria and they are excluded from the default run, so run them
  deliberately whenever the thing they cover changes. A phase is not complete
  because its unit tests are green.

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
