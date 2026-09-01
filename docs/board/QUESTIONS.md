# Questions for Ali — one sitting

Every open decision, batched. Each has a recommendation so the whole file
is answerable in one message like: `1 yes, 2 A, 3 A, 4 go + window Sat
morning, 5 pasted, 6 A, 7 A, 8 A, 9 yes + psycopg, 10 yes`.

Rules for agents: these are Class C. Do not act on a recommendation as if
it were an answer. When an answer arrives, record it inline here (dated),
flip the tasks it unblocks to `ready`, and apply any blueprint amendment it
implies in the same pass.

---

## Q1 — May WhatsApp messages trigger real actions?

`flp_sort`, `system_control`, `zoom_join_meeting`,
`whatsapp_desktop_send_message` are built, tested, registered — and nothing
can enqueue them. The missing producer is a classifier on inbound WhatsApp
text ("sort out this FLP" → `flp_sort` job). Inbound text was an injection
channel until 27 Aug (now fenced + deduped), and this gives your phone the
power to move files and drive apps on the laptop.

**Recommend: yes, with a per-kind allowlist** — start with `system_control`
and `zoom_join_meeting` only; `flp_sort` stays out until a convention
exists; anything destructive replies with a confirm-first message.

Unblocks: `enqueue-classifier`.

**Answer:** _pending_

## Q2 — Worker topology for the four action kinds

The two-worker split (whatsapp-worker / background-worker) means no running
poller ever claims the four action kinds. Widening background-worker is
rejected by evidence: a 2s Zoom join would queue behind a 130s Ollama
extraction — the exact starvation the split exists to prevent.

- **A (recommended): third worker.** `action-worker` polls only the four
  action kinds. Small launcher change, no schema change.
- B: add a priority column to the live `jobs` table (schema migration,
  needs Q9 anyway).
- C: leave them dead for now.

Unblocks: `action-worker`, and with Q1 `enqueue-classifier`.

**Answer:** _pending_

## Q3 — Backfill checkpoint: amend blueprint or conform code?

Blueprint 1.3 says "checkpoint = file + offset". The code keys checkpoints
on content hash (rename-safe, tamper-evident; but editing an ingested file
restarts it from chunk 0 and re-remembers everything).

- **A (recommended): amend the blueprint** to content-hash — it shipped,
  it's safer, and the re-ingest-on-edit cost is acceptable for your corpus.
- B: conform the code to file+offset.

Must be settled before `backfill-run`.

**Answer:** _pending_

## Q4 — Backfill go signal

Confirm `ingest/data/` as it stands is the final ingest list (this is the
corpus opt-in — nothing outside that folder is ever read), and give a
window of a few hours when you don't expect replies: the run monopolises
Ollama, so JARVIS is text-dumb while it runs.

Unblocks: `backfill-run`, then U5 (your ten-question review).

**Answer:** _pending_

## Q5 — Provider model IDs (paste, don't discuss)

Five `*_DEFAULT_MODEL` keys are missing from `.env`, so five rungs can't
serve a request. Researched values (state.md, verified 28 Aug 2026) —
paste into `.env`, edit as you like:

```
GROQ_DEFAULT_MODEL=openai/gpt-oss-20b
GEMINI_DEFAULT_MODEL=gemini-2.5-flash
CEREBRAS_DEFAULT_MODEL=gpt-oss-120b
NVIDIA_DEFAULT_MODEL=
CLAUDE_API_DEFAULT_MODEL=claude-sonnet-5
```

(NVIDIA stays empty — geo-blocked, no key. Cerebras only matters if Q6
keeps the rung.) Say "pasted" when done — that's U2, and it unblocks
`live-routing-probe`.

**Answer:** _pending_

## Q6 — Cerebras and Mistral rungs

Cerebras: free tier abolished 17 Aug 2026; every call 402s until a card
goes on file. Mistral: chat 403s, cause undocumented, likely workspace
plan activation (your dashboard, U9).

- **A (recommended): disable the Cerebras rung** (blueprint edit) until
  you ever decide to add a card; leave Mistral in place pending U9.
- B: add a card to Cerebras ($5 trial, expires in 30 days).
- C: leave both as-is (dead rungs mid-chain; the 402/403 handling is
  already fixed, so they just waste a hop).

**Answer:** _pending_

## Q7 — How does voice reach the queue?

For the desk voice loop: a bearer-authed `POST /command` endpoint on the
bus, or the loop calling `db.jobs.enqueue` directly?

**Recommend A: `POST /command`** — it survives the bus moving to Oracle in
Phase 4; direct enqueue doesn't.

Unblocks: `voice-command-ingress`.

**Answer:** _pending_

## Q8 — Cloud STT fallback ownership

Blueprint says Groq Whisper is the STT fallback if the NPU disappoints.
The router is chat-completions-only; audio is a different endpoint shape.

**Recommend A: voice owns its own small Groq STT client** (no router
change). B: grow the router an audio lane (shared-interface change, big).

Unblocks: `stt-groq-fallback`.

**Answer:** _pending_

## Q9 — Live database maintenance approval

Three deferred items need your one-time approval because they write the
live `jobs` table / schema: a migration runner + ledger, sweeping the one
orphaned `queue-durability-probe-` row, and a retention/index pass. Also:
which Postgres driver may enter `requirements.txt` (there is none today —
that's why migration 0002 once sat unapplied). **Recommend `psycopg`
(v3, binary extra)** — your call, it's a component decision.

Unblocks: `db-maintenance`.

**Answer:** _pending_

## Q10 — Blueprint housekeeping (one blanket yes/no)

Approve agents applying, in one pass (`blueprint-corrections` task):

- **a.** The factual corrections in `docs/audit/blueprint-drift.md` §3.7 +
  §3.8 (DeepSeek weekday peak windows, stale price caveat, Cerebras/Groq/
  NIM corrections, 1.3 extraction sentence matching what shipped).
- **b.** Restating the routing chain as 9 rungs with live status delegated
  to `state.md` (audit §3.3), and numbering the facts-check job as a real
  deliverable (§3.5) — the tool itself is being built regardless.
- **c.** Specifying the cooldown ledger as **process-lifetime**, with the
  executor (not the bus) reporting provider health (§3.4). This one is a
  real architecture choice — say no to just this letter if you want to
  think about it. Unblocks: `router-cooldown-ledger`.

**Recommend: yes to all three.**

**Answer:** _pending_
