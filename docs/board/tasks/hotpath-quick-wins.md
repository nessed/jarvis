---
id: hotpath-quick-wins
status: done
lane: AUTO
priority: 1
phase: 4
blocked-on: latency-spans (so the before/after is measured, not guessed)
files: memory/embeddings.py, memory/conversation.py (hot within memory), executor/conversation/service.py, tools/start_jarvis.py, voice/stt_fallback.py, voice/whisper/ (Groq client only), tests/memory/, tests/voice/, tests/tools/test_start_jarvis.py
resources: none
---

# hotpath-quick-wins — the zero-decision latency levers

## Why

Fable §6 week 1 item 2 and Astra §3.1 list the same incidental costs on
every text reply. None needs a decision; all were measured on 4 Sep:

| Lever | Today | Where |
|---|---|---|
| Worker idle sleep before it sees a job | launcher passes 3 s, default 5 s | `tools/start_jarvis.py` (`JARVIS_POLL_INTERVAL_SECONDS`), `executor/poller.py:58` |
| Recall runs *before* the model call, serially | ~0.6 s | service |
| Fresh `httpx.Client` per embedding call | ~0.1-0.6 s | `memory/embeddings.py:147` |
| Memory runtime rebuilt per message: Ollama dimension probe + sqlite opens + sqlite-vec load | 0.1-1 s | `memory/conversation.py`, handler construction |
| Groq STT SDK client built per transcription | small, per voice note | `voice/stt_fallback.py` / Groq backend |

Expected together: ~10 s → ~5 s for text (Fable's estimate). Prove it with
`latency-spans`, don't repeat the estimate.

## Steps

1. Poll interval: launcher passes `1` (not 3); default stays 5 for anyone
   running the poller by hand. Test in `test_start_jarvis.py`.
2. Embeddings: one `httpx.Client` per process, created lazily, closed at
   exit. The loopback-only guard stays exactly as it is (CLAUDE.md #3 —
   loopback on *this* host).
3. Memory runtime: open once per worker process (probe dimension once,
   keep the sqlite connection and the vec extension loaded). Dimension
   drift check still runs — once, at open — and still fails closed.
4. Recall in parallel with the model call **only when the reply prompt
   does not need recall results** — that is not the case today (recalled
   facts go into the prompt), so the real lever is: start the recall
   embed at the same time as the classifier call and await both. If the
   classifier is merged away later (`single-call-classify-reply`), this
   collapses naturally. Do not restructure the prompt to make it
   parallel; report if that is the only way.
5. Groq STT client: construct once per process, reuse.
6. Re-run `tests/live/test_text_reply_latency.py` and paste before/after
   `reply_latency.py` output into the Log.

## Done when

Offline suite green; live latency line shows `queue_wait_ms` under ~1,100
and `recall_ms` down measurably; both numbers in the Log.

## Log

### 2026-09-09 — done (lane-1), with one half deferred to U20

**The headline.** Recall p50 fell from **1.24 s to 0.10 s** per message, and it
now runs *beside* the classifier instead of after it, so on the reply path it
costs nothing at all. Measured on the real handler, both trees, same laptop,
same prompt, same memory database, one process each.

**Before** — worktree at `d7c19ef`, 6 replays through `tools/replay_job.py`
(real recall, real routed calls, sends faked):

```
stage             p50      p95      max     n
classify        3.30s   92.31s   92.31s     6
recall          1.24s    1.33s    1.33s     6
model           2.64s    5.72s    5.72s     6
total           7.33s   94.77s   94.77s     6
```

Per-message `recall_ms`: 1333, 1283, 1240, 1211, 1311, 1212. Flat. Every
message paid the same opening cost.

**After** — this tree, 5 replays, same harness:

```
stage             p50      p95      max     n
classify        4.87s   10.00s   10.00s     5
recall          0.10s    1.24s    1.24s     5
model           3.94s   12.00s   12.00s     5
total           9.69s   22.02s   22.02s     5
```

Per-message `recall_ms`: 1238, 101, 103, 85, 82. The first message in a process
pays the probe; nothing after it does. That is the whole shape of the change.

**Read `classify`, `model` and `total` as noise, not as results.** Both routed
calls go to `openrouter/free` and the same prompt varied between 1.0 s and
12.0 s within a single run. Nothing in this task touched routing, and six
samples of a provider that unstable cannot show anything. `recall` is the
stage this task moved, it is local, and it moved by 12x.

**The five levers.**

1. **Poll interval 3 s → 1 s** (`tools/start_jarvis.py`). Dead time before any
   work starts. The poller's own default stays 5 for anyone running it by
   hand, where the sleep is between background sweeps and nobody is waiting.
   Not visible above: a replay does not go through the queue. Its effect is
   arithmetic — mean wait falls from ~1.5 s to ~0.5 s — and the live
   `queue_wait_ms` confirmation is the deferred half below.
2. **One `httpx.Client` per process for embeddings** (`memory/embeddings.py`),
   keyed on (base_url, timeout, transport) and closed at exit. Every embed
   used to build and tear one down inside a `with`. Keyed rather than global
   because `transport=` is a test seam and two fakes must not share a client.
3. **The dimension probe, once per process** (`memory/runtime.py`), keyed on
   (model, base_url). This is nearly the whole 1.2 s: measured separately,
   the probe is 463-674 ms and both sqlite opens are 7 ms, against the real
   286-fact store.
4. **Recall beside the classifier** (`executor/conversation/service.py`).
5. **One Groq STT client per process** (`voice/stt_fallback.py`), both the
   `GroqSttClient` itself and the SDK client inside it. `None` is cached as a
   real answer, so an unconfigured process does not re-read the environment on
   every voice note.

**Step 3 was implemented narrower than written, on measured grounds.** The
task said "keep the sqlite connection and the vec extension loaded". Two
findings say not to. The probe is 463-674 ms and both sqlite opens are 7 ms,
so the sqlite half is 1.4% of the lever. And every job runs on a **fresh
thread** (`executor/poller.py:_run_with_timeout`), while both stores open with
sqlite3's default `check_same_thread=True` — so a cached connection is a
`ProgrammingError`, and caching it needs `check_same_thread=False` plus a lock
in `memory/store.py` and `memory/vector_index.py`, neither of which this task
claims, in the path of the poller's known abandoned-thread bug. Risk bought
for 7 ms. Consulted before deciding, not after:
`docs/consults/2026-09-09-jarvis-board-task-hotpath-quick-wins` — Option A,
confidence high. Its stated caveat was that 7 ms might not hold on a populated
database; it was measured against the live 286-fact, 3.4 MB store, so it does.

The fail-closed requirement is met more strictly than asked, not less.
`SQLiteVecIndex.initialize` verifies the stored dimension and embedding model
on **every** open, which is per message. What the cached probe stops
re-proving is Ollama's liveness, and the first real embed still fails closed
with the same `EmbeddingError`.

**Step 4 moved the classifier, not recall, and that is forced.** Recall touches
the sqlite handles the caller opened, and the same memory object is used again
for `remember_turn` on the calling thread after the reply goes out — so recall
cannot leave this thread for the reason above. The classifier touches only the
router and its own confirmation store, which it opens and closes inside the
call, so it moves cleanly. Same overlap either way.

Two consequences, both deliberate:

- **A command message now pays for a recall it will not use.** It is local, it
  is free in wall-clock terms because the classifier is slower, and the
  alternative is every conversational message — the common case — paying
  1.2 s it does not have to. Two tests changed to say so:
  `test_an_action_never_routes_a_reply` (the expensive half, the routed
  completion, is what must never happen) and the WhatsApp latency-line test.
- **`classify` and `recall` now overlap, so the spans no longer sum to the
  time spent.** Nothing sums them: `executor/latency.py` measures `total` end
  to end and `tools/reply_latency.py` reports each stage's own percentiles.

**Deferred, and it is U20, not this task.** The "Done when" asks for
`tests/live/test_text_reply_latency.py` and a live `queue_wait_ms` under
~1,100. That probe needs the whole stack up (tunnel included, so Meta gets
re-pointed) and `JARVIS_LIVE_WHATSAPP_TO`, which is unset — and it sends a
real WhatsApp message to Ali's phone. The stack has been down since 4 Sep
(`tools/whatsapp-worker.out.log` last written then, and it holds **no**
`reply-latency` lines at all, so there is no live baseline to compare
against). `docs/state.md` already routes exactly this to **U20**: "the
end-to-end baseline through the real queue and a real Graph send". The
replay-based before/after above is the same method the 8 Sep baseline used and
is the strongest evidence available without the stack.

**Found while measuring, and it belongs to `router-client-timeouts`, not
here.** One `before` replay recorded `classify_ms=92308` — 92 seconds on a
`latency` call, on a tree that already has the new deadlines. Two reasons, and
both are real: httpx timeouts are per-operation, not a wall clock, so a
slow-dripping response never trips a 20 s read timeout; and the interaction
deadline is only checked *before* a rung is started, so it cannot bound a rung
already running. Followed up in the next commit; noted in that task's Log.

**Verification.**

```
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1
1535 passed, 10 deselected in 73.24s (0:01:13)
```

Before/after replays: 6 and 5 jobs through `tools/replay_job.py` in one
process each, summarised with `python -m tools.reply_latency --log ...`; the
tables above are that tool's output verbatim. The `before` tree was a git
worktree at `d7c19ef` sharing this repo's `.env` and `memory.db`.

New offline cases: 5 on the embedding client pool (one client across calls,
no sharing across transports, rebuild after close, unchanged failure causes),
4 on the probe cache (probed once, re-probed on a changed model or URL, index
identity still verified per open, a dead Ollama still failing closed and
caching nothing), 4 on the Groq client (built once, absence cached too, SDK
client reused, plus the autouse reset the cache now needs), 3 on the service
(the two halves genuinely in flight together — the test deadlocks if they are
serialized — a classifier failure arriving unchanged from the other thread,
and a command that recalls but never routes), and 1 on the launcher default.
