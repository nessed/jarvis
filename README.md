# JARVIS

Local executor and durable command bus for a personal assistant. A FastAPI
webhook receives WhatsApp messages, enqueues them into Supabase, and a
laptop-resident pull executor claims and runs them. Memory is local-first
(Ollama + sqlite-vec + SQLite, wrapped by self-hosted Mem0).

`docs/blueprint.md` is the spec. `docs/context.md` is the current build state.
`agents.md` is the process contract, loaded automatically via `CLAUDE.md`.

## Local start

1. Create and activate `.venv`.
2. Install `requirements.txt`.
3. Copy `.env.example` to `.env` and fill provider and service values locally.
4. Run `uvicorn bus.main:app --reload`.

The only initial public route is `GET /health`.

After a fresh clone, enable the pre-commit hook once:

```
git config core.hooksPath .githooks
```

It runs the full offline suite and refuses a commit while anything is red.

## Tests

```
.venv\Scripts\python.exe -m pytest -q --ignore=tests/db/test_jobs_integration.py
.venv\Scripts\python.exe -m pytest -q -m live tests/live
```

The first is the offline suite — deterministic, no network, required before any
commit. The second is the phase acceptance probes: they hit real local services
(Ollama on loopback) and are excluded from the default run by `pytest.ini`. A
phase is not complete because its unit tests are green.

`tests/db/test_jobs_integration.py` is excluded above because it needs live
Supabase credentials.

## Tools

```
.venv\Scripts\python.exe tools/consult.py "question" [--file P] [--cmd "..."]
.venv\Scripts\python.exe tools/repoint_webhook.py [--check]
```

`consult.py` gets a structured second opinion from a stronger model through
headless `claude -p`, and saves the exchange under `docs/consults/`. It screens
every attachment against live `.env` values and known key shapes before sending,
and refuses `.env` outright.

`repoint_webhook.py` points Meta's WhatsApp callback at the current Cloudflare
tunnel through the Graph API, so a tunnel restart does not mean a trip through
the dashboard. It probes the tunnel before changing anything and reads the
subscription back to confirm.
