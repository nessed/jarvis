# Questions for Ali — one sitting

The September improvement review is now available. See Q16 at the end for
the proposed package; the older answers below remain authoritative.

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


## Q14 — Backfill is stuck between your own two answers

`backfill-run` is blocked, and the thing blocking it is a contradiction
between two decisions you made 49 minutes apart on 2 Sep 2026.

**Q10a (01:53, `6bd3ad4`)** amended blueprint 1.3 to say fact extraction uses
"the `json_object` response format with pydantic validation and one retry —
**not** constrained JSON-schema structured decoding. That is what shipped and
what the code does."

**The blocker filed at 02:42 (`843bc26`)** says the opposite, and quotes 1.3's
*pre-amendment* text as its justification:

> `docs/blueprint.md` §1.3 already specifies this and the code does not do it:
> "...using **constrained JSON-schema structured decoding**."

That sentence no longer exists. It was replaced by its own negation before the
blocker was written. So the blocker's recommendation — "pass the fact schema
to Ollama as `format`" — is not conforming the code to the spec any more. It
is a request to change the spec back, which is yours and not an agent's.

**The measurements in the blocker are still good**, and they are the reason
this is not simply closed. On synthetic text at real chunk sizes:

```
unconstrained (what the code does today):   invalid JSON, twice, run aborted
schema-constrained, ~96-768 words:          4/4 valid, 26-29s, 12-15 facts
```

Both pass on small inputs, so the model is not the problem — the input size
is. The backfill sends chunks in the failing range.

- **A (recommended): re-amend 1.3 to constrained decoding, and file the task.**
  Your Q10a answer corrected the blueprint to match the code, which was right
  at the time — nobody had measured the code failing yet. Now someone has. The
  change is small: pass the schema through as Ollama's `format`, keep the
  existing validate-and-retry as a second line.
- B: keep `json_object` and make the backfill chunk smaller instead. Cheaper
  to try, but it is tuning around a decoder that is free to emit anything, and
  the failure returns at whatever the next size ceiling is.
- C: leave it. `backfill-run` stays blocked and blueprint 1.3 stays unbuilt.

Either way, note that the two timeout defaults are too tight for one serial
Ollama on this machine — extraction defaults to 90s and the real call takes
about that; embedding defaults to 15s and cannot survive an 8B generation
holding the runtime. Raising them is not a fix on its own (a run with both
raised still failed on decoding) but the fix cannot be tested without it.

Full evidence: `docs/blockers/mem0-extraction-not-schema-constrained.md`.

Blocks: `backfill-run`, and therefore blueprint 1.3.

**Answer:** _pending_

## Q15 — Which Whisper answers voice notes, and where does it run?

Measured 4 Sep 2026 on this laptop with `whisper-server` already warm and
the large-v3 encoder on the NPU (`docs/history/infra-audit-2026-09-04.md`):

```
7.6 s clip, lang=en : 11.2-17.6 s wall, CPU 53-69 % avg / 73-89 % peak, all 8 cores
7.6 s clip, lang=ur : 13.8 s wall, CPU 69 % avg / 89 % peak
```

That is the lag you feel. The NPU only runs the encoder; large-v3's
32-layer decoder runs on the CPU and dominates — `whisper-server.out.log`
says `no GPU found` for the decode side. It is also why a voice reply takes
40-50 s end to end even after every connection-reuse fix.

Three options. None is an agent's to pick: A sends your voice off the
laptop, B changes the model the blueprint names, C keeps the lag.

- **A (recommended for now): Groq `whisper-large-v3-turbo` as the primary
  STT, local NPU as the fallback.** Already built and live-verified the
  other way round (`stt-groq-fallback`, 2 Sep): word-perfect on English in
  about 1-2 s round trip. Cost: PKR 0 (free tier, ~2,000 clips/day). Trade:
  every voice note leaves the laptop. This is not memory content, so no
  non-negotiable is crossed, and the blueprint's own threshold says exactly
  this — "NPU Whisper too slow for live voice -> Groq Whisper free tier".
  What is unknown is Urdu quality under the forced `ur` hint on the cloud
  tier; U11 is the one-minute test that settles it, and if it degrades, the
  fallback gets its own language setting. A one-line env switch
  (`JARVIS_STT_PREFER_CLOUD=1`) is the whole implementation.
- **B: local large-v3-turbo.** Same encoder as large-v3, so the compiled
  `.rai` NPU graph should carry over; the decoder drops from 32 layers to 4.
  Expect roughly 3-5x faster decode and a 1.6 GB model instead of 3.1 GB,
  with Urdu still supported. Needs a build-and-verify session (download,
  confirm the NPU encoder loads, measure) and it changes the model named in
  blueprint §2. Voice stays on the laptop. Can be done after A, as the
  fallback tier's upgrade.
- **C: keep large-v3 on the laptop.** Nothing changes; the 11-18 s and the
  CPU load stay.

A and B are not exclusive. Recommend **A now, B when there is a spare
evening**, in that order, because A is one env var and measurable in a day.

Blocks: `stt-latency-decision`.

**Answer:** _pending_

## Q16 — September architecture improvement package

Ali requested a review and plan, not implementation. The complete frozen
proposal, source evidence, costs, September sequence and acceptance criteria:

[Architecture review and September plan](../history/architecture-review-2026-09-08.md)

Review its section 11 as one package. Recommendation: an always-on cloud
conversation core, predictable interactive model routing, bounded Claude/Codex
task workers, local private memory, then activated voice and the presence UI.
The package identifies the hosting/budget, data scope, one-pass conversation,
speech routing, Pipecat integration and workflow decisions explicitly.
It does not supersede Q1, Q5, Q8, Q12, Q15 or the blueprint without an answer.
No proposed task has been marked ready and no architecture was implemented.

Separate review-only gate: automatic approval review rejected sending the
prepared project briefs to Claude. Permission to send those briefs and the
referenced non-secret source/docs to Claude for the Opus 5 cross-check would
unblock independent review, not deployment or access to personal data.
Exact scope and failure: [review-export blocker](../blockers/architecture-review-opus-export.md).

**Architecture package answer:** _pending_

**Independent review export answer:** _pending_

## Q17 — Reconciling Astra's and Fable's reviews

Fable 5.1 wrote a second, independent architecture review at your request
(`docs/history/architecture-review-fable-2026-09-08.md`), without reading
Astra's. Its own D1-D13 decision list was never added here. Both reviews
agree on the diagnosis; two of their recommendations directly contradict
each other, and both are architecture-shape or non-negotiable calls, which
`agents.md` reserves for you regardless of how obvious either side's case
looks to an agent. The rest of Fable's D-list is new ground, not yet
tracked anywhere answerable.

### 17.1 — The two real conflicts, no recommendation given

**Memory placement (non-negotiable #3).** Astra: keep it as written —
embeddings/extraction/recall stay laptop-only, the cloud core only holds
short-term turn state. Fable: amend it to permit memory on a VPS Ali
controls, or extraction via a contractual zero-retention provider (Groq,
Fireworks) — arguing the rule's *purpose* (no training on private content,
no geo-blocked/free-tier exposure) survives the amendment, only its
"loopback-only" wording doesn't. This is the one call that decides whether
recall works with the laptop off at all.

**Does conversation skip the durable queue?** Astra: keep enqueue-before-ack
for everything, including chat — that discipline is what the enqueue-only
bus rule exists for. Fable: webhook returns 200 and hands the message to an
in-process handler on the VPS; only laptop-bound actions still go through
Supabase. Fable's own case for this depends on memory also living on the
VPS (17.1's first question) — if memory stays on the laptop, this one's
moot and Astra's shape is probably right by default.

**Recommend, on reflection — a synthesis of both, not a pick between them:**

**Memory: amend #3's *scope*, not its guarantee.** The rule's own text gives
its reason: no hosted fallback because a provider might train on private
content or be unreliably geo-blocked. That reasoning objects to a
*third-party model provider* seeing private content — it says nothing
about which of Ali's own machines runs the code. Fable's memo ("the
brother's offer removes constraint 1; amend constraint 2 in one sentence")
treats the cash constraint and the privacy constraint as one thing; they
aren't. Recommend: reword "loopback-only" to mean *infrastructure Ali owns
and administers* (laptop or his own VPS), which unblocks always-on recall
without weakening the guarantee at all. Recommend declining the other half
of Fable's D2 — routing extraction/embeddings through a third-party
"zero-retention" API (Groq, Fireworks) — because a contractual promise not
to retain is a materially weaker guarantee than data never leaving Ali's
own boxes, and closing exactly that gap is what #3 was written for. Keep
extraction as a nightly local batch (laptop or the new VPS) either way;
Fable's own alternative (b) already describes this and it costs nothing
extra.

**Performance note, 8 Sep 2026 (reasoned from measured specs, not a fresh
benchmark):** recall/lookup is under 1 s either place and moving it to a
rented box is a wash on speed — its value is laptop-off availability, not
speed. Extraction (`llama3.1:8b`, 15-55 s/chunk measured on the laptop's 8
real cores today) is the opposite case: a budget VPS in the $10-12/month
class (2 shared vCPUs, 2-4 GB RAM) would likely run this *slower* than the
laptop, not faster — the model needs ~5 GB just to load, and shared/
burstable vCPUs are typically weaker per-core than dedicated laptop cores.
Don't move extraction to the cheap VPS tier under discussion. Either keep
it on the laptop with a lighter, GPU-capable model (Qwen3-4B via llama.cpp
Vulkan — no rental needed, should beat today's CPU-only 8B model on this
same machine), or send it to Groq's cloud, which is the third-party-privacy
tradeoff already declined above. A VPS big enough to beat the laptop at
this specific job is a much bigger box than the one being priced.

**Queue: keep durable-enqueue, kill the idle-poll wait, not the queue.**
Astra's durability point holds — an in-process fire-and-forget reply task
that dies with the process on a crash or redeploy is silently lost, with no
row anywhere to show it happened; the current bus is tested precisely
against that failure. But the 3-5 s Fable is objecting to isn't durability
overhead, it's *poll-sleep* overhead: 0-3 s of idle sleep plus three
separate RPC round trips because a claim/checkpoint/complete cycle assumes
an unrelated process wakes up later and asks. Astra's own §5.2 already
names the fix — persist the job, then wake the consumer directly instead of
polling on an interval — and that closes nearly all of the latency gap
Fable is chasing without dropping the durability property. Recommend: build
that, not a full queue bypass. This also makes the memory question above
mostly moot for D5's own stated reason (Fable's case for skipping the queue
was "the queue's benefit is smaller once memory is already local to the
same process") — the notify-on-enqueue version gets there either way.

Neither half of this needs a new architecture; both are within reach of the
code that already exists. The #3 rewording still needs your explicit
sign-off since it touches a non-negotiable's wording, even though the
guarantee itself is unchanged.

**Answer (queue question, 8 Sep 2026): for now, answer right away.** Skip
durable-enqueue-before-ack for ordinary conversation; reply in-process
immediately rather than writing a job and waiting on a worker to pick it
up. Explicitly interim, not a permanent architecture call — if lost
messages during a crash/redeploy turn out to matter in practice, this gets
revisited rather than silently kept. Note the dependency: this only pays
off once the reply path doesn't have to call back to the laptop for
memory, so its real effect rides on the memory answer below, which is
still open.

**Answer (memory question, 8 Sep 2026): yes, as recommended.** Reword
non-negotiable #3's "loopback-only" to mean infrastructure Ali owns and
administers (laptop or a rented server he controls) — recall/lookup moves
to the rented server for laptop-off availability. Extraction stays off the
cheap rented tier per the performance note above: local batch (laptop,
lighter GPU-capable model) rather than the VPS or a third-party API.
Third-party "zero-retention" providers for extraction/embeddings remain
declined; that guarantee doesn't move.

### 17.2 — New decisions from Fable's D-list, not yet asked anywhere

- **D1 — Hosting.** Brother's AWS (Fable: Mumbai, smallest ≥2 GB plan) vs.
  Oracle Always Free (free, but idle-reclaim terminates a quiet box after 7
  days under 20% utilization at p95 — a heartbeat job avoids it) vs. Fly.io.
  Astra leaves this an open menu pending quotes; Fable picks AWS decisively.
  Recommend: AWS via your brother if the offer is still open — it removes
  the idle-reclaim risk and the account-speed unknown.
  *8 Sep 2026: Ali said "idm rented" and did not object to the AWS 2 GB
  Mumbai recommendation when it was restated; taken as the working answer.
  The physical step is U17. If he provisions something else, U17 and
  `vps-harden-deploy` adapt — the runbook keeps both sections.*
- **D4 — Flip the single-call default.** Both reviews want classify+reply
  merged into one model call (constants still dispose). It is being built
  behind `JARVIS_SINGLE_CALL_REPLY` (default off) by
  `single-call-classify-reply`, which will paste its two-mode evaluation
  table here. The decision is only whether to make it the default once the
  table exists. Recommend: yes, if action/refusal agreement is ≥ 95% on
  the fixture set.

  *9 Sep 2026 — the table exists now (`single-call-classify-reply`). Built
  behind `JARVIS_SINGLE_CALL_REPLY`, default off. 23 fixtures, both modes,
  live router, through the real service:*

| # | category | message | two-call | one-call | agree |
|---|---|---|---|---|---|
| 1 | chat | hey, what's up? | conversation | conversation | yes |
| 2 | chat | In one sentence, what is the boiling point of water at se... | conversation | conversation | yes |
| 3 | chat | can you explain what a hash map is, briefly | conversation | conversation | yes |
| 4 | chat | what's a good way to remember someone's name | conversation | conversation | yes |
| 5 | chat | thanks, that helped | conversation | conversation | yes |
| 6 | chat | how many days are there in a leap year | conversation | conversation | yes |
| 7 | chat | I'm thinking about learning the guitar | conversation | conversation | yes |
| 8 | command | turn wifi off | action (wifi.set_enabled) | action (wifi.set_enabled) | yes |
| 9 | command | turn the wifi back on | action (wifi.set_enabled) | action (wifi.set_enabled) | yes |
| 10 | command | switch to the balanced power plan | action (power.set_plan) | action (power.set_plan) | yes |
| 11 | command | what power plan am I on | action (power.get_active_plan) | action (power.get_active_plan) | yes |
| 12 | command | list my bluetooth devices | action (bluetooth.list_devices) | action (bluetooth.list_devices) | yes |
| 13 | command | turn bluetooth off please | action (bluetooth.set_enabled) | action (bluetooth.set_enabled) | yes |
| 14 | command | switch my display to the second monitor | action (display.switch) | action (display.switch) | yes |
| 15 | destructive | kill the chrome process | confirm | confirm | yes |
| 16 | destructive | print the file at C:/tmp/report.txt | confirm | confirm | yes |
| 17 | destructive | zip up the folder C:/tmp/notes | confirm | confirm | yes |
| 18 | destructive | rename C:/tmp/a.txt to C:/tmp/b.txt | confirm | confirm | yes |
| 19 | excluded | send a whatsapp message to the group saying I'm running late | refuse | refuse | yes |
| 20 | excluded | sort the mixer tracks in my FL Studio project | refuse | refuse | yes |
| 21 | follow-up | and the other one? | conversation | conversation | yes |
| 22 | follow-up | do that again | conversation | conversation | yes |
| 23 | long | Here is a long note I want you to read: the quick brown f... | conversation | conversation | yes |

| metric | result |
|---|---|
| Full agreement (decision + kind + action) | 100% (23/23) |
| Action agreement | 100% (7/7) |
| Refusal agreement | 100% (2/2) |
| Confirm-first agreement | 100% (4/4) |
| Reply present, two-call | 100% (23/23) |
| Reply present, one-call | 100% (23/23) |
| Median seconds, two-call | 1.1s |
| Median seconds, one-call | 0.9s |
| Errors | two-call 0, one-call 0 |

  *Every category agreed: 7 chat, 7 reversible commands, 4 destructive (all
  held for confirmation by the table, both modes), 2 excluded kinds (refused
  with their own reason), 2 follow-ups, 1 over-length. Zero disagreements,
  zero errors, a reply present on all 46 runs. **Your bar was action/refusal
  agreement ≥ 95%; both are 100%, and so is confirm-first.** Two caveats: the
  latency columns are weak evidence (openrouter was unusually fast during the
  run — the same provider varied 1.0-12.0 s earlier the same day), and this is
  one provider, because the ladder is collapsed to one rung until U2. The
  recommendation stands: flip it. Say the word and it is a one-line default
  change plus a test.*
- **D6 — TTS and Urdu.** Fable found Kokoro has **no Urdu support at all**
  — a factual gap Astra's review doesn't check, since Astra's plan keeps
  Kokoro (`am_puck`) on the reply path. If you want Urdu replies, Kokoro is
  disqualified regardless of which architecture wins; the choice is then
  Inworld TTS-2 or Azure `ur-PK`, by ear (~$1/month either way). Also
  decide, separately: should JARVIS answer in Urdu at all?
- **D7 — `claude -p` as a general unattended laptop executor.** Both
  reviews want Claude wired into task execution; the open question is
  scope — Fable recommends starting read-only plus the existing action
  table, widening per task class after a week of logs. This is the
  highest-blast-radius change either review proposes (unattended tool use
  on your machine) and needs its own explicit yes, not a bundled one.
- **D9 — Provider roster cleanup + a purchase.** Drop NIM and Cerebras from
  `providers.yaml` (NIM is confirmed Pakistan-blocked; Cerebras is dead
  weight per Q6's own answer), route DeepSeek overflow via OpenRouter
  instead of direct (cheaper, sidesteps the Pakistani-card problem), and
  buy the one-time $10 OpenRouter credit that lifts its free tier from 50 to
  1,000 requests/day. The $10 is the only real spend in this item.
- **D10 — Skip paid Gemini 2.5 Flash-Lite as a second latency lane.** Both
  reviews treat this as low-value while Groq's free tier covers the
  expected volume. Recommend: skip, revisit only if Groq's rate limit is
  actually hit.
- **D13 — Process change.** Adopt the latency targets either review states
  as `tests/live` acceptance criteria, and let agents pull any lever that
  keeps constants-dispose/secrets/destructive-op rules intact without a
  fresh Class C question per lever. This is what turns "ten questions
  accumulated while agents optimized connection reuse" (Fable §2.6) into
  actual throughput. Recommend: yes.

**Answer (each):** _pending_

### 17.3 — Existing questions this new evidence touches

- **Q12 (Pipecat)** has fresh, conflicting input: Astra now argues to
  reopen it for one timeboxed integration spike; Fable reaffirms the
  existing "drop" recommendation. Q12 itself is still unanswered, so this
  doesn't reopen a closed decision — it just adds a third position to
  weigh when you get to it.
- **Q15 (STT)** is unaffected — Fable's D3 independently confirms Q15's
  recommendation A (Groq Whisper turbo primary, NPU fallback).
- **`docs/state.md`'s provider tables** should absorb Fable's §3 "facts
  that moved" table regardless of which architecture direction you pick —
  it's corrections, not a proposal: Groq's Llama rungs dead since 16 Aug,
  Cerebras' context cap wrong (65K/131K, not 8K), Hetzner's cost-optimized
  tier currently unbuyable, Kokoro's missing Urdu, NIM's confirmed
  Pakistan block. This can happen as ordinary housekeeping, same precedent
  as Q10a, without waiting on 17.1-17.2.

**Nothing downstream builds differently based on 17.2 or 17.3 — those are
safe to answer now.** 17.1's two questions are the actual bottleneck: every
other line in both reviews' plans (hosting size, budget, what week 1
delivers) branches on where memory ends up living.

**Blueprint deltas from `state-facts-refresh` (9 Sep 2026), for one blanket
yes** — `docs/state.md` absorbed everything correctable there (see its
Provider rungs / Open blockers sections, dated 8-9 Sep); these four are
`docs/blueprint.md`'s own text and are not edited without your say-so per
`agents.md`:

- **Cerebras context is 65K free / 131K paid, not 8K.** Blueprint §"Cerebras"
  and the routing-pattern paragraph both hardcode 8K (lines naming it: the
  Cerebras section's own text, and "Cerebras is 8K context, Groq TPM is
  tight" under DeepSeek's overflow-valve note). Both should read 65K/131K
  free, higher paid.
- **NVIDIA NIM should drop out of blueprint §1 and the Phase 4 API-key list
  as a routing/VPS candidate.** Confirmed geo-blocked from Pakistan (+92
  absent from phone verification) plus a per-org 404 gate on the API — this
  is stronger than the existing "geo-blocked from Pakistan for private
  memory content" carve-out (CLAUDE.md #3, blueprint 1.3), which only
  excludes it from *extraction*. It cannot be reached at all, from here, for
  anything.
- **Hetzner CX22 (~PKR 1,240/mo) is not currently a real fallback.** Every
  cost-optimised plan shows "currently unavailable" as of 8 Sep 2026. The
  blueprint names it as the paid fallback in three places (the routing
  section, the Oracle-signup step, and the budget line). Superseded anyway
  by U17's AWS answer, but the text should stop pointing at a plan that
  cannot currently be bought.
- **Kokoro as "the voice" is unchanged as a decision** (Ali picked it by
  ear, 29 Aug 2026) **but the blueprint should say plainly that it has no
  Urdu voice**, rather than leaving that discoverable only from
  `docs/state.md`'s WhatsApp voice wiring row and
  `executor/conversation/service.py`'s own comment. Not a request to revisit
  the choice — recorded on `hosted-urdu-tts`'s blocked task already — just a
  drift-prevention note so the blueprint doesn't read as though Kokoro
  covers both languages.
- **§"Phase 4 — Always-on split" (4.1-4.4) still walks through the Oracle
  path, not the AWS one this section already answered** (D1: "AWS via your
  brother... taken as the working answer"). Found by `board-audit`,
  9 Sep 2026, after `bus-offbox-packaging` made the drift concrete: 4.1
  says "Oracle signup"; 4.2 says "one A1 instance at exactly 2 OCPU/12GB"
  and "Deploy bus + router **+ web UI** as containers" — no Terraform
  module or A1 sizing applies to AWS, and the web UI container is the
  standing "no UI until necessary" decision (`PARKED.md`), not something
  either box runs. This isn't a new decision, just this section's text not
  yet reflecting the one already made — flagged rather than rewritten,
  since blueprint edits stop and ask first regardless of how settled the
  underlying decision is.

**Answer:** _pending_
