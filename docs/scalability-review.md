# Phase 1 review — what works, where it stops scaling

27 August 2026, **revised** after the recommendation below was implemented.
196 tests passing. Phase 0 complete, Phase 1 partial.

The four options table and the recommendation are kept as written. Options 1
and 2 were adopted together: turns are stored raw and inline, extraction runs
as a batch. Figures elsewhere in this document have been updated to match.

Every figure here was measured on this machine during the 26-27 August session,
not estimated. Read `docs/state.md` for current component status and
`docs/history/whatsapp-reply-failures.md` for the full failure analysis this
review draws on.

## Verdict

The WhatsApp reply loop is live and every real message completes. Memory now
works too, but only because fact extraction was taken off the reply path — the
underlying constraint (private content must be extracted locally, and local
extraction is slow) is unchanged, it is routed around rather than solved.

| | |
|---|---|
| Real messages | **34 / 34** reached `done`. Zero failed, zero dead-lettered |
| Reply latency | **4-11s** measured end to end on the live queue |
| Memory writes | **~0.5s** per turn (embed and store). Extraction moved to a batch |
| Throughput ceiling | **~20 msg/min** (one executor, one job at a time) |

Five separate causes had to be cleared before a message reliably came back: a
migration never applied to the live project, a prompt patch that only worked
once per process, a token limit that truncated real output, a batch job
monopolising the local model, and memory writes that failed every time. All
five are fixed or contained.

The blueprint's success test is *"you tell it something on Monday and it uses
it unprompted on Thursday."* That now works for raw conversation turns —
verified live, stored and recalled in 0.61s. It does **not** yet work for
distilled facts, which wait on a batch nobody schedules.

### The root constraint

Fact extraction must run locally — non-negotiable #3 forbids sending private
content to hosted models, because NIM is geo-blocked from Pakistan and Gemini's
free tier may train on prompts. Local extraction on this CPU takes **20-130
seconds per call** and the handler makes two per message.

The privacy rule and the hardware are *jointly* the blocker. Neither a longer
timeout nor a different cloud provider resolves it without changing one of them.

## Measured — where the time goes

| Step | Time |
|---|---|
| Embedding lookup | 0.49s (median of 5, warm) |
| LLM reply, routed | ~2s |
| Extraction, idle machine | 6-12s (measured 5.9 / 10.3 / 11.5) |
| Extraction, under load | 60-130s |

Reading memory is roughly **250x cheaper than writing it** — the embedding
model is 137M parameters, the extraction model is 8B. That asymmetry is what
makes the recommendation below viable.

Extraction succeeded in 5.9s, 10.3s and 11.5s on an otherwise idle machine. On
the live reply path it succeeded **zero times**, because the machine is never
idle there: the reply, the embedding, and anything else sharing Ollama contend
for the same CPU. Run as a batch with nothing competing, one turn took 55.3s —
slow, but reliable. That gap between "idle" and "live" is the whole argument
for batching.

## Scaling limits

| Component | Ceiling | Binding constraint | State |
|---|---|---|---|
| Local Ollama | 1 request | Serial and shared. Any batch job blocks all live replies for its full duration. Guarded by `executor/heartbeat.py` | **Hard limit** |
| Executor poller | ~20 msg/min | Single-threaded, one job claimed at a time. Ceiling is 1 ÷ job duration | Adequate now |
| Memory writes | ~120 msg/min | Two embeddings per message at ~0.5s. No longer the constraint | Resolved |
| Mem0 store | ~1,000 facts | Blueprint's own threshold for migrating to Graphiti. Currently 68 facts | Far from limit |
| Cloudflare tunnel | No uptime SLA | URL dies whenever cloudflared restarts. `start-jarvis.bat` re-points Meta automatically now | Fragile |
| Laptop availability | Awake only | Queue absorbs downtime, but nothing executes while the machine sleeps | By design |

**Ollama's serialisation is the sharp one** — it is why a corpus backfill
silently starved eight incoming messages. `executor/heartbeat.py` now stops
batch tools starting while the executor polls, but the underlying single-lane
constraint is unchanged. Executor throughput is comfortable for
one user; it would need revisiting only if jobs became long-running or
multi-user.

## Blueprint vs. reality

| Blueprint position | Outcome | |
|---|---|---|
| Phase 0 — bus, queue, executor, router | Held completely. Durable queue, atomic claim, retry/backoff/dead-letter all behaving under real failure | Held |
| Mem0 is the right starting pick | Wrapper, sqlite-vec store and index are correct and tested. Mem0 was not the problem | Held |
| 1.4 — recall before, remember after every message | Amended with authorisation: reply now sends *before* the memory write, so extraction can no longer delay or discard a reply | **Amended** |
| 1.3 — extraction via local Ollama + structured decoding | This amendment (replacing NIM/Gemini for privacy) is precisely what created the bottleneck. Correct on privacy, unworkable on this CPU | **Backfired** |
| Phase 1 done = "Monday fact used on Thursday" | Now met for raw turns: a turn stored and recalled in 0.61s, verified live. Distilled facts still lag until the batch runs | Partly met |
| "Plain markdown + local semantic search remains the underrated portable option" | Adopted. This is now the live memory path | **Adopted** |

## Four ways to make memory real

| Option | Cost per turn | Trade-off | Privacy rule |
|---|---|---|---|
| Store raw turns + embeddings, skip LLM extraction | ~0.5s | Recall works immediately. Loses structured facts, dedup and contradiction handling — you search conversations rather than distilled facts | Intact |
| Batch extraction overnight | ~0s live | Keeps full Mem0 behaviour; memory lags by a day. Reuses the resumable backfill runner that already exists | Intact |
| Smaller extraction model | unknown | Unproven. `qwen3:4b` was tested and produced valid schema 0/10 — its reasoning tokens consumed the output budget | Intact |
| GPU, or extraction off this box | ~1s | Fastest path technically. Off-box means hardware spend, or sending private content to a hosted model | **Needs amendment** |

**Recommendation: combine the first two.** Write raw conversation turns with
embeddings inline — cheap enough to be invisible at 0.5s — and run Mem0's fact
extraction as a nightly batch over those stored turns. Recall works the same
day, full fact-extraction behaviour still arrives, and the privacy boundary is
untouched. It also matches the option the blueprint already flagged as
underrated.

## Open items, ranked by consequence

1. ~~Backfill and conversation cannot coexist.~~ **Guarded.**
   `executor/heartbeat.py` makes batch tools refuse to start while the executor
   is polling. `tools/run_backfill.py` still needs the same one-line check.
2. **Nothing schedules distillation.** Turns accumulate undistilled until
   `tools/distill_memory.py` is run by hand, and it needs a window with the
   executor stopped.
3. ~~The tunnel is a single point of failure.~~ **Reduced, not removed.**
   `start-jarvis.bat` mints a tunnel and re-points Meta on every run, so the
   manual step is gone — but nothing receives while the laptop is off. Moving
   the bus off the laptop is Phase 4.
4. **Unit tests could not have caught any of these bugs.** All five passed a
   green suite. What found them was replaying real failing job payloads through
   the real handler with only the outbound send faked. That belongs in the
   standard toolkit for anything that works in test and fails in the field.
5. **The Meta app is still unpublished.** Only test events are delivered — fine
   for now, blocking for real use.

---

Failure counts above exclude test probes: of 76 total queue rows, the 17
`failed` and 5 `dead_letter` are all synthetic kinds from earlier integration
runs. All 34 `whatsapp_webhook` rows are `done`.
