# JARVIS component state

Semi-fixed tier. What is true about each component right now, and what is
blocking it. Facts here survive a session but not a phase.

Do not record what happened here, only what is. Evidence and narrative go in
`docs/history/`. What is in flight right now goes in `docs/context.md`. If you
find yourself writing a date and a story, you are in the wrong file.

## Phase position

Phase 0 complete and verified. Phase 1 underway. Phase 2 scaffolding started
in parallel (blueprint-authorized). Its interpreter blocker is cleared and
`sort.py`'s full pipeline is now proved against a real `.flp`; it waits on the
user for one remaining thing, the dictated mixer-sorting convention — see open
blocker 4.

Phase order: 0 bus, 1 memory, 2 FL Studio, 3 voice, 4 VPS/laptop split,
5 vision fallback.

**Phase 3 is live-verified end to end** (30 Aug 2026): a real WhatsApp voice
note gets a spoken English reply. `voice-deps-and-tooling` landed (openWakeWord,
Kokoro, Pipecat, Silero VAD installed and exercised), the wake word is proved
working on the pretrained model, and `whisper-npu-build` is **done, not in
flight** — Whisper large-v3 runs on this laptop's XDNA NPU at 12.4x CPU encoder
speed. What is left in Phase 3 is sensory and Ali's: a false-positive rate
measured over hours of ordinary talking.

**Blueprint 2.4 desktop automation has landed** and is separate from the FL
Studio half of Phase 2: `executor/system_control/` (CLI/API, no UIA) and
`executor/app_automation/` (the real UIA targets, Zoom and WhatsApp Desktop).
Both are registered handlers with no producer — see the two rows above.

Phases 4 and 5 have not started.

## Built and working

| Component | State |
|---|---|
| FastAPI bus | HMAC-verified webhooks, bearer auth elsewhere, request-ID JSON logging, protected `/status` |
| Supabase queue | Migrations `0001` and `0002` applied live. RLS on, no public policies, RPCs service-role only |
| Queue client | Rejects publishable/anon credentials, requires `SUPABASE_SECRET_KEY`. PostgREST timeout pinned to 10s (`SUPABASE_QUEUE_TIMEOUT_SECONDS`) — supabase-py's 120s default let one hung connection stall the serial poll loop for two minutes |
| Executor | Atomic claim, checkpoint, complete. Retry, backoff, per-job timeout, dead-letter |
| Executor topology | **Three** independently supervised pollers, each restricted to its own kinds and no kind claimable by two: `whatsapp-worker` -> `whatsapp_webhook`, `background-worker` -> the long-running `distill_memory` chain, and `action-worker` -> `flp_sort`, `system_control`, `zoom_join_meeting`, `whatsapp_desktop_send_message`. Only `background-worker` seeds the chain and maintains the batch heartbeat; the other two pass `--no-heartbeat` because no handler of theirs drives Ollama. `action-worker` is an **optional** child like `whisper-server`: its death leaves desktop actions unclaimed and leaves text and voice replies untouched. The webhook remains enqueue-only. `--kind` takes `nargs="+"`; since `claim_next_job` filters on one kind, a multi-kind worker asks per kind and the poll loop rotates the starting kind each turn (`rotate_kinds`) so a busy kind cannot hold its siblings behind it. **All three have run live.** The first two reached steady-state polling on 31 Aug 2026 — `tools/whatsapp-worker.out.log` (1570 lines) and `tools/background-worker.out.log` (2990 lines), both ending in successful `claim_next_job` calls at 01:53. `action-worker` claimed and completed a real `system_control` job on 2 Sep 2026 (`wifi.list_interfaces`, job `f7b3e7ba`, row read back `status: done`) — the first time any of those four registered kinds had ever been claimed by a running poller. The earlier "not live: Quick Tunnel startup fails before worker launch" claim is withdrawn; it also contradicted this file's own "WhatsApp voice wiring" row, which records a live-verified voice reply on 30 Aug. Quick Tunnel startup is still fragile (see open blocker 3), but it is no longer blocking worker launch. |
| Memory | SQLite facts, sqlite-vec index, loopback Ollama. Two paths: conversation turns embed-and-store inline (fast), and the shared loop in `memory/distill.py` folds them into Mem0 facts as an offline batch |
| Migration runner | **Built 2 Sep 2026, not yet applied.** `db/migrate.py` applies `db/migrations/*.sql` in filename order, once each, recording every application in a `public.schema_migrations` ledger (version, name, file sha256, applied_at). Each migration and its ledger row commit in one transaction; a failure rolls back and stops. A file edited after it was applied is warned about and never re-run; a misnamed file is an error, not a silent skip. `--dry-run` prints the plan without opening a write transaction. Driver `psycopg[binary]==3.3.5`, named by Ali as a component decision (Q9). 26 offline tests. **Blocked on U12**: `SUPABASE_DB_PASSWORD` is an empty placeholder in `.env`, and the populated REST key can read and write rows but cannot run DDL, so `0003` (four justified indexes plus a hand-called retention function) is written and committed but unapplied. This is the machinery whose absence let 0002 sit unapplied for days and strand four inbound messages |
| Live queue contents, 2 Sep 2026 (evening) | 383 rows: 262 `done`, 103 `dead_letter`, 17 `failed`, 1 `queued`. **`whatsapp_webhook` is 175 rows, all `done`** — the reply path is healthy. **`distill_memory` is 162 rows: 63 `done`, 98 `dead_letter`, 1 `queued`** — the single queued row is the live chain's next link, not a stall. The 98 dead-letters are all between 29 Aug 13:06 and 30 Aug 20:52 UTC (84 `EmbeddingError`, 16 `LLMError`, 3 `exhausted after stale timeout`; the earlier 83/12 split was read off a smaller sample) and every one of them carries `{"reason": "seed"}` and nothing else, so **no work was lost and there is nothing to re-queue** — disposal only, see Q13. The seven orphaned `queue-durability-probe-` rows (five dead-lettered, two failed, all 25 Aug, empty payloads) are **reported and left in place** per Q9's carve-out, and account for five of the 103 |
| Distill chain | **Running, 2 Sep 2026 — closed.** Seven consecutive live jobs completed back-to-back that evening, seven turns distilled, zero failures: `dd853e77` (the row that had been ripe and unclaimed since 30 Aug), then `2d2d6c1c`, `adcb7574`, `b2ace2a9`, `cf8c4b91`, `9e3e1e57`, `3e9471b1`, each one enqueued by the one before it. Extraction runs 14-46s per turn against `llama3.1:8b`, comfortably inside the 90s default. **Two separate things had gone wrong, and neither was the chain's own logic.** First, Ollama stopped at 31 Aug 00:35 local (`tools/background-worker.out.log:202` is the last extraction, and the last mem0 line in the file); from then every distill row failed in ~3s on `open_mem0_memory`'s embedding dimension probe, dead-lettered after three attempts, and was re-seeded — a ~55s cycle that ran unattended for 78 minutes and produced 84 rows. Second, the `background-worker` process was stopped at 31 Aug 01:53 local and never restarted, which is the whole of "unclaimed since 30 Aug": no code was waiting on anything. `docs/audit/blueprint-drift.md` §4's first open question is settled — the chain was neither healthy nor dead-lettered out of existence, it had no worker |
| Batch distillation | Job kind `distill_memory` (`executor/handlers/distill.py`), self-re-enqueuing. One turn per job; a yield check for ready non-distill work runs **before** any extraction, so a ripe distill row costs one query rather than 55s when a reply is waiting. `run_after` is a duty-cycle throttle only, never a priority — the queue has no priority column and `claim_next_job` orders by `run_after asc, created_at asc`, so the ordering inversion is real and is absorbed by the yield check, not prevented. The successor write carries a veto evaluated **at the write site**: it refuses if this pass no longer owns its row (the poller re-queues what it claimed on timeout, and the abandoned thread would otherwise enqueue beside it) or if a sibling row is already open. Forks never merge, so each one would permanently double the duty cycle. `assert_timeouts_ordered` runs at executor startup and per row; it had no production caller at all until 27 Aug 2026. The executor seeds the chain at startup (not for `--once`), best-effort. Mechanism chosen adversarially: `docs/consults/2026-08-27-distill-scheduling-mechanism/`. `tools/distill_memory.py` remains as the manual path, still heartbeat-guarded. Seeding is idempotent **and rate-limited**: at most one seed per process per `SEED_RESEED_COOLDOWN_SECONDS` (900s, deliberately the idle cooldown, so a chain that died costs no more than a chain with nothing to do). A live chain returns early without spending the allowance, and a fresh process always seeds immediately, so a restart is never delayed. Idempotence alone said nothing about *rate*, which is why one Ollama outage became 84 rows |
| Executor failure diagnostics | A dead-lettered row's checkpoint records the exception type **and, where the exception publishes one, a `cause` slug** — `executor handler failed (EmbeddingError: unavailable)` rather than `executor handler failed (EmbeddingError)`. `memory/embeddings.py` publishes 15 named causes plus `http_<status>` (`EMBEDDING_FAILURE_CAUSES`), which separates a timeout from an unreachable Ollama from a model that was never pulled — three failures that had been one string across 84 live rows. `executor/poller.py::_describe_failure` admits a slug only if it matches `[a-z0-9_]{1,40}`; the checkpoint is written to the **hosted** jobs table, so that shape is a privacy boundary rather than tidiness, and no prompt, turn, URL or key can pass it. Anything else falls back to the bare type name. `LLMError` (`memory/mem0_wrapper.py`) does not publish a cause yet — the 16 live rows carrying it are all the one known invalid-JSON failure, `docs/blockers/mem0-extraction-not-schema-constrained.md` |
| Batch-tool liveness guards | Both Ollama-driving batch tools refuse while the executor's heartbeat is fresh: `tools/distill_memory.py` and now `tools/run_backfill.py`. Same `--force` override, same message from `executor/heartbeat.py`. `--dry-run` is never blocked |
| Conversation wiring | Recalled memory is injected as a **user**-role message inside a `<remembered_context>` fence, never as `system`. `remember_turn` stores inbound bodies verbatim, so until 27 Aug 2026 anything a sender said came back wearing the operator's role — a write into the instruction channel for anyone who could get a sentence remembered. Fence markers are stripped from the content so it cannot be closed from inside. `whatsapp_webhook` handler: recall, route, **send**, then store the turn. Reply-first is an authorized amendment to the blueprint's step order. Turns are stored verbatim via `memory/conversation.py` (~0.5s embed), **not** Mem0 extraction. Dedups by Meta's message id at two points, not one: `bus/webhook_dedup.py`'s `SeenWebhookMessageStore` stops a redelivered webhook from enqueueing a second job at all (added 2026-08-28, after a redelivered webhook was confirmed live on 26 Aug to create duplicate jobs), and `executor/handlers/whatsapp.py`'s `SeenMessageStore` separately stops a duplicate *reply* from sending. See `docs/history/whatsapp-reply-failures.md` |
| Outbound WhatsApp | `WhatsAppClient.send_text_message()` sends replies. `show_typing_indicator()` posts Meta's native combined read receipt and animated typing cue against the inbound message ID; the `whatsapp_webhook` handler issues it best-effort after durable reply-dedup and before opening or recalling memory, so local recall cannot delay the cue and Graph feedback failures never delay a reply. The callback must be re-pointed after Quick Tunnel recovery; no current callback read-back has been verified. A real text send through the live Graph API succeeded 26 August 2026 |
| Process tooling | `tools/consult.py`, `tools/repoint_webhook.py`, `tests/live/`, pre-commit hook. **`consult.py` sends the prompt on stdin, never in argv** — `claude.cmd` runs through `cmd.exe`, where a newline in an argv element terminates the command and the line is capped at 8191 chars, so every consult before 27 Aug 2026 delivered only its first line and got a confidently wrong answer back. No pre-fix verdict exists in `docs/consults/`, so nothing archived is suspect. Sub-model output is framed as untrusted data at every exit — stderr, `response.md`, and the `verdict` field when the reply is not JSON. A brief transport stall on 27 Aug 2026 (`docs/blockers/consult-cli-no-response.md`) recovered without a repo change; live-reconfirmed 30 Aug 2026, `docs/consults/2026-08-30-consult-selftest/` |
| Work-board claims | Local-only `tools/work_board_claim.py` atomically claims overlapping repository files and named resources. Its ignored `.work-board` state is not an external system; `git-commit` is a CORE-only resource. |
| `/status` | Reports `retry_health` (dead-letter and retried-job counts) from the live queue, additive to the existing payload |
| FL Studio sort (`executor/flp/sort.py`) | `flp_backup`, `load`/`save`, `apply_rules`, `diff_report`, `verify`, `build_flp_sort_handler` built and unit-tested against fakes (27 tests). Registered as job kind `flp_sort` in `executor/poller.py`'s `DEFAULT_HANDLERS`, but nothing enqueues it yet. Reordering mixer inserts raises `ReorderNotSupported` rather than silently no-op'ing: PyFLP has no insert-move API. Writes are confined to `flp_sort_root()` (env `JARVIS_FLP_SORT_ROOT`, default `test_projects/`) via `FlpSortPathOutsideRoot`; a diff report is written alongside the backup on any real change. **`sort.py`'s full pipeline has now been run against a real `.flp`**, not just unit-tested against fakes: `tests/flp/test_flp_real.py` (marker `realflp`, `.venv311`/3.11.5) exercises `build_flp_sort_handler` end to end against PyFLP's own downloaded fixture (`test_projects/FL 20.8.4.flp`) — a real mixer insert renamed, saved, and the rename confirmed by a from-scratch re-parse, plus the backup and diff report both confirmed on disk. Still open: a real user project with channel groups still hits PyFLP's own `IndexError` (open blocker 4, separate from this), and the dictated mixer-sorting convention is still the user's |
| Startup | Passes `--protocol http2` to cloudflared (`JARVIS_TUNNEL_PROTOCOL` overrides). QUIC is UDP 7844 and is unroutable on this network. `start-jarvis.bat` -> `tools/start_jarvis.py` brings up Ollama, bus, tunnel, Meta re-point, whisper-server and the three workers in order. A Quick Tunnel recovery is required: its initial API call selected an unusable IPv6 address. The launcher accepts only a hyphenated generated `*.trycloudflare.com` hostname, so it ignores the `api.trycloudflare.com` provisioning endpoint in a failure line. Ctrl+C stops the set together; a child dying reports which and shuts the rest down. |
| Single-instance guard | The launcher binds `127.0.0.1:8765` exclusively (`JARVIS_SINGLETON_PORT` overrides) as `main`'s first side effect, before the Ollama probe and before any child. A second copy refuses, names the holding PID via `netstat -ano`, exits nonzero, and mints no tunnel and re-points nothing. `SO_REUSEADDR` is deliberately never set. Fails open like `executor/heartbeat.py`: the OS releases the bind however the process dies, so no stale lock can wedge a future launch. The refusal never kills anything — it says Ctrl+C in the owning window. Loopback health probes could not catch a duplicate: an HTTP 200 on `127.0.0.1:8000` does not say whose process answered |
| Wake word | **Works on the pretrained model; no training run needed.** openwakeword 0.6.0 ships `hey_jarvis_v0.1.onnx` in its own package resources, so "Hey JARVIS" was testable before a single clip was recorded. Live check by Ali 29 Aug 2026 via `voice/listen_wakeword.py --meter`: **7 detections out of 7 attempts**, every score 0.873-0.993 against the 0.5 threshold, peak 0.999, idle floor 0.154 -- a wide margin with no room-noise triggering. This closes blueprint 3.2's wake-word half and makes `wakeword-train` (train a custom model on 30-50 recorded clips) **unnecessary as scoped**: it is not blocked, it is not needed. `voice/record_wakeword.py` stays as the recorder for the day the pretrained model is not good enough in a noisier room, which has not happened yet. Judging a false-positive rate over hours of ordinary talking is still Ali's and has not been done -- a 30-second sample cannot show it |
| TTS voice | **`am_puck`**, chosen by Ali by ear 29 Aug 2026 from Kokoro-82M's 54 installed packs. Recorded as `DEFAULT_TTS_VOICE` in `voice/config.py` (env `JARVIS_TTS_VOICE` overrides) so the WhatsApp voice reply and the live loop speak with one voice instead of each picking its own. Kokoro synthesises at 24 kHz; that is the model's rate, not a setting. Blueprint 3.2 puts this choice with the user and it is not an agent's to revisit |
| Outbound voice | **Live-verified 29 Aug 2026**: text -> Kokoro (`am_puck`) -> OGG/Opus -> Meta media upload -> playable WhatsApp voice note on Ali's phone, confirmed by ear. `voice/speak.py` synthesises and encodes; `WhatsAppClient.upload_media()` and `.send_voice_note()` do the two Graph API calls (media id first, message second; a failed upload never sends a message). `"voice": true` in the audio payload is what makes it render as a note rather than a file attachment. **No ffmpeg and no new dependency**: the pinned `soundfile==0.14.0` bundles libsndfile 1.2.2, whose OGG format exposes an OPUS subtype. Now wired into `executor/handlers/whatsapp.py` as the reply path for an inbound voice note — see "WhatsApp voice wiring" below. Evidence: `docs/history/voice-first-outbound-note.md` |
| Local speech-to-text | **Working on the NPU.** `amd/whisper.cpp` built with `-DWHISPER_VITISAI=ON`, Whisper large-v3, running on this laptop's XDNA NPU — independently re-verified by CORE, not just reported: `VITISAI = 1`, `whisper_init_state: Vitis AI model loaded`, `whisper_vitisai_encode: ... completed`, `XRT build version: 2.21.0`, correct transcript. A `WHISPER_USE_VITISAI` build **aborts** if the encoder graph will not load, so there is no silent CPU fallback to mistake for success. NPU encoder is **12.4x faster than CPU** (87.5s -> 7.1s per pass); whole-clip CPU-only 186.8s vs 32.4s. `voice/try_stt.py` records and transcribes in one command (`--language`, `--compare`). ~2.9x real time unoptimised; most of that is model reload per invocation. `whisper-server` (keeps the model resident, avoiding that reload) is now wired via `voice/whisper/server_client.py` — see "WhatsApp voice wiring" below. **Language default: forced Urdu (`ur`), decided 30 Aug 2026.** Ali confirmed he code-switches Urdu/English mid-sentence, so `DEFAULT_WHISPER_LANGUAGE` in `voice/config.py` was changed from `auto` to `ur` — `auto` was silently dropping the Urdu half of mixed clips, which is worse than `-l ur`'s degraded pure-English case. See `docs/history/voice-urdu-language-detection.md` for the tradeoff data; the retry-heuristic alternative sketched there was not built |
| Text encoding on this machine | **State an encoding explicitly whenever a transcript crosses a process or terminal boundary.** The locale codec here is cp1252 and cannot represent Urdu or Arabic script. This bit twice on 29 Aug 2026 in the same hour: `subprocess.run(text=True)` raised `UnicodeDecodeError` on a *successful* Urdu transcription and reported `(nothing recognised)`, and after that was fixed `print()` raised `UnicodeEncodeError` on the recovered text. Both runners now pass `encoding="utf-8", errors="replace"`; `voice/try_stt.py` reconfigures stdout/stderr. A bug of this shape looks exactly like model failure and cost a wrong conclusion about Urdu quality before it was found. **Now regression-pinned on both halves, 1 Sep 2026.** The write half is asserted against a real `cp1252` `TextIOWrapper` (with a control test proving an unreconfigured stream genuinely still raises); the read half against a real `sys.executable -c` child emitting UTF-8 Urdu bytes through `LocalWhisperBackend._run`, plus a direct assertion on the `encoding`/`errors` kwargs that every other test in `tests/voice/test_local_backend.py` bypassed via its `FakeRunner`. The pins were verified to bite, not just to pass: reverting the `reconfigure(...)` line reproduced the original `UnicodeEncodeError` in 3 tests |
| Bus logging | uvicorn's access log redacts the verify token, matching **both** `hub.verify_token` and `hub_verify_token`. A live Meta handshake carried both spellings and only the dotted one was caught, so the value reached `tools/bus.out.log` in plaintext. Logs are gitignored, so it was never committed. `hub[._]challenge` is deliberately left alone: a public nonce, not a credential |
| Cloud STT fallback | **Live-verified 2 Sep 2026** (Q8 = A). `voice/stt_fallback.py` — voice owns a small Groq client (`whisper-large-v3-turbo`, `JARVIS_GROQ_STT_MODEL` overrides because Groq retires IDs on weeks of notice); the provider router is untouched and stays chat-completions-only. Local NPU first, always, because it is the only path where a voice note never leaves the machine. The fallback fires when the local tier is *unavailable* — `/health` silent, or accepted-then-failed — and **never** because a transcript came back empty: an empty transcript is the correct result for a silent clip, and re-running it in the cloud would be double-transcription plus audio sent off the laptop for a message with no words in it. One clip, at most one backend. Both failing raises `SttFallbackError` naming each tier, which is louder than what it replaced — a dead whisper-server used to read as a blank transcript and a spoken message got silence back. Every transition logs at INFO, so "did it quietly send my voice to a third party" is answerable from a log. `JARVIS_STT_CLOUD_FALLBACK=0` restores the old silent behaviour. 24 offline tests. Live: with whisper-server genuinely down, a Kokoro-synthesised OGG/Opus clip decoded through the handler's own `to_transcribable_wav` came back from `api.groq.com` as `Testing the cloud speech fallback for JARVIS.` — word-perfect. **Open, and Ali's:** the same clip under the production `ur` language hint came back as garbage. That is `voice/config.py`'s documented trade (pure-English degrades under forced Urdu) on a clip that misrepresents how he speaks, so the default was left alone; U11 asks for one real code-switched note to settle it |
| WhatsApp voice wiring | **Live-verified, 30 Aug 2026.** An inbound voice note gets a spoken reply, not silence: `executor/handlers/whatsapp.py` downloads it (`WhatsAppClient.download_media()`, Meta's id-then-URL two-step), decodes OGG/Opus to 16 kHz mono PCM WAV (`voice/audio.py`, linear-interpolation resample if the source isn't already 16 kHz), transcribes it (`voice/whisper/server_client.py` against a warm `whisper-server`, language forced to `ur`), routes the transcript through the same recall/route pipeline a text message uses, and replies with a synthesised **English** voice note — Kokoro has no Urdu voice, so a voice reply's system prompt carries an explicit English-only instruction that a text reply's does not. A blank transcript is a silent no-op, same as an empty-body text message. `tools/start_jarvis.py` spawns `whisper-server.exe` as an **optional** managed process (`Supervisor.spawn(..., optional=True)`): its death or a missing NPU build degrades to text-only, it no longer takes bus/tunnel/workers down with it. Two bugs (wrong binary, a fatal-instead-of-optional child death) surfaced and were fixed on the first live pass: `docs/history/voice-whatsapp-live-verification.md`. Every seam is dependency-injected and covered with fakes for the offline suite |
| Router cooldown ledger | **Process-lifetime since 2 Sep 2026** (Q10c). `router.shared_router()` builds one `ProviderRouter` per process on first use, behind a lock, and `route()` uses it. Before that, `route()` built a router per call: every call re-read the manifest and started from a blank `health` map, so a provider that had just returned 429 with a `retry-after` was retried on the very next message — the cooldown died with the router that recorded it. Not persisted to disk, deliberately: a file would tell a fresh process to keep avoiding a provider that recovered hours ago. `current_shared_router()` asks whether one exists without building one; `reset_shared_router()` is the test seam. **Live-verified**: two real `route()` calls in one process, a 429 + `retry-after: 60` recorded between them via the same `_record_cooldown` the real 429 branch calls, and call 2 went to a genuinely different provider over real HTTP (`openrouter/free` → `mistral/codestral-2508`) with the cooled rung gone from the eligible order |
| Router denial surfacing (401/402/403) | **Built 2 Sep 2026**, closing blueprint §3.3's clause: "A rung that returns 401/402/403 enters cooldown and surfaces the denial. It does not silently fall through to paid work." Three things changed. **(1)** The cooldown carve-out was literally `provider.name == "mistral"`, so every other provider's auth denial cooled down nothing and every subsequent job re-probed a key that could not work; it now applies to all of them. **(2)** 401/403 no longer abort the cascade — they cool down and fall through like 429/402/5xx, which *gains* a live reply where one used to be lost. **(3)** The new part: a denial recorded during a request bars the cascade from crossing into a rung marked `paid_overflow` or `capped`; at that boundary it raises `ProviderDenied` instead, naming the denying rung. Raising **is** the surfacing — inside one cascade there is no other channel, because a request cannot both continue onto the paid rung and have surfaced the denial that preceded it. The bar is **per request, not sticky**: the cooldown ledger already handles repetition, and a persistent bar would let one bad key disable paid overflow indefinitely. `emergency=True` may still cross it, per §3.3's adjacent bullet that urgency promotes a paid rung "explicitly and per-job" — a caller's flag is the opposite of silent. `ProviderDenied` subclasses `NoEligibleProvider`, and nothing upstream catches that type specially (`executor/poller.py` catches bare `Exception`), so retry/dead-letter behaviour is unchanged. The reading was settled before the control flow changed: `docs/consults/2026-09-02-router-denial-surfacing-reading/` (verdict B, confidence high). The other half of "surfaces" was already there — `/status` carries `last_status` per provider. **Known behaviour change:** a 402 on a free rung no longer reaches `deepseek`. Narrow in practice, since `deepseek` is peak-gated and `claude_api` is `emergency_only`. **Not built:** a `denied: true` flag on `/status`, which would say it in words rather than leaving a reader to know that 402 is a denial; `last_status` meets the task's bar without it |
| Router model-resolvability gate | **Built 2 Sep 2026.** A rung that cannot name a model is no longer a routing candidate. It used to be: `_configured()`'s model guard fired only for providers declaring `model_env`, and `groq`/`cerebras`/`gemini` declare `default_model: "${...}"`, which `load_providers` resolves to `None` when the env var is unset. They entered the candidate list, sorted to the front by priority, and were skipped inside `route()` with a line appended to a `failures` list **rendered only if every provider failed** — so the ladder working was the exact condition that hid it. `_can_resolve_model()` now checks the same three sources `_model_for()` uses, in the same order, so the two cannot drift; `discover_chat_model` still counts as resolvable, which keeps `mistral` routable with no `default_model` at all. **Measured against the live manifest and `.env`: three rungs are excluded, not the two the task named** — `groq`, `cerebras` and `gemini`, each for an unset placeholder — leaving `openrouter, mistral, deepseek` as the whole ladder for both `latency` and `batch`. `unroutable_reasons()` returns `{provider: reason}` naming the env var that would fix each one, and a one-per-process warning says it out loud in the meantime. That method is **data, not a report**: §3.3's generated configured-but-not-routable list is `provider-status-generator`'s to format, and this task deliberately did not invent it. Cooldowns are excluded from it — a cooling rung is routable and merely resting |
| Router cost-class ordering | **Built 2 Sep 2026**, closing blueprint §3.3's first two bullets. `providers.yaml` gains `cost_class` per rung — `free` for groq, nvidia_nim, gemini, openrouter and mistral; **`trial` for cerebras**, whose open free tier became a one-time $5 credit in mid-2026; `paid` for deepseek, claude_max and claude_api, which keeps the blueprint's own ladder order among them via the existing priority integer. A missing or unrecognised value loads as **`paid`**, not `free`: a manifest typo should cost a rung its tier, not cost money, and it must never stop the router from starting. **The profile partition moved inside the cost class**, which was a real defect and not just a missing field — it used to run across the whole eligible list, so a paid rung declaring the task profile sorted above a free rung that did not, exactly what "never promotes a paid rung above a free one that is eligible" forbids. Within a class, ordering is measured p50 per **(provider, task_profile)**, then manifest priority. The buckets are a bounded deque of the last 20 **successful** calls (a 429 measures how fast a rung says no), and a median only counts once it has 5 samples — a p50 over one call is the last call, and an order that flips on one cold start is worse than none. A measured rung outranks an unmeasured one; an unmeasured one keeps its priority. **Process-lifetime, beside the cooldown ledger**, following Q10c's precedent: persisting it needs a decay window nobody has specified, and inventing one would be inventing policy. That decision was consulted rather than assumed, as the task required — `docs/consults/2026-09-02-router-p50-storage-scope/` (Class B, option A, confidence high). Against the live manifest the whole ladder is currently `openrouter, mistral, deepseek` for both `latency` and `batch` |
| Provider status generator | **Built 2 Sep 2026.** `tools/provider_status.py` emits §3.3's two lists — routable, and configured-but-not-routable **with a reason and a date** — into `docs/state.md` between generated markers, the same discipline `tools/context_status.py` uses for `docs/context.md`. Three inputs: the manifest, the environment, and the live health snapshot `router/health_report.py` publishes. **Environment key *names* only** — it decides whether a variable is set and never reads what it holds, because the output is committed; a test asserts no env value reaches the block while the variable names, which are the whole content of the reason, survive. The reason vocabulary is `ProviderRouter.unroutable_reasons()`, so the tool and the router cannot disagree about why a rung is unusable. Cooldowns are added here rather than there: a cooling rung is routable and merely resting, and "never verified" is its own state — a rung with a key, a model and no cooldown is indistinguishable from a working one until the first request, which is the distinction §3.3 asks for by name. **Not wired into the pre-commit hook**, unlike `context_status.py`: the state column reads a snapshot that changes between requests, so staging it would put an ephemeral cooldown countdown in every commit. `--check` verifies the block is present and machine-written rather than byte-comparing against a fresh render, which would fail constantly for the same reason. The old hand-written rung table is gone; a test asserts no markdown table survives in that section outside the markers |
| Provider health on `/status` | **Reported by the process that routes, since 2 Sep 2026** (Q10c). It used to read `app.state.provider_router.health` — the *bus's* router. The bus is enqueue-only and never calls `route()`, so every entry stayed at its constructed default for the life of the process: `/status` reported the absence of any attempt in a shape indistinguishable from "everything is fine". The executor now publishes its ledger through `router/health_report.py` and the bus reads it. Mirrors `executor/heartbeat.py`: small file, best-effort write, age-bounded read, fail-open on every error, 10-minute staleness window. The countdown is stored **relative** plus a wall-clock `reported_at`, because `cooldown_until` is a `monotonic()` reading and monotonic clocks share no origin across processes; the reader ages it. The file is rewritten only when something *material* changes — a ticking countdown is not a reason — or the poll loop would rewrite it several times a second forever. Only `whatsapp-worker` routes, and `_publish_provider_health` uses `current_shared_router`, so the other two workers neither build a router nor stamp defaults over its snapshot. Entry shape changed: `cooldown_until` → `cooldown_seconds_remaining`, plus `reported` / `reported_age_seconds`; `reported: false` is what nothing-has-reported looks like now |
| Ladder rungs that cannot resolve a model | **Open, found 2 Sep 2026.** `groq` (priority 1) and `cerebras` (priority 2) declare `default_model: "${GROQ_DEFAULT_MODEL}"` / `"${CEREBRAS_DEFAULT_MODEL}"`, and `load_providers` resolves both to `None` because neither key is in `.env` (U2). `_configured()` does not catch it — its model guard only covers providers that declare `model_env`, and these declare `default_model` — so both stay eligible, sort to the front of every request, and are skipped inside `route()` with `"no model configured"`, a message surfaced only if *every* provider fails. Six consecutive live `latency` calls went to `openrouter` with `groq` first in the eligible order each time. Two fixes are possible (widen the `_configured` guard, or report it as configured-but-not-routable) and choosing belongs with `provider-status-generator`; filed for `board-audit` as `router-unresolvable-model-rungs`. Resolves on its own the moment U2 lands |
| Command classifier (WhatsApp → action jobs) | **Live-verified 2 Sep 2026.** `executor/handlers/command_intent.py`, called from the WhatsApp handler before recall/routing — so a spoken command works too, a voice note being a transcript by then. The allowlist is a closed tuple (`system_control`, `zoom_join_meeting`) per Ali's Q1 answer; `flp_sort` and `whatsapp_desktop_send_message` are named as excluded-with-a-reason so asking gets an answer rather than silence. **The model proposes, constants dispose**: a `system_control` action must exist in the classifier's own action table (a test asserts that table equals `_build_action_registry(SystemControlDeps())`, so drift is caught in CI rather than by a dead-lettered job), and whether it needs confirmation is read from that table — the model's `destructive` flag may only raise the bar, never lower it. Reversible toggles (`wifi.set_enabled`, `power.set_plan`, `display.switch`) go straight through; `process.kill`, the `file.*` actions, both `scheduled_task` mutations and both printing actions ask first. Confidence floor 0.7; unparseable, low-confidence, empty and over-300-char input all fall back to conversation. Message text is fenced as data with markers stripped, same discipline as the recalled-context fence. Pending confirmations are sqlite beside the memory DB (`*.pending-actions.db`), one row per sender, 10-minute TTL, and any non-yes/no message retires them so a later "yes" cannot fire a forgotten action. Yes/no is a word list, not a model call. `JARVIS_WHATSAPP_COMMANDS=0` disables the producer without touching the allowlist. **Cost: a text message now makes two routed completions**, classification then reply. 104 offline tests. Live: three runs of "what wifi interfaces does this laptop have?" each classified, enqueued, and completed by `action-worker` (`a8b4785b`, `d581f3cd`, `a63ba76b`, all `status: done`); "kill the chrome process" asked first and enqueued nothing; an FLP request was refused. Zero `process.kill` and zero `flp_sort` jobs have ever been enqueued. The outcome reply landed 2 Sep 2026 — see the Action outcome replies row. Evidence: `docs/board/tasks/enqueue-classifier.md` |
| Command-classification reliability | **Gated on U2, not on the classifier.** Probing the live router on 2 Sep 2026 with the classifier prompt, the current top rung `openrouter/openrouter/free` returned the bare string `User Safety: safe` instead of JSON on two of four probes — an auto-router handing the request to a moderation model. The fallback is fail-safe (unparseable → conversation, no action), so the failure mode is "a command is silently treated as chat", never a wrong action. It resolves when Ali's five model IDs reach `.env`; `live-routing-probe` is the task that confirms it |
| Action outcome replies | **Built and live-verified 2 Sep 2026**, machine half end to end. An action job that carries a `notify` descriptor (`executor/notify.py`) produces a second message when it settles: `Done: list wifi interfaces. Wi-Fi (connected).` on success, `That didn't work — turn wifi off failed (UnknownSystemControlActionError).` on a dead-letter. **The outcome travels as a durable `whatsapp_outcome` job, not as a direct send** — a Graph send raising inside an action handler would make the poller retry the *action*, so a failed message about `process.kill` would kill it again; the queue already provides a separate retry lifecycle. `whatsapp-worker` owns the new kind because it already holds the Graph client and token, and `action-worker` needs neither. `system_control` stopped discarding its actions' return values, since half of them are questions and "done" is not an answer to a question. The poller notifies only on a **terminal** status (`failed` or `dead_letter`), never per retry, and reads a payload field rather than learning that WhatsApp exists. `enqueue_outcome` never raises, by design. Shape chosen adversarially against the two the task proposed: `docs/consults/2026-09-02-action-outcome-reply-shape/` (verdict C, confidence high; both of its named flip-conditions were checked and neither holds). Live proof: `30215ad3` (`wifi.list_interfaces`) -> outcome `3388acea` carrying `detail: Wi-Fi (connected)`; `c156e895` (unknown action, `max_attempts=1`) -> `dead_letter` -> outcome `227e7b90` carrying `status: failed`. Both outcome rows were settled with `fail()` rather than sent: their `reply_to` is the literal `PROOF-NOT-A-REAL-NUMBER`. **Still unproven: the inbound half** — nobody has sent a real WhatsApp command and seen two replies arrive, because that needs the tunnel up and Ali's thumb. U14 |
| Desktop system control | `executor/system_control/` — one job kind (`system_control`), five capability modules behind `handler.py`'s `build_system_control_handler()`: `power.py` (power plan via `powercfg`, wifi via `netsh`, Bluetooth radio via PowerShell `*-PnpDevice`, display via `DisplaySwitch.exe`), `scheduled_tasks.py` (`schtasks`), `printing.py` (`win32print`, and `win32api.ShellExecute`'s "print" verb for arbitrary files), `files.py` (confined move/rename/zip), `processes.py` (guarded kill by name/pid via `psutil`). **CLI/API only, no UIA.** Every subprocess call builds an argument list, never a formatted shell string. The one value that must reach a PowerShell `-Command` script — Bluetooth's `instance_id` — is passed through `JARVIS_PNP_INSTANCE_ID`/`JARVIS_PNP_ACTION` and read back with `$env:`, never interpolated into the command text, so it cannot be parsed as PowerShell syntax; a test feeds an injection attempt as the `instance_id` and asserts it never reaches the command text. 80 offline tests against fakes, plus one-off real-system proofs recorded in the lane report (power plan switched and restored, wifi enumerated). Registered in `executor/poller.py`'s `DEFAULT_HANDLERS` as `system_control`, claimed by `action-worker` since 2 Sep 2026 and **enqueued by the WhatsApp command classifier since the same day** — see the Command classifier row. It had no producer at all until then. The tree has exactly two producers and neither emits this kind: `bus/main.py:112` (`whatsapp_webhook`) and `executor/handlers/distill.py:469` (the self-re-enqueuing distill chain). `docs/tasks/laptop-system-control-report.md` |
| Desktop app automation (UIA) | `executor/app_automation/` — the real UIA targets from blueprint 2.4. `zoom.py` builds a `zoommtg://` URL and drives the native-dialog tail (passcode, audio device, popups); `whatsapp_desktop.py` does find-chat → compose → send → verify for sending as Ali's personal number. `handler.py`'s `build_app_automation_handler()` serves both job kinds from one instance. `__init__.py` holds the shared `Control` protocol, `WindowConnector`, and the `poll_until()`/`first_existing()` explicit-wait helpers — **every job-changing action is explicit-wait-then-read-back, never a blind `time.sleep`**. 45 tests; the 43 offline ones run entirely against `FakeControl`/`FakeConnectorRegistry` with zero real UIA calls, and 2 are `guiauto`-gated and self-skip without the env var. Live UIA inspection of both apps was done 29 Aug 2026: WhatsApp Desktop attaches by **window title** (`"WhatsApp"`, class `WinUIDesktopWin32WindowClass`) because it is a UWP host whose process name is `WhatsApp.Root` — attaching by process path would not work. Registered in `DEFAULT_HANDLERS` as `zoom_join_meeting` and `whatsapp_desktop_send_message`, both claimed by `action-worker` since 2 Sep 2026. `zoom_join_meeting` is on the WhatsApp command allowlist; `whatsapp_desktop_send_message` is deliberately off it (Q1) and still has no producer. Deps `pywinauto==0.6.9`, `comtypes==1.4.16`. `docs/tasks/pywinauto-zoom-whatsapp-report.md` |

Ollama 0.32.15 and `nomic-embed-text` are active on loopback. `memory.db` and
corpus inputs are gitignored. No personal corpus has been read or ingested.

## Provider rungs

**The two lists below are generated.** Blueprint §3.3: they are "generated
from the running config, not maintained by hand here". Never hand-edit
between the markers; run `.venv\Scripts\python.exe tools/provider_status.py --write`
instead, and `--check` asks whether the block is still machine-written.

They are **not** regenerated by the pre-commit hook, unlike
`docs/context.md`'s status block, and deliberately so: the state column reads
the live health snapshot, which changes between requests, so staging it would
put an ephemeral cooldown countdown in every commit. The generation date in
the block is how a reader judges its age.

<!-- BEGIN GENERATED: tools/provider_status.py. Do not edit by hand. -->

_Generated by `tools/provider_status.py` on 2026-09-02._

**Routable**

| Rung | Cost class | State |
|---|---|---|
| `openrouter` | free | never verified — no request has reached it in this reporting window |
| `mistral` | free | never verified — no request has reached it in this reporting window |
| `deepseek` | paid | never verified — no request has reached it in this reporting window |

**Configured but not routable**

| Rung | Cost class | Reason | As of |
|---|---|---|---|
| `groq` | free | no model: its default_model placeholder is unset in .env | 2026-09-02 |
| `cerebras` | trial | no model: its default_model placeholder is unset in .env | 2026-09-02 |
| `nvidia_nim` | free | no API key in NVIDIA_API_KEY | 2026-09-02 |
| `gemini` | free | no model: its default_model placeholder is unset in .env | 2026-09-02 |
| `claude_max` | paid | not a router target | 2026-09-02 |
| `claude_api` | paid | no endpoint configured | 2026-09-02 |

<!-- END GENERATED: tools/provider_status.py -->

Everything below is a decision or an account fact, not a status — those are
above, and generated.

DeepSeek proxy mode is off. OpenRouter proxy routing is disabled. DeepSeek's
`default_model` is a literal in `router/providers.yaml` (`deepseek-v4-flash`),
not env-resolved, which is why it is routable while the `${...}` rungs are
not. Ali reports credits added to the DeepSeek account (2026-08-29) — not
independently verified, no balance was read.

**Ali's model IDs (Q5, 1 Sep 2026).** His own values, differing from the
researched set; these are what must be pasted, and `.env` still did not
contain them on 2 Sep:

```
GROQ_DEFAULT_MODEL=openai/gpt-oss-120b
GEMINI_DEFAULT_MODEL=gemini-3.6-flash
CEREBRAS_DEFAULT_MODEL=
NVIDIA_DEFAULT_MODEL=
CLAUDE_API_DEFAULT_MODEL=claude-sonnet-5
```

Neither `openai/gpt-oss-120b` nor `gemini-3.6-flash` has been checked against
a provider model list or a live call. They are an instruction, and
`live-routing-probe` is what turns them into evidence. The blank Cerebras
value is deliberate (Q6): it makes that rung a skipped loop iteration rather
than a 402.

Two facts about specific rungs that no generator can derive, and that outlive
any snapshot:

- **NVIDIA NIM is geo-blocked from Pakistan** and is removed from the
  fact-extraction plan by the blueprint 1.3 amendment. It stays a candidate
  for the Phase 4 VPS, which is not in Pakistan. Independently of geography,
  `CLAUDE.md` forbids it from ever seeing private memory content.
- **Cerebras authenticates and returns `402 payment_required` on chat.** Its
  open free tier became a one-time $5 credit in mid-2026, which is why its
  cost class is `trial` rather than `free`.

## Open blockers

1. **No opted-in backfill.** No corpus has completed the fact-extraction and
   review acceptance loop.
2. **Meta app is unpublished.** Dashboard test events arrive, production data
   does not.
3. **The tunnel is ephemeral.** A Cloudflare Quick Tunnel URL dies whenever
   cloudflared or the laptop stops. `start-jarvis.bat` now mints a new one and
   re-points Meta automatically on each run, so this is no longer a manual
   step — but nothing receives messages while the laptop is off. A named
   tunnel, and moving the bus off the laptop, are both Phase 4.
4. **Phase 2 needs one thing from the user.** The interpreter half is done:
   `.venv311` on CPython **3.11.5** parses and saves real `.flp` files, proved
   against PyFLP's own `FL 20.8.4.flp` fixture with a rename that survived a
   save-and-re-parse round trip. What is still missing is blueprint 2.1, and
   it is the user's:
   - ~~Real guinea-pig `.flp` files.~~ **Done.** A real project is now in
     `test_projects/` (gitignored, copy only). Parsing it exposed a second,
     independent PyFLP failure — see the note below.
   - **The dictated mixer-sorting convention. Closed unanswered by Ali,
     1 Sep 2026.** He closed the question without dictating one, so
     `apply_rules()` still runs on a placeholder ruleset **that nobody
     approved**. The blocker is therefore no longer *waiting on him* — but the
     gap it names is unchanged, and guessing the convention is still out of
     scope. Do not build the FLP writing half against the placeholder.

   Evidence and the full history: `docs/blockers/pyflp-python-312.md`.
   **New, separate from the above:** parsing the real project raises
   `IndexError: list index out of range` inside PyFLP's own channel-grouping
   code (`channel.py:1586`) once it reaches a channel referencing a group
   number PyFLP's own `groups` list doesn't contain. The 3.11.5 interpreter
   fix is confirmed still working — this is a distinct gap in PyFLP itself, hit
   once, not yet investigated further. `docs/blockers/pyflp-channel-groups-indexerror.md`.
5. **One tool-result injection is unexplained.** Text claiming a plan-mode
   transition, and instructing a change of tooling, appeared inside a tool
   result during a session that was never in plan mode. An exhaustive search of
   the tree — untracked, gitignored, logs, consults, transcripts — did not find
   the string anywhere on this machine. The leading account is harness
   mode-transition text rather than anything repo-originated, and a 25 August
   session shows the same shape. Not reproduced, so **not closed**. Two related
   facts on disk: a `PostToolUse` hook that appends text to tool results ships
   in an installed plugin (inert, unset guard variables), and repo-root
   `.pytest_cache/` could not be read. `docs/blockers/tool-result-injection.md`.

## Meta account

- One WhatsApp app, **WA 1st**, in development. The test recipient allow-list
  already has the user's Pakistani number. Do not re-verify it.
- System user **whatsapp-bot** is Admin with full access to the app and test
  WABA. Do not create another system user or reassign assets.
- The system-user access token is permanent (`expires_at: 0`) with the right
  scopes, verified against the live test number. Its value is not recorded
  anywhere in the repo.
- If the token ever reads invalid, check it with `debug_token` through the
  Graph API before regenerating. Meta's dashboard has a separate rendering bug
  that has produced a false invalid reading before.
- Dashboard path, redesigned layout: **Use cases**, **Settings**,
  **Configurations**, the WhatsApp card's **Connect**, **Basic setup**,
  **Step 2. Production setup**, **Configure Webhooks**. Traditional layout:
  **WhatsApp**, **Configuration**.

## This machine and network

- **The ISP DNS resolver lags on fresh records.** It returned NXDOMAIN for a
  Quick Tunnel hostname that `1.1.1.1` and `8.8.8.8` both resolved correctly.
  Meta resolves independently, so a tunnel this laptop cannot look up is still
  reachable from the internet. `tools/start_jarvis.py` therefore gets a
  second opinion from public DNS before believing a tunnel is dead, and passes
  `--skip-probe` to `repoint_webhook.py` in that case. Do not "fix" a
  local-probe failure by assuming the tunnel is broken.
- **Supabase connectivity is intermittently flaky here**, occasionally failing
  TLS with `WinError 10054` for minutes at a time before recovering on its
  own. The queue client's 10s timeout keeps that from stalling the poll loop.
- **Ollama is a single serial resource.** Any batch job using it blocks live
  replies for its whole duration. That is what `executor/heartbeat.py` guards.
- **Local fact extraction is CPU-only** and roughly 250x slower than
  embedding (~55s vs ~0.5s), which is the reason for the two-path memory
  design above.
- The system `TEMP` directory is locked down; pytest needs
  `-p no:cacheprovider --basetemp=.pytest-basetemp` to run.
- **Two Python environments, and the second one is version-locked.** `.venv`
  is Python 3.12.10 and stays the default for everything. `.venv311` is
  CPython **3.11.5** and holds only `pyflp` and `pytest`
  (`requirements-flp.txt`). It must not be upgraded: CPython 3.11.6 backported
  the empty-enum guard that breaks PyFLP, so 3.11.6+ and 3.12+ are both
  unusable. 3.11.5 is unpatched (Aug 2023) and is only acceptable because that
  environment is offline, off `PATH`, two packages wide, and reads nothing but
  the user's own `.flp` copies. Always spell out `.venv311\Scripts\python.exe`;
  never `py`, never bare `python`.

## Local configuration

Confirmed present without reading values: Groq, Cerebras, Gemini, OpenRouter,
Mistral, DeepSeek direct, Supabase URL, Supabase publishable key, Supabase
secret key, Meta verify token, Meta phone number ID, Meta app ID, Meta app
secret, Meta system-user access token, bus bearer token.

No credential, token, password or database secret is committed or recorded in
any file in this repository. `.env` is gitignored and `.env.example` holds
empty placeholders.
