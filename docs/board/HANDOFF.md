# Handoff

The one place agents write to when they need Ali. Overwritten, not appended:
this is what is waiting on him *now*. Anything that stops being true gets
removed. History lives in `docs/history/`, questions in `QUESTIONS.md`,
hands-and-accounts steps in `USER-TASKS.md`; this file points at them.

Written by whichever lane runs out of work first; the other lanes append a
line rather than sending a second notification. One `PushNotification` per
rewrite.

---

**Written 2 Sep 2026 by CORE.** The board still has eight ready tasks, so
nothing here blocks work — but four items are yours alone, and one thing is
broken that you should know about.

## One thing is broken

**Batch distillation has been down since 30 August.** Memory is not being
built.

- 98 of the queue's 103 dead-lettered rows are `distill_memory`, all inside a
  32-hour window on 29–30 Aug: 83 `EmbeddingError`, 12 `LLMError`, 3 stale
  timeouts.
- Since then it has been *stalled*, not dead: exactly one row is queued, ripe
  since 30 Aug 20:53, unclaimed for two days.
- Your reply path is fine — 175 `whatsapp_webhook` rows, every one `done`.

Filed as `distill-chain-stall`, at the top of NEXT. No action needed from
you; an agent takes it next.

## Four things only you can do

Ordered by what they unblock. Each has a full write-up where it lives.

1. **Q12 — drop Pipecat from the desk loop?** (`QUESTIONS.md`)
   `voice-loop` stopped before writing a line because five of its six stages
   would be custom subclasses. Recommendation and a second opinion are filed.
   Blocks `voice-loop` and `voice-command-ingress`.

2. **U2 — the five model IDs still are not in `.env`.** (`USER-TASKS.md`)
   You said "pasted"; a key-name check finds none of them. This is now
   costing something measurable, not hypothetical: `groq` and `cerebras` sort
   to the front of every request and are silently skipped, so the ladder
   collapses to `openrouter/free` — which answered a JSON-only prompt with
   the string `User Safety: safe` on two of four probes. WhatsApp commands
   fail safe when that happens (they read as chat), but they only work as
   often as that one rung behaves.

3. **U12 — `SUPABASE_DB_PASSWORD` is an empty placeholder.**
   (`USER-TASKS.md`) The migration runner, its ledger and migration `0003`
   are built, tested and committed. The REST key you have can read and write
   rows but cannot run DDL, so nothing can be applied until this lands. Two
   minutes: Supabase dashboard → Project Settings → Database.

4. **Q11 — how long is the router's "verification window"?**
   (`QUESTIONS.md`) Your own §3.3 makes a rung ineligible without a recent
   verified 200. Recommendation is 24h plus an eligible-but-last cold start.
   Blocks only `router-eligibility-window`.

## One two-minute sensory check, whenever

**U11 — send one code-switched voice note with whisper-server stopped.**
The Groq STT fallback is live and word-perfect on English. Under the
production `ur` language hint a pure-English test clip came back as garbage,
which is the documented trade — but a synthetic English clip is not how you
talk, so it proves nothing about your real messages. One normal Urdu/English
note settles whether the fallback needs its own language setting.

## What landed on 2 September

Eleven tasks across four parallel sessions. From this one:

- **`action-worker`** — the four action job kinds had no consumer at all
  (`--kind` took one value). A third supervised worker now owns them.
- **`enqueue-classifier`** — WhatsApp text becomes real action jobs, on your
  closed allowlist, with confirm-first on anything irreversible. Live: three
  wifi queries classified, enqueued and completed; "kill the chrome process"
  asked first and enqueued nothing.
- **`router-cooldown-ledger`** — cooldowns now outlive a single call, and
  `/status` reports the ledger of the process that actually routes instead of
  the bus's, which never routes anything.
- **`blueprint-corrections`** — your §3.3 applied verbatim, five provider
  facts re-verified against current sources. One audit recommendation was
  wrong and is flagged rather than followed.
- **`stt-groq-fallback`** — a dead whisper-server no longer means silence.
- **`db-maintenance`** — runner and ledger built; blocked on U12 above.
- **`board-audit`** — NEXT is now generated from the task files, and seven
  new tasks were filed from what the day's work turned up.

Detail in each task's Log under `docs/board/tasks/`, and in `docs/state.md`.
