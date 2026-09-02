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

**Answer (1 Sep 2026): yes, with the recommended per-kind allowlist.**
Allowlisted: `system_control`, `zoom_join_meeting`. Excluded: `flp_sort`
(stays out until a convention exists), `whatsapp_desktop_send_message`.
Anything destructive replies with a confirm-first message rather than
enqueueing. No kind joins this list by agent judgment.

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

**Answer (1 Sep 2026): A — third worker.** `action-worker` polls only the
four action kinds. No schema change.

## Q3 — Backfill checkpoint: amend blueprint or conform code?

Blueprint 1.3 says "checkpoint = file + offset". The code keys checkpoints
on content hash (rename-safe, tamper-evident; but editing an ingested file
restarts it from chunk 0 and re-remembers everything).

- **A (recommended): amend the blueprint** to content-hash — it shipped,
  it's safer, and the re-ingest-on-edit cost is acceptable for your corpus.
- B: conform the code to file+offset.

Must be settled before `backfill-run`.

**Answer (1 Sep 2026): A — amend the blueprint to content-hash.** Applied
to `docs/blueprint.md` 1.3 in this same pass; the code is unchanged and
`backfill-run` needs no conform step.

## Q4 — Backfill go signal

Confirm `ingest/data/` as it stands is the final ingest list (this is the
corpus opt-in — nothing outside that folder is ever read), and give a
window of a few hours when you don't expect replies: the run monopolises
Ollama, so JARVIS is text-dumb while it runs.

Unblocks: `backfill-run`, then U5 (your ten-question review).

**Answer (1 Sep 2026): go.** `ingest/data/` as it stands is the final
ingest list. Window: **overnight — explicitly not Saturday morning.**
`backfill-run` schedules itself for an overnight window and holds the
`ollama-extract` resource for the whole run.

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

**Answer (1 Sep 2026): pasted — with Ali's own values, which supersede the
28 Aug researched set above and in `state.md`:**

```
GROQ_DEFAULT_MODEL=openai/gpt-oss-120b
GEMINI_DEFAULT_MODEL=gemini-3.6-flash
CEREBRAS_DEFAULT_MODEL=
NVIDIA_DEFAULT_MODEL=
CLAUDE_API_DEFAULT_MODEL=claude-sonnet-5
```

Three differ from the recommendation: Groq is the 120b not the 20b, Gemini
is 3.6-flash not 2.5-flash, and Cerebras is deliberately blank (see Q6).
These are Ali's values, not research output — `live-routing-probe` is what
establishes which of them actually serve, and it must report the changed
IDs by name.

**But the paste has not landed.** A key-name check of the repo-root `.env`
the same day found none of the five keys present (the file exists and is
1271 bytes; key names checked, no values read or printed). So **U2 is not
done and `live-routing-probe` stays `blocked`.** Either the lines went
somewhere other than the repo-root `.env`, or the paste is still to come.
Whoever confirms it re-runs the key-name check and flips the task.

## Q6 — Cerebras and Mistral rungs

Cerebras: free tier abolished 17 Aug 2026; every call 402s until a card
goes on file. Mistral: chat 403s, cause undocumented, likely workspace
plan activation (your dashboard, U9).

- **A (recommended): disable the Cerebras rung** (blueprint edit) until
  you ever decide to add a card; leave Mistral in place pending U9.
- B: add a card to Cerebras ($5 trial, expires in 30 days).
- C: leave both as-is (dead rungs mid-chain; the 402/403 handling is
  already fixed, so they just waste a hop).

**Answer (1 Sep 2026): split — Cerebras C, Mistral A.**
Cerebras: leave the rung as-is. No blueprint edit, no card.
Mistral: leave in place pending U9.

Consequence, verified in code rather than assumed: with
`CEREBRAS_DEFAULT_MODEL` blank the rung is still admitted by `_configured()`
(it declares no `model_env`, so the guard at `router/routing.py:255` does
not gate it), then skipped inside `route()` at `router/routing.py:216` with
`cerebras: no model configured`. That is a skipped loop iteration — no HTTP
call, no 402, and no cooldown entry. Cheaper than the 402 path C described.
Nothing to build; recorded so a later agent does not "fix" the blank.

## Q7 — How does voice reach the queue?

For the desk voice loop: a bearer-authed `POST /command` endpoint on the
bus, or the loop calling `db.jobs.enqueue` directly?

**Recommend A: `POST /command`** — it survives the bus moving to Oracle in
Phase 4; direct enqueue doesn't.

Unblocks: `voice-command-ingress`.

**Answer (1 Sep 2026): A, narrowed — `POST /command`, enqueue-only.**
The endpoint enqueues and returns a job id. It must not execute a command
inline, and must not grow a synchronous execution path later; the worker
remains the only thing that runs jobs.

## Q8 — Cloud STT fallback ownership

Blueprint says Groq Whisper is the STT fallback if the NPU disappoints.
The router is chat-completions-only; audio is a different endpoint shape.

**Recommend A: voice owns its own small Groq STT client** (no router
change). B: grow the router an audio lane (shared-interface change, big).

Unblocks: `stt-groq-fallback`.

**Answer (1 Sep 2026): A — voice owns its own small Groq STT client.**
No router change; the router stays chat-completions-only.

## Q9 — Live database maintenance approval

Three deferred items need your one-time approval because they write the
live `jobs` table / schema: a migration runner + ledger, sweeping the one
orphaned `queue-durability-probe-` row, and a retention/index pass. Also:
which Postgres driver may enter `requirements.txt` (there is none today —
that's why migration 0002 once sat unapplied). **Recommend `psycopg`
(v3, binary extra)** — your call, it's a component decision.

Unblocks: `db-maintenance`.

**Answer (1 Sep 2026): driver = `psycopg[binary]`** (v3). That settles the
component decision.

**Approval (1 Sep 2026, follow-up): yes — with the orphan row shown first.**

- Migration runner + ledger: approved, may write live schema.
- Retention/index pass: approved.
- Orphaned `queue-durability-probe-` row: **do not delete.** Report it to
  Ali — id, kind, status, age, payload shape — and stop there. Deletion is
  a separate approval.

`db-maintenance` is `ready`.

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

**Answer (1 Sep 2026): a — yes. c — yes. b — rewrite requested.**

- **a** approved: apply the §3.7 + §3.8 factual corrections.
- **c** approved: cooldown ledger is **process-lifetime**, with the
  executor (not the bus) reporting provider health. Unblocks
  `router-cooldown-ledger`.
- **b** — Ali wrote the replacement himself (1 Sep 2026). Apply this
  **verbatim**; it is his text, not a draft to improve:

  ### §3.3 Routing chain

  The blueprint does not enumerate rungs or state a rung count. Provider
  membership and ordering live in `providers.yaml`; live reachability lives in
  `docs/state.md`. Both are generated from the running config, not maintained
  by hand here.

  What the blueprint fixes is the shape, not the roster:

  - Rungs are ordered by cost class first (free-tier, then trial/credit, then
    paid), and within a class by measured p50 latency for the task profile.
  - A rung is eligible only if it has a configured key AND a verified 200 within
    the current verification window. Configured-but-unverified is not eligible.
  - `route(task_profile)` reorders within a cost class only. It never promotes a
    paid rung above a free one that is eligible; urgency does that, explicitly
    and per-job.
  - A rung that returns 401/402/403 enters cooldown and surfaces the denial. It
    does not silently fall through to paid work.
  - Removing a provider is a `providers.yaml` edit plus a `state.md` line. It is
    never a blueprint edit.

  `docs/state.md` carries two lists: routable, and configured-but-not-routable
  with a reason and a date per entry.

  It replaces the enumerated 8-rung list under "The routing pattern"
  (`docs/blueprint.md:82-93`). Four parts of it describe behaviour the code
  does not have yet — see the delta list in `blueprint-corrections`. Those
  are **not** this task's job; the task edits the blueprint only, and names
  the deltas in its Log so they become router work.

**Derived question — Q11 below.**

## Q11 — What is "the current verification window"?

Ali's §3.3 (Q10b) makes a rung eligible only with "a configured key AND a
verified 200 within the current verification window. Configured-but-
unverified is not eligible." The window has no duration, and nothing in
`router/` measures one today — there is no `last_verified`, no
`verification_window`, no `cost_class`, and no p50 latency anywhere
(grepped 1 Sep, zero hits).

Two things need a number or a rule:

1. **How long is the window?** **Recommend 24h**, refreshed by any 200 the
   router already sees in normal traffic, plus `live-routing-probe` as the
   cold-start refresher. Shorter means a quiet provider drops out of the
   chain for no reason; longer and "verified" stops meaning much.
2. **What happens at cold start**, when nothing has a fresh 200 — most
   obviously right after a reboot? **Recommend: treat an unverified rung as
   eligible-but-last within its cost class**, rather than ineligible.
   Strict reading of §3.3 empties the chain entirely and JARVIS answers
   nothing until a probe runs.

Say "24h + eligible-but-last" to take both, or give your own.

Blocks: the eligibility half of `router-eligibility-window` (new task).
Does not block `blueprint-corrections`, which applies your §3.3 text as
written regardless.

**Answer:** _pending_

## Q12 — Drop Pipecat from the desk loop?

`voice-loop` stopped before writing a line, on its own Constraints clause:
Pipecat is a stop-and-report if its abstractions fight this stack. They do.
Read off the installed packages, not upstream docs:

- **Transport needs a second PortAudio binding.** `pipecat.transports.local`
  hard-imports `pyaudio` (`pipecat-ai[local]`), which is not installed. The
  whole voice runtime here is `sounddevice`.
- **Its Kokoro is a different engine.** Pipecat's TTS service wants
  `kokoro-onnx`; installed is `kokoro==0.9.4`, the `KPipeline` path where you
  picked `am_puck` by ear.
- **Its wake word is textual, not acoustic.** Pipecat matches a phrase in a
  transcript, so STT must run continuously — the inverse of the openWakeWord
  gate that exists to keep Whisper large-v3 off the NPU until wake.
- STT (your whisper.cpp fork over HTTP) and the reply path (this repo's own
  router + memory) are custom subclasses too.

Five of six stages become custom code. Pipecat contributes its frame graph,
its Silero VAD analyzer, and interruption handling — and `silero-vad` 6.2.1
is installed standalone, so the VAD is yours either way. Barge-in was the
one real argument for keeping it; against a local `sounddevice` output
stream, stopping playback is an abort and a state change, not the buffered-
across-a-network-transport problem Pipecat's machinery solves.

**Recommend: drop Pipecat from §3.3's desk-loop clause, keep Silero VAD.**
Build the loop directly on `sounddevice` + `openwakeword` + `silero-vad` +
the existing `server_client` / `speak` / `router` seams. Pipecat stays
installed and stays the obvious choice if a later phase wants a networked
transport — WebRTC to your phone, say — which is the case it is built for.

Blueprint edit if you agree: `docs/blueprint.md` lines 112, 267, 338 and 342
all name "Pipecat + Silero VAD"; those become "Silero VAD", with §3.3's
"Assemble the Pipecat loop" becoming "Assemble the local loop".

Second opinion: `docs/consults/2026-09-02-pipecat-fit/` — verdict (B)
stop-and-report, confidence high. Full finding:
`docs/tasks/voice-loop-report.md`.

Blocks: `voice-loop`, and therefore `voice-command-ingress` behind it.

**Answer:** _pending_

## Q13 — What happens to the 98 dead-lettered `distill_memory` rows?

The chain is fixed and running again (`distill-chain-stall`, 2 Sep 2026), so
this is only about the wreckage it left.

**Nothing was lost.** Every one of those rows is a chain *link*, not a unit
of work: the payload is `{"reason": "seed"}` and nothing else, because the
handler deliberately keeps turn text out of the hosted queue. The work
itself lives in the local conversation store, and it was still there — the
7 turns distilled today came straight off that backlog. So **re-queueing
them would achieve nothing**, and that half of the question answers itself.

What is left is disposal, and they are the only evidence of the outage.

- **A (recommended): leave them.** They cost one `dead_letter` count on
  `/status` and nothing else. The failure they record is the reason
  `EmbeddingError` now carries a `cause`, and the reason the seed is
  throttled; deleting the evidence a week after reading it is how the same
  incident gets diagnosed twice.
- B: delete them once `db-maintenance`'s retention pass exists, as part of
  it rather than as a special case.
- C: delete them now.

B and C are destructive writes to the live table, so neither happens without
you. Q9's carve-out on the seven orphaned `queue-durability-probe-` rows is
the precedent: reported, left in place.

Blocks: nothing. The chain runs regardless.

**Answer:** _pending_
