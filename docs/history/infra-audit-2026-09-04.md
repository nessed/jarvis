# Where the time goes: a layer-by-layer audit of the laptop stack (4 September 2026)

Frozen record. Ali's complaint that morning, verbatim in spirit: startup is
slow, Whisper lags the laptop, replies are slow. This is what each layer
actually cost when measured, the same day, on the machine it runs on. Every
number below came from a command run that evening; nothing is estimated.

Machine: AMD Ryzen AI 7 350 (8 cores, XDNA NPU), Radeon 860M iGPU, 32 GB
RAM. With the JARVIS stack **down**, 8.3 GB was free — Chrome held about
8 GB across tabs and Windows had 3.5 GB in memory compression, so the stack
starts on a machine already under memory pressure.

## The reply path, and what each hop cost

A text message travels phone -> Meta -> Cloudflare Quick Tunnel -> bus ->
Supabase insert -> worker poll -> claim -> typing cue -> classify (LLM) ->
recall (embed) -> reply (LLM) -> send -> remember (2 embeds) -> complete.

| Hop | Measured | Cause |
|---|---|---|
| Supabase, raw HTTPS on one kept-alive connection | GET jobs 0.31-0.36 s; `claim_next_job` RPC 0.35-0.42 s | Network floor from Pakistan to the SIN edge |
| Supabase through `db.jobs.claim_next()` | **1.72-3.43 s per call** | `_repository_or_default()` built a new supabase-py client, and so a new TLS session, on every call. The worker log shows it too: consecutive `claim_next_job` lines 1.3-1.8 s apart |
| Queue calls on one reply's critical path | ~5 (poll, claim, set_timeout, checkpoint, complete) | ~6 s of connection setup per reply |
| Meta Graph API TLS handshake | 1.0 s | `WhatsAppClient` opened a fresh `httpx.Client` per call, and the handler built a fresh `WhatsAppClient` per call; a text reply does two (typing cue, send), a voice reply four |
| Provider TLS handshake | openrouter 0.45 s, groq 0.92 s, mistral 0.57 s, deepseek 0.38 s | `ProviderRouter.route()` built a new `AsyncOpenAI` per attempt, and `asyncio.run()` per call closed the loop the pool was bound to |
| Routed completions per text reply | 2 (classify, then reply) | By design since `enqueue-classifier` (2 Sep); each paid a handshake |
| Ollama `nomic-embed-text` embed | cold 0.91 s, warm **0.04 s** | Fine. Recall is not the problem |
| Poll interval | 3 s sleep between idle polls, two kinds per cycle | Adds 0-3 s of pickup delay; not the bottleneck once claims are 0.4 s |
| Jobs table | 460 rows | Small. Migration `0003`'s indexes (blocked on U12) are not what is slow |

Sum, before any fix: roughly 12-18 s of a text reply was connection setup
and polling, before a model saw a token.

## The voice path

| Step | Measured | Notes |
|---|---|---|
| `import kokoro` | **18.5 s** | torch |
| `KPipeline()` build | **5.3 s** | Was rebuilt on **every** `synthesize()` call |
| Kokoro render, warm pipeline | 2.7-3.1 s for 7.6 s of speech | CPU 76 % avg, 100 % peak |
| Kokoro through `text_to_voice_note()` as shipped | first call 28-103 s in a fresh process, then 7.4-7.6 s | The 103 s reading was under memory pressure; the 28 s one was not |
| OGG/Opus -> 16 kHz WAV decode | 0.03 s | |
| Whisper large-v3, NPU encoder + CPU decoder, `whisper-server` resident | **11.2-17.6 s** for a 7.6 s clip (`en`); **13.8 s** (`ur`) | CPU 53-69 % avg, 73-89 % peak across all 8 cores for the whole duration. This is the "lags the laptop" |
| Whisper transcript quality | `en`: word-perfect. `ur`: transliterated English into Urdu script | Expected under the forced-`ur` trade recorded in `voice/config.py` |

So a voice note's reply, before any fix and after the worker was warm, was
about 14 s STT + two LLM calls + 7.5 s TTS + four Graph handshakes + the
queue overhead above: 40-50 s on a good run, and the first one after a
restart added the 24 s Kokoro load on top.

The NPU claim in `docs/state.md` — "12.4x faster than CPU" — is true of the
**encoder** only. Whisper large-v3's decoder (32 layers, 1280 wide) runs on
the CPU and dominates: `whisper_backend_init_gpu: no GPU found` in
`tools/whisper-server.out.log`. Two ways out, both Ali's call (Q15): Groq's
`whisper-large-v3-turbo` as primary (already live-verified as the fallback,
word-perfect on English; audio leaves the laptop), or local large-v3-turbo
(same encoder, so the compiled `.rai` NPU graph should carry over; 4
decoder layers instead of 32).

## Startup

From `tools/cloudflared.out.log` and `tools/whisper-server.out.log` for the
19:56 launch that evening:

| Step | Time |
|---|---|
| Ollama probe | Refused: Ollama was not running and the launcher exits with "start it and run this again" |
| Bus up | seconds |
| Quick Tunnel minted | 9 s (14:56:01Z -> 14:56:10Z) |
| Tunnel reachability probe + Meta re-point | **57 s** (tunnel up 14:56:10Z, whisper-server spawned 14:57:08Z) |
| whisper-server load (3.1 GB model + XRT init) | tens of seconds, waited on serially |
| Three workers, each importing `executor.poller` | 4.9 s each (mem0 + qdrant_client 2.9 s, pywinauto 0.55 s, PyFLP 0.36 s) |

Everything ran in series, so the total was the sum. The tunnel/re-point
leg, the Whisper load and the worker imports are independent.

## Orphans

With the stack down, two `whisper-server.exe` processes from launches at
18:17 and 19:50 were still alive at 20:30 — 55 MB and 700 MB working set,
**both** listening on 127.0.0.1:8081. `Supervisor.shutdown()` runs only
when `main` reaches its `finally`; closing the console window that
`start-jarvis.bat` opens kills python outright and leaves every child
spawned with `CREATE_NEW_PROCESS_GROUP` alive. Each launch since had been
stacking a fresh 3 GB Whisper on top of the last one. Neither was killed by
this audit; killing is Ali's, and the launcher fix (a Windows Job Object
with kill-on-close) stops it recurring.

## What was changed the same day, and what was not

Changed, all measured before and after in their task logs
(`docs/board/tasks/client-connection-reuse.md`,
`docs/board/tasks/tts-pipeline-cache.md`,
`docs/board/tasks/launcher-fast-start.md`):

- One Supabase client per process; one `httpx.Client` per `WhatsAppClient`
  and one `WhatsAppClient` per handler; one `AsyncOpenAI` per provider on a
  persistent event loop.
- One Kokoro pipeline per process, warmed on a daemon thread when the
  WhatsApp worker starts.
- Launcher: job object so children die with it, Ollama started if silent,
  tunnel/Whisper/workers brought up in parallel, elapsed time printed.

Not changed, because each is a decision and not a lookup:

- Which Whisper runs, and where (Q15).
- The two-completion text reply. Merging classification into the reply
  call would halve provider latency, but `enqueue-classifier`'s "model
  proposes, constants dispose" shape was Ali's Q1 answer.
- Moving the bus off the laptop. Phase 4 is written and validated
  (`infra/`, `docs/tasks/phase4-runbook.md`); it waits on the Oracle
  account (U7), which needs his identity and card. Note that Phase 4 alone
  does not shorten a reply: recall and memory are laptop-local by
  non-negotiable, so a text reply still round-trips through the laptop
  executor. What it buys is a webhook that is up when the laptop is not.
- Claude Max and ChatGPT Plus. The blueprint already settles both: Max is
  `claude -p` only (it is `tools/consult.py`), never a router target; Plus
  has no API. Nothing on the reply path can use either.
