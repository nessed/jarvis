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

Phase 3 of 6. Phases 0 and 1 are done; 2 and 3 are largely done and 3 has been
verified end to end against real WhatsApp.

Working:

- Webhook with HMAC verification, bearer auth on everything else. Duplicate
  Meta redeliveries are dropped at enqueue *and* again at send, because a real
  redelivery created a duplicate job in production.
- Durable queue with atomic claim, checkpoint, complete, retry, backoff,
  per-job timeout and dead-letter. Both migrations are applied live.
- Two independently supervised workers on the laptop: one only takes WhatsApp
  messages, one only runs the slow background memory work. Neither can starve
  the other.
- Groq, Gemini, DeepSeek and OpenRouter in the router, free tiers first.
- Local memory, wired into conversations. A message recalls context, routes,
  replies, then stores the turn. Recalled memory is injected as a *user*
  message inside a fence, never as a system instruction — it used to be the
  latter, which meant anything a sender got remembered came back wearing my
  role.
- **Voice, both directions.** A WhatsApp voice note is downloaded, decoded,
  transcribed locally on this laptop's NPU, and answered with a synthesised
  voice note. Confirmed working on my own phone.
- Speech-to-text runs Whisper large-v3 on the XDNA NPU — 12.4x faster than CPU
  on the encoder. It's a from-source build of `amd/whisper.cpp`; if the NPU
  graph won't load the binary aborts rather than quietly falling back to CPU,
  so a "working" result can't be a lie.
- Desktop control: power plans, wifi, Bluetooth, displays, scheduled tasks,
  printing, file moves, process kills. Plus UIA automation for Zoom's join
  dialogs and sending from WhatsApp Desktop.
- FL Studio `.flp` files parse and re-save with edits intact, against real
  projects.

Not working yet:

- **Most of the above has no way to be triggered.** `flp_sort`,
  `system_control`, `zoom_join_meeting` and `whatsapp_desktop_send_message` are
  all registered handlers, but the only two things that create jobs are the
  WhatsApp webhook and the memory chain re-queuing itself. Nothing classifies
  an incoming message into "sort my FLP" or "join this Zoom". That classifier
  is the next real piece of work.
- The Meta app is unpublished, so only test messages get delivered.
- Cerebras returns 402, Mistral returns 403. Both are in the router, neither
  can take work.
- Five providers have no model ID set in `.env`, so those rungs can't serve a
  request. It fails safe — the router logs it and falls through — but they
  aren't usable.
- The tunnel is a Cloudflare Quick Tunnel, so the URL dies whenever cloudflared
  or the laptop stops. The launcher mints a new one and re-points Meta
  automatically, but nothing receives messages while the laptop is off.
- No personal data has been ingested yet. That needs me to opt in per source
  and it hasn't happened.

Phase 4 is splitting work between a VPS and the laptop. Phase 5 is a vision
fallback. Neither has started.

## Running it

You need Python 3.12, a Supabase project, and Ollama with `nomic-embed-text`
pulled (for embeddings) plus whatever you set as the fact-extraction model.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Fill in `.env` by hand. It's gitignored and stays that way.

The FL Studio side needs a **second** environment, and its Python version is
part of the pin:

```
py -3.11 -m venv --clear .venv311
.venv311\Scripts\python.exe -m pip install -r requirements-flp.txt
```

That has to be CPython 3.11.5 exactly — not 3.11.6, not 3.12. PyFLP 2.2.1
relies on an empty enum reaching `_missing_`, and CPython added a guard that
raises first, backported into 3.11.6. It holds two packages, stays off `PATH`,
and only ever reads copies of my own project files. Everything else uses
`.venv`.

Voice is optional and needs more: Kokoro for speech, and a from-source build of
`amd/whisper.cpp` if you want speech-to-text on an AMD NPU. Without them the
WhatsApp path still works, it just stays text-only.

Then start it:

```
start-jarvis.bat
```

Double-click that, or run it from a terminal. It brings up Ollama, the webhook
receiver, the public tunnel, both workers and the local speech-to-text server
in order, re-points WhatsApp at the new tunnel URL, and stops the whole set on
Ctrl+C. Nothing else needs starting by hand.

Only one copy can run at a time — it takes an exclusive lock on a loopback port
before doing anything else, and a second copy tells you which process is
holding it instead of minting a second tunnel and fighting over the queue. The
speech-to-text server is optional: if it dies or the NPU build is missing,
voice degrades to text and everything else keeps running.

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
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp
```

That's the offline suite. No network, deterministic, and it has to pass before
anything gets committed. Anything needing a real service — Supabase, Ollama,
Meta, a GUI app, the FL Studio sandbox — sits behind a pytest marker and is
deselected by default, so there is nothing to remember to exclude.

The two extra flags aren't optional on my machine — the system TEMP directory
is locked down, and pytest's default cache and scratch directories land there
and die with `PermissionError` without them. The pre-commit hook uses the same
form. If you're on a normal setup, a bare `pytest -q` works fine.

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
