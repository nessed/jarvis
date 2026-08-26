# Phase 1 review — what works, where it stops scaling

27 August 2026. `HEAD` `129de3a`. 152 tests passing. Phase 0 complete, Phase 1
partial.

Every figure here was measured on this machine during the 26-27 August session,
not estimated. Read `docs/state.md` for current component status and
`docs/history/whatsapp-reply-failures.md` for the full failure analysis this
review draws on.

## Verdict

The WhatsApp reply loop is live and every real message completes. The memory
system it was built to serve does not work on this hardware — and that is a
constraint the blueprint's own privacy rule creates, not a bug left to fix.

| | |
|---|---|
| Real messages | **34 / 34** reached `done`. Zero failed, zero dead-lettered |
| Reply latency | **~3s** (recall + route + send, memory writes off) |
| Memory writes | **0%** success on live turns before being disabled |
| Throughput ceiling | **~20 msg/min** (one executor, one job at a time) |

Five separate causes had to be cleared before a message reliably came back: a
migration never applied to the live project, a prompt patch that only worked
once per process, a token limit that truncated real output, a batch job
monopolising the local model, and memory writes that failed every time. All
five are fixed or contained.

What did not survive contact is the thing Phase 1 exists for. The blueprint's
success test is *"you tell it something on Monday and it uses it unprompted on
Thursday."* That is currently impossible: conversation memory writes are
disabled because they never once succeeded.

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

Extraction succeeded in 5.9s, 10.3s and 11.5s on an otherwise idle machine. In
production it succeeded **zero times**, because the machine is never idle: the
reply, the embedding, and anything else sharing Ollama contend for the same CPU.

## Scaling limits

| Component | Ceiling | Binding constraint | State |
|---|---|---|---|
| Local Ollama | 1 request | Serial and shared. Any batch job blocks all live replies for its full duration | **Hard limit** |
| Executor poller | ~20 msg/min | Single-threaded, one job claimed at a time. Ceiling is 1 ÷ job duration | Adequate now |
| Memory writes | ~0.5 msg/min | Two 8B extractions per message. Collapses the executor ceiling 40x | **Disabled** |
| Mem0 store | ~1,000 facts | Blueprint's own threshold for migrating to Graphiti. Currently 68 facts | Far from limit |
| Cloudflare tunnel | No uptime SLA | Quick Tunnel URL dies whenever cloudflared restarts; Meta needs re-pointing | Fragile |
| Laptop availability | Awake only | Queue absorbs downtime, but nothing executes while the machine sleeps | By design |

Only two bind today. **Ollama's serialisation is the sharp one** — it is why a
corpus backfill silently starved eight incoming messages, and nothing in the
current design prevents that recurring. Executor throughput is comfortable for
one user; it would need revisiting only if jobs became long-running or
multi-user.

## Blueprint vs. reality

| Blueprint position | Outcome | |
|---|---|---|
| Phase 0 — bus, queue, executor, router | Held completely. Durable queue, atomic claim, retry/backoff/dead-letter all behaving under real failure | Held |
| Mem0 is the right starting pick | Wrapper, sqlite-vec store and index are correct and tested. Mem0 was not the problem | Held |
| 1.4 — recall before, remember after every message | Amended with authorisation: reply now sends *before* the memory write, so extraction can no longer delay or discard a reply | **Amended** |
| 1.3 — extraction via local Ollama + structured decoding | This amendment (replacing NIM/Gemini for privacy) is precisely what created the bottleneck. Correct on privacy, unworkable on this CPU | **Backfired** |
| Phase 1 done = "Monday fact used on Thursday" | Not met. Nothing from conversation is written to memory at all | **Not met** |
| "Plain markdown + local semantic search remains the underrated portable option" | The blueprint already names the way out — see below | Unused |

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

1. **Backfill and conversation cannot coexist.** No guard exists. A batch run
   silently starves live replies for as long as it runs — this already happened
   once. Either serialise them explicitly or refuse to start a backfill while
   the executor is polling.
2. **The tunnel is a single point of failure.** Every cloudflared restart mints
   a new URL and requires re-pointing Meta. A named tunnel is deferred to Phase
   4, which is the right call, but the fragility is live now.
3. **Unit tests could not have caught any of these bugs.** All five passed a
   green suite. What found them was replaying real failing job payloads through
   the real handler with only the outbound send faked. That belongs in the
   standard toolkit for anything that works in test and fails in the field.
4. **The Meta app is still unpublished.** Only test events are delivered — fine
   for now, blocking for real use.

---

Failure counts above exclude test probes: of 76 total queue rows, the 17
`failed` and 5 `dead_letter` are all synthetic kinds from earlier integration
runs. All 34 `whatsapp_webhook` rows are `done`.
