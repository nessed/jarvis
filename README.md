# JARVIS

A personal assistant I talk to over WhatsApp. Messages hit a FastAPI webhook,
get written into a Supabase Postgres queue, and my laptop pulls them off and
runs them. The laptop does the actual work, so nothing has to stay up in the
cloud and nothing expensive runs when I'm not using it.

Memory is local. Facts go into SQLite, embeddings come from Ollama running on
loopback, and search runs through sqlite-vec. Mem0 sits on top, self-hosted.
Nothing personal leaves the machine.

LLM calls go through a router that tries free tiers first and falls back to paid
only when it has to.

## State

Phase 1 of 6. Phase 0 (webhook, queue, executor, provider routing) is done and
verified against live services.

Working:

- Webhook with HMAC verification, bearer auth on everything else
- Durable queue with atomic claim, checkpoint, complete
- Executor pulling jobs on the laptop
- Groq, Gemini, DeepSeek, OpenRouter routing
- Local memory: remember and recall both work end to end against real Ollama

Not working yet:

- Nothing calls memory during a conversation. The plumbing exists, it just
  isn't wired into the message path.
- Retry and dead-letter logic is written and tested but the migration hasn't
  been applied to the live database.
- The Meta app is unpublished, so only test messages get delivered.
- Cerebras returns 402, Mistral returns 403. Both are in the router, neither
  can take work.
- The tunnel is a Cloudflare Quick Tunnel, so the URL dies whenever cloudflared
  restarts.

Phases 2 through 5 are FL Studio automation, voice, splitting work between a
VPS and the laptop, and a vision fallback. None started.

## Running it

You need Python 3.11+, a Supabase project, and Ollama with `nomic-embed-text`
and `llama3.1:8b` pulled.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Fill in `.env` by hand. It's gitignored and stays that way.

Then start it:

```
start-jarvis.bat
```

Double-click that, or run it from a terminal. It brings up the webhook
receiver, the public tunnel, and the worker in order, re-points WhatsApp at the
new tunnel URL, and stops the whole set on Ctrl+C. Nothing else needs starting
by hand.

To run just the bus on its own:

```
.venv\Scripts\python.exe -m uvicorn bus.main:app --reload
```

`GET /health` is the only route that doesn't need auth.

One more thing after a fresh clone:

```
git config core.hooksPath .githooks
```

That turns on the pre-commit hook, which runs the test suite and blocks the
commit if anything is red.

## Tests

```
.venv\Scripts\python.exe -m pytest -q --ignore=tests/db/test_jobs_integration.py
```

That's the offline suite. No network, deterministic, and it has to pass before
anything gets committed. The ignored file needs live Supabase credentials.

```
.venv\Scripts\python.exe -m pytest -q -m live tests/live
```

Those are the acceptance tests. They hit real Ollama and are left out of the
default run. Green unit tests don't mean a phase is finished, these do.

## Tools

```
.venv\Scripts\python.exe tools/consult.py "question" [--file P] [--cmd "..."]
.venv\Scripts\python.exe tools/repoint_webhook.py [--check]
```

`consult.py` asks a stronger model a question through headless `claude -p` and
gets back a structured answer instead of prose. I built it because I was
manually copying terminal output into a browser, reading the reply, and pasting
it back. It scrubs anything that looks like a key before sending and won't touch
`.env` at all.

`repoint_webhook.py` updates the WhatsApp callback URL through the Graph API
after the tunnel restarts. Beats clicking through Meta's dashboard every time.
It checks the tunnel is alive first and reads the subscription back afterward.

## How this repo gets built

Almost all of the code here is written by AI agents. `agents.md` is the rulebook
they work under and it loads automatically through `CLAUDE.md`. The short
version: every claim that something works has to name the command that proved
it, specified components can't be swapped out without asking, secrets never get
printed or committed, and anything touching my personal data needs me to say yes
first.

Docs are split by how fast they go stale. `docs/context.md` is whatever is in
flight right now and stays short, with its status block generated from git.
`docs/state.md` is component status: what works, what's blocked, which provider
rungs are usable. `docs/history/` is the frozen archive, append-only.
`docs/blueprint.md` is the spec. `docs/workflow_overview.md` describes the
process itself, including what's still wrong with it.
