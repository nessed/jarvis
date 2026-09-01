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
| Batch distillation | Job kind `distill_memory` (`executor/handlers/distill.py`), self-re-enqueuing. One turn per job; a yield check for ready non-distill work runs **before** any extraction, so a ripe distill row costs one query rather than 55s when a reply is waiting. `run_after` is a duty-cycle throttle only, never a priority — the queue has no priority column and `claim_next_job` orders by `run_after asc, created_at asc`, so the ordering inversion is real and is absorbed by the yield check, not prevented. The successor write carries a veto evaluated **at the write site**: it refuses if this pass no longer owns its row (the poller re-queues what it claimed on timeout, and the abandoned thread would otherwise enqueue beside it) or if a sibling row is already open. Forks never merge, so each one would permanently double the duty cycle. `assert_timeouts_ordered` runs at executor startup and per row; it had no production caller at all until 27 Aug 2026. The executor seeds the chain at startup (not for `--once`), best-effort. Mechanism chosen adversarially: `docs/consults/2026-08-27-distill-scheduling-mechanism/`. `tools/distill_memory.py` remains as the manual path, still heartbeat-guarded |
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
| WhatsApp voice wiring | **Live-verified, 30 Aug 2026.** An inbound voice note gets a spoken reply, not silence: `executor/handlers/whatsapp.py` downloads it (`WhatsAppClient.download_media()`, Meta's id-then-URL two-step), decodes OGG/Opus to 16 kHz mono PCM WAV (`voice/audio.py`, linear-interpolation resample if the source isn't already 16 kHz), transcribes it (`voice/whisper/server_client.py` against a warm `whisper-server`, language forced to `ur`), routes the transcript through the same recall/route pipeline a text message uses, and replies with a synthesised **English** voice note — Kokoro has no Urdu voice, so a voice reply's system prompt carries an explicit English-only instruction that a text reply's does not. A blank transcript is a silent no-op, same as an empty-body text message. `tools/start_jarvis.py` spawns `whisper-server.exe` as an **optional** managed process (`Supervisor.spawn(..., optional=True)`): its death or a missing NPU build degrades to text-only, it no longer takes bus/tunnel/workers down with it. Two bugs (wrong binary, a fatal-instead-of-optional child death) surfaced and were fixed on the first live pass: `docs/history/voice-whatsapp-live-verification.md`. Every seam is dependency-injected and covered with fakes for the offline suite |
| Command classifier (WhatsApp → action jobs) | **Live-verified 2 Sep 2026.** `executor/handlers/command_intent.py`, called from the WhatsApp handler before recall/routing — so a spoken command works too, a voice note being a transcript by then. The allowlist is a closed tuple (`system_control`, `zoom_join_meeting`) per Ali's Q1 answer; `flp_sort` and `whatsapp_desktop_send_message` are named as excluded-with-a-reason so asking gets an answer rather than silence. **The model proposes, constants dispose**: a `system_control` action must exist in the classifier's own action table (a test asserts that table equals `_build_action_registry(SystemControlDeps())`, so drift is caught in CI rather than by a dead-lettered job), and whether it needs confirmation is read from that table — the model's `destructive` flag may only raise the bar, never lower it. Reversible toggles (`wifi.set_enabled`, `power.set_plan`, `display.switch`) go straight through; `process.kill`, the `file.*` actions, both `scheduled_task` mutations and both printing actions ask first. Confidence floor 0.7; unparseable, low-confidence, empty and over-300-char input all fall back to conversation. Message text is fenced as data with markers stripped, same discipline as the recalled-context fence. Pending confirmations are sqlite beside the memory DB (`*.pending-actions.db`), one row per sender, 10-minute TTL, and any non-yes/no message retires them so a later "yes" cannot fire a forgotten action. Yes/no is a word list, not a model call. `JARVIS_WHATSAPP_COMMANDS=0` disables the producer without touching the allowlist. **Cost: a text message now makes two routed completions**, classification then reply. 104 offline tests. Live: three runs of "what wifi interfaces does this laptop have?" each classified, enqueued, and completed by `action-worker` (`a8b4785b`, `d581f3cd`, `a63ba76b`, all `status: done`); "kill the chrome process" asked first and enqueued nothing; an FLP request was refused. Zero `process.kill` and zero `flp_sort` jobs have ever been enqueued. **Not yet built:** the completion-outcome reply — an action gets an immediate "queued as job X" and no second message when it finishes (task `action-outcome-reply`). Evidence: `docs/board/tasks/enqueue-classifier.md` |
| Command-classification reliability | **Gated on U2, not on the classifier.** Probing the live router on 2 Sep 2026 with the classifier prompt, the current top rung `openrouter/openrouter/free` returned the bare string `User Safety: safe` instead of JSON on two of four probes — an auto-router handing the request to a moderation model. The fallback is fail-safe (unparseable → conversation, no action), so the failure mode is "a command is silently treated as chat", never a wrong action. It resolves when Ali's five model IDs reach `.env`; `live-routing-probe` is the task that confirms it |
| Desktop system control | `executor/system_control/` — one job kind (`system_control`), five capability modules behind `handler.py`'s `build_system_control_handler()`: `power.py` (power plan via `powercfg`, wifi via `netsh`, Bluetooth radio via PowerShell `*-PnpDevice`, display via `DisplaySwitch.exe`), `scheduled_tasks.py` (`schtasks`), `printing.py` (`win32print`, and `win32api.ShellExecute`'s "print" verb for arbitrary files), `files.py` (confined move/rename/zip), `processes.py` (guarded kill by name/pid via `psutil`). **CLI/API only, no UIA.** Every subprocess call builds an argument list, never a formatted shell string. The one value that must reach a PowerShell `-Command` script — Bluetooth's `instance_id` — is passed through `JARVIS_PNP_INSTANCE_ID`/`JARVIS_PNP_ACTION` and read back with `$env:`, never interpolated into the command text, so it cannot be parsed as PowerShell syntax; a test feeds an injection attempt as the `instance_id` and asserts it never reaches the command text. 80 offline tests against fakes, plus one-off real-system proofs recorded in the lane report (power plan switched and restored, wifi enumerated). Registered in `executor/poller.py`'s `DEFAULT_HANDLERS` as `system_control`, claimed by `action-worker` since 2 Sep 2026 and **enqueued by the WhatsApp command classifier since the same day** — see the Command classifier row. It had no producer at all until then. The tree has exactly two producers and neither emits this kind: `bus/main.py:112` (`whatsapp_webhook`) and `executor/handlers/distill.py:469` (the self-re-enqueuing distill chain). `docs/tasks/laptop-system-control-report.md` |
| Desktop app automation (UIA) | `executor/app_automation/` — the real UIA targets from blueprint 2.4. `zoom.py` builds a `zoommtg://` URL and drives the native-dialog tail (passcode, audio device, popups); `whatsapp_desktop.py` does find-chat → compose → send → verify for sending as Ali's personal number. `handler.py`'s `build_app_automation_handler()` serves both job kinds from one instance. `__init__.py` holds the shared `Control` protocol, `WindowConnector`, and the `poll_until()`/`first_existing()` explicit-wait helpers — **every job-changing action is explicit-wait-then-read-back, never a blind `time.sleep`**. 45 tests; the 43 offline ones run entirely against `FakeControl`/`FakeConnectorRegistry` with zero real UIA calls, and 2 are `guiauto`-gated and self-skip without the env var. Live UIA inspection of both apps was done 29 Aug 2026: WhatsApp Desktop attaches by **window title** (`"WhatsApp"`, class `WinUIDesktopWin32WindowClass`) because it is a UWP host whose process name is `WhatsApp.Root` — attaching by process path would not work. Registered in `DEFAULT_HANDLERS` as `zoom_join_meeting` and `whatsapp_desktop_send_message`, both claimed by `action-worker` since 2 Sep 2026. `zoom_join_meeting` is on the WhatsApp command allowlist; `whatsapp_desktop_send_message` is deliberately off it (Q1) and still has no producer. Deps `pywinauto==0.6.9`, `comtypes==1.4.16`. `docs/tasks/pywinauto-zoom-whatsapp-report.md` |

Ollama 0.32.15 and `nomic-embed-text` are active on loopback. `memory.db` and
corpus inputs are gitignored. No personal corpus has been read or ingested.

## Provider rungs

| Rung | State |
|---|---|
| Groq | "Working" claim **unverified against the current `.env`** — see note below. Rate-limit header capture proven at some point, but not provably under today's config |
| Gemini | Same caveat as Groq below |
| DeepSeek direct | Working through `https://api.deepseek.com/v1`. No rate-limit headers, so cooldown parsing is unexercised. `default_model` is a literal in `router/providers.yaml` (`deepseek-v4-flash`), not env-resolved, so this rung is unaffected by the note below. Ali reports credits added to the account (2026-08-29) — not independently verified, no balance was checked or read |
| OpenRouter | Working through `openrouter/free`. No retry headers, cooldown correctly stays empty. Also a `providers.yaml` literal, unaffected |
| Cerebras | Authenticates, chat returns `402 payment_required`. Do not route work here |
| Mistral | Integrated, model discovery works, live chat returns `403`. Needs account or workspace resolution |
| NVIDIA NIM | Deferred. Geo-blocked from Pakistan, and removed from the fact-extraction plan by the blueprint 1.3 amendment |
| Claude Max | Priority 8. Used through `tools/consult.py`, not as a router target (`not_a_router_target: true`, `execution_path: claude -p`) |
| Claude API | **Priority 9, and missing from this table until 1 Sep 2026.** `router/providers.yaml` defines **nine** rungs, not eight. `emergency_only: true`, `capped: true`, keyed on `ANTHROPIC_API_KEY`, `default_model: ${CLAUDE_API_DEFAULT_MODEL}` — one of the five unset vars in the gap note below, so it resolves to `None` today |

DeepSeek proxy mode is off. OpenRouter proxy routing is disabled.

**`*_DEFAULT_MODEL` gap, found 2026-08-28 (`verify-configured-model-ids`):**
none of `GROQ_DEFAULT_MODEL`, `CEREBRAS_DEFAULT_MODEL`, `NVIDIA_DEFAULT_MODEL`,
`GEMINI_DEFAULT_MODEL`, or `CLAUDE_API_DEFAULT_MODEL` are present as keys in
the live `.env` (checked key names only, no values read or printed — the file
itself is access-restricted to this agent by design). `router/providers.yaml`
resolves each of those five providers' `default_model` via `${VAR}`
interpolation with no literal fallback, so each currently resolves to
`None`. `ProviderRouter._configured()` (`router/routing.py:246-257`) does not
check `default_model` for these providers (its `model_env` guard only covers
Mistral, the one provider using that field) — a rung passes as "configured"
purely on `key_env` presence. The failure is caught, not silent: `route()`
(`routing.py:216-218`) checks `if not provider_model` and records
`"{provider}: no model configured"` before falling through to the next
candidate — so this does not crash a request, but it does mean any of these
five rungs that reach that point today cannot serve one, contradicting a
"Working" claim made on their behalf. `tests/live/` currently has exactly one
test (`test_memory_roundtrip.py`) and it does not exercise routing at all, so
there is no live probe on disk proving current Groq/Gemini behavior either
way. This is the exact gap `docs/plan.md`'s `router-model-env-validation` job
already names; this note is the live-environment evidence for it, not a fix —
`router/routing.py` is claimed by another lane as of this writing.
Current model IDs, for whoever sets these (verified 2026-08-28, not written
to `.env` by this agent): Groq's `llama-3.1-8b-instant` is deprecated;
`openai/gpt-oss-20b` is Groq's current free-tier-friendly general model
([console.groq.com/docs/models](https://console.groq.com/docs/models)).
Gemini's `gemini-2.0-flash` shut down 1 June 2026; current free-tier Flash
models include `gemini-2.5-flash` and `gemini-2.5-flash-lite`
([ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models)).

**Superseded by Ali's own values, 1 Sep 2026 (Q5).** He chose different IDs
from the researched set above and they are what must be pasted — do not
paste the 28 Aug values:

```
GROQ_DEFAULT_MODEL=openai/gpt-oss-120b
GEMINI_DEFAULT_MODEL=gemini-3.6-flash
CEREBRAS_DEFAULT_MODEL=
NVIDIA_DEFAULT_MODEL=
CLAUDE_API_DEFAULT_MODEL=claude-sonnet-5
```

The gap above is still live: a key-name check on 1 Sep found none of the
five keys in `.env`. Neither `openai/gpt-oss-120b` nor `gemini-3.6-flash`
has been verified against a provider model list or a live call — they are
Ali's instruction, and `live-routing-probe` is what turns them into
evidence. The blank Cerebras value is deliberate (Q6): it makes that rung a
skipped loop iteration rather than a 402.

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
