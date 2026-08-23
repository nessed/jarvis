# Wave A: repository skeleton

## Ownership

Own the repository alone during Wave A. No other worker is active. Create the
initial Phase 0 layout and make the first small commit.

## Required implementation

Create `bus/` with a FastAPI app and only a health route, `router/` as a Python
package stub, `executor/` with a poller stub, `infra/`, `tests/`, and this
`docs/tasks/` directory. Create a pinned `requirements.txt`, README, `.gitignore`,
`.env.example`, and a local `.env`.

`.env.example` has empty placeholders only for `GROQ_API_KEY`,
`CEREBRAS_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`,
`MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `SUPABASE_URL`,
`SUPABASE_KEY`, `META_VERIFY_TOKEN`, `META_APP_SECRET`, `META_ACCESS_TOKEN`,
`META_PHONE_NUMBER_ID`, and `BUS_BEARER_TOKEN` (plus `DEEPSEEK_VIA_OPENROUTER`
if useful). `.env` is ignored before any commit; it is never printed, logged,
or committed. Generate `META_VERIFY_TOKEN` and `BUS_BEARER_TOKEN` locally using
`openssl rand -hex 32` and write them into `.env` without exposing them.

Create `.venv`, install pinned dependencies, initialize git, verify `.env` is
ignored with git before the first commit, run the health test, then commit only
the skeleton. Do not install globally or elevate permissions. All tests are
written with the code.

## Constraints

Python 3.11+, FastAPI, Supabase/Postgres, and OpenAI SDK are the eventual stack.
Never handle provider secrets, passwords, cards, or tokens in chat/output.
Small logical commits only.
