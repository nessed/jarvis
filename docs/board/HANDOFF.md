# Handoff — 4 September 2026

You asked for one thing: make it fast. Here is where the time was going,
what is already fixed, and the four things that are yours.

---

## What was slow, measured

Full numbers: `docs/history/infra-audit-2026-09-04.md`.

**Replies.** About 12-18 s of every text reply was connection setup, not
thinking. Three clients were rebuilt on every call, each paying a fresh TLS
handshake from Pakistan:

| Client | Per call before | Now |
|---|---|---|
| Supabase queue (claim, checkpoint, complete — 5 per reply) | 1.7-3.4 s | 0.30 s |
| WhatsApp Graph API (typing cue, send; 4 for voice) | 0.8-1.1 s | 0.24 s |
| LLM provider (2 completions per text reply) | ~2.0 s | 0.8-1.2 s |

Mistral was also re-listing its model roster before every completion.

**Voice.** Kokoro rebuilt its whole pipeline on every reply: 5 s of
construction per voice note, and 25-100 s on the first one after a restart.
Now built once and pre-warmed when the worker starts; a render is ~2.8 s.

**Whisper is the laptop lag, and it is a decision, not a bug.** With the
server already warm, a 7.6 s voice note takes 11-18 s to transcribe at
53-89 % CPU across all eight cores. The NPU only runs the encoder; large-v3's
32-layer decoder runs on the CPU. That is Q15 below.

**Startup.** Everything ran in series: 57 s of tunnel probe + Meta re-point,
then a 3 GB Whisper load, then three workers each importing 5 s of
dependencies. And closing the launcher window orphaned every child: two
`whisper-server.exe` from earlier today were still alive tonight, 750 MB,
both holding port 8081, with the stack down.

---

## What landed today

Committed, full suite green (`1434 passed`). Three subagent lanes on
Opus 5 plus CORE integration.

- **Connection reuse** everywhere — queue, Graph, router. The router now
  runs on one persistent event loop (`route_sync`), which is what lets the
  connection survive between messages.
- **Kokoro cached and warmed.**
- **Launcher:** children are in a Windows Job Object and die with it however
  it dies; Ollama is started for you if it is not running; Whisper and the
  workers start while the tunnel is minted; an already-running Whisper is
  reused, never stacked; every step and the final banner print seconds.
- Ollama is running now (started for the probes) — the launcher will find it.

---

## Do these, in this order

**U15 — kill the two orphaned whisper-servers** (30 s). They are yours to
end; agents never kill what they did not spawn:

```
taskkill /PID 9748 /PID 21308
```

**U16 — run `start-jarvis.bat` and send two messages** (5 min). The banner
now ends with the total seconds. Then one text, one voice note. Report the
three numbers. I could not run the launcher live from this session (the
command classifier refused it), so the startup saving is structural until
you measure it.

**Q15 — which Whisper, and where.** Three options in `QUESTIONS.md`:

- **A (recommended now):** Groq `whisper-large-v3-turbo` as primary, local
  NPU as fallback. One env var. Already live-verified the other way round:
  word-perfect on English in ~1-2 s. Your voice note leaves the laptop.
- **B (when you have an evening):** local large-v3-turbo — same encoder, so
  the NPU graph should carry over; 4 decoder layers instead of 32.
- **C:** keep the 11-18 s.

**U7 — Oracle signup.** This is what "deploy" means and it is the only thing
between you and a bus that is up with the lid closed. Everything on the agent
side is written and validated: `infra/terraform`, hardening scripts,
Dockerfile, `docs/tasks/phase4-runbook.md`. The account needs your identity
and card, one sitting with a browser agent driving. One honest caveat: Phase
4 does not shorten a reply, because memory is laptop-only by your own rules,
so a text reply still round-trips through the laptop executor. It buys a
webhook that never goes down.

Still open from 3 Sep and unchanged: **U2** (three model IDs into `.env`),
**U12** (`SUPABASE_DB_PASSWORD`), **U14** (send one command, expect two
replies), **Q11**, **Q12**.

---

## Your subscriptions

You asked about Claude Max and ChatGPT Plus. The blueprint already settled
both and nothing today changes it: Max is `claude -p` only — it is
`tools/consult.py`, every second opinion — and is never a router target;
Plus has no API. Neither can sit on the reply path.

---

## Not done, on purpose

- **Merging the two LLM calls** (classify + reply) into one would halve
  provider time, but the two-call shape was your Q1 answer. Say so if you
  want it changed.
- **Whisper model or placement** — Q15.
- **Killing orphans** — U15.
- **A live launcher run** — refused by the classifier; U16.
