# Building a Real JARVIS on One Windows 11 Laptop — Blueprint v2 (verified 23 Aug 2026)

Every section is tagged: **[UNCHANGED]** = original report holds, build on it as written. **[UPDATED]** = facts changed, corrected here. **[NEW]** = wasn't in the original.

---

## TL;DR **[UPDATED]**

- ~80% of JARVIS is buildable today for near-zero cash. Architecture: Oracle Cloud free VPS hosts the webhook/command bus, job queue and web UI; the laptop runs a local executor that drives apps. Highest-leverage move is still attacking file formats and Windows accessibility APIs instead of pixels — PyFLP for FL Studio remains the headline win.
- Claude Max is the backbone and stays scriptable: `claude -p` headless runs still draw from your subscription (Agent SDK billing split remains **paused** as of Aug 2026, verified against Anthropic's Help Center). **Change:** Cowork scheduled tasks now run in the cloud too, and Cloud Routines can be fired by an HTTP call — your VPS can trigger Anthropic-hosted jobs on demand.
- **New in the stack: DeepSeek V4-Flash as the paid overflow layer.** $0.22 in / $0.66 out per 1M off-peak (Aug 16 repricing), 1M context, thinking mode built in, cache-hit input at $0.007/M. At a $2–5/mo budget it's effectively unlimited for a single-user assistant. It slots BELOW Claude Max and ABOVE the free tiers — it catches what free tiers drop, it does not replace them.
- Free routing layer grows: Groq + Cerebras + Gemini AI Studio + OpenRouter, **plus NVIDIA NIM (~40 RPM, 100+ models incl. DeepSeek V4, free)** and Mistral's free tier as spare lanes.
- Build order unchanged in shape: (0) harden bus, (1) memory, (2) PyFLP + pywinauto, (3) voice, (4) always-on split, (5) vision fallback. Details of Phase 4 updated for cloud Cowork tasks and Cloud Routine API triggers.

*(USD at ~PKR 278/USD, 21 Aug 2026 interbank. PKR figures move with the rate.)*

---

## Your three subscriptions: what's scriptable vs hand-only

### Claude Max **[UPDATED — mostly holds, three changes]**

- **Headless is fine, still subscription-backed.** `claude -p "task"` with `--output-format json`, `--allowedTools` / `--permission-mode` for unattended runs. **The June 15 Agent SDK billing split is still paused** — the Help Center article ("Use the Claude Agent SDK with your Claude plan") still opens with the June 15 pause note as of Aug 2026: Agent SDK, `claude -p`, and third-party app usage draw from subscription limits, no separate credit exists, and Anthropic will give notice before anything changes. Re-verify monthly; if it un-pauses, headless automation moves to DeepSeek/free tiers (see routing below).
- **Auth rule unchanged:** official Claude Code CLI over SSH on the VPS with your Max OAuth = fine. Your OAuth token inside the Agent SDK or any custom harness = ToS violation. On the VPS: run the `claude` binary, or use an `ANTHROPIC_API_KEY` for custom harnesses.
- **Limits — one thing to plan around:** the May 6 2026 permanent doubling of 5-hour limits holds, and peak-hour throttling stayed removed. But the **+50% weekly-limit promo (running since May 13) has an expiry, currently extended through ~Aug 31 2026.** When it lapses, weekly walls arrive roughly a third sooner than you're used to. Budget your scheduled jobs assuming the smaller weekly cap. Also note: since July 20, Fable 5 draws from the same weekly allowance on Max plans, capped at 50% of it, and weighs roughly 2× an Opus session — for automation, pin cheaper models (Sonnet) in headless runs.
- **Cowork — the report's naming table is stale.** Cowork moved to cloud sessions (beta, all paid plans, web/desktop/mobile/Chrome side panel). **Cowork scheduled tasks now run on Anthropic's servers** — laptop asleep, app closed, doesn't matter. The old "Scheduled Tasks are local-only" distinction is gone. Local files are reachable only while the desktop app is open on that machine, so scheduled jobs that need your files still route through the VPS queue → laptop executor path.
- **[NEW] Cloud Routines have API triggers.** A Cloud Routine can be fired by an HTTP call to its endpoint, not just a schedule. This is a real primitive for the build: your FastAPI bus on the VPS can trigger an Anthropic-hosted Claude job on demand for anything that doesn't need local files. Cowork/Routine sessions burn noticeably more of your usage allocation than chat, so reserve them for jobs that earn it.

### ChatGPT Plus / Gemini Pro (consumer) **[UNCHANGED]**
Hand-use only, no API keys from consumer subs. For scripting Gemini, use Google AI Studio's separate free API tier (prompts may be used for training).

---

## The free/near-free API routing layer **[UPDATED + NEW ENTRIES]**

### Groq **[UPDATED — limits are per-model now, TPD is the real ceiling]**
The report's "30 RPM / 6,000 TPM / 14,400 req/day across all models" is stale. Current published limits are **per model**, with tokens-per-day caps the report never mentioned:
- llama-3.1-8b-instant: still the permissive one, ~14,400 RPD — this is where the old headline number came from.
- gpt-oss-120b / 20b: ~30 RPM, **1,000 RPD, 8K TPM, 200K TPD** (Aug 2026 snapshot). At 2K tokens per call that's ~100 real calls/day, not 1,000.
- Limits remain org-level; extra keys don't help. Cached tokens don't count against limits — keep system prompts stable.
- **Read `x-ratelimit-*` response headers at runtime instead of hardcoding numbers.** They rot in weeks.
- **Whisper v3 Turbo STT still free** (~2,000 audio req/day) — still your Urdu/English transcription path. Unchanged.
- Best at: low-latency chat, STT, small-model tool loops on the 8B lane.

### Cerebras **[UPDATED — minor corrections]**
1M tokens/day free and the 8K context cap both confirmed. Corrections: recent doc snapshots put free tier at **5 RPM / 30K TPM** (report said ~15 RPM), and the catalogue is confirmed narrowed to gpt-oss-120b and GLM-4.7. Don't hardcode a model name. Best at: batch/overnight volume where 8K context fits.

### Google AI Studio (Gemini) **[UNCHANGED]**
Flash/Flash-Lite free tier for long-context + vision. Free prompts may train Google's models — don't send private memory content here.

### OpenRouter **[UPDATED — one addition, one caveat]**
50 req/day free, one-time $10 credit purchase raises it to 1,000/day permanently, 20 RPM fixed either way. Confirmed. Two changes:
- **[NEW] `openrouter/free` auto-router** (Feb 2026): set the model to `openrouter/free` and it picks a live free model matching your request's needs (tool calling, vision, structured output). Your code survives roster rotation without babysitting model IDs.
- Caveat: mid-2026 snapshots show **zero free DeepSeek or Gemini variants** on the roster — old guides referencing `deepseek-r1:free` etc. are dead. The roster rotates; verify before depending on any specific `:free` ID.

### NVIDIA NIM — build.nvidia.com **[NEW — the report missed this entirely]**
Free NVIDIA Developer Program account, no card, OpenAI-compatible endpoint (`integrate.api.nvidia.com/v1`), **100+ hosted open models at ~40 RPM** — including **DeepSeek V4**, Llama, Qwen, GLM, Nemotron. New open-weight drops land here fast (GLM appeared ~2 weeks after release). This means DeepSeek-class inference at $0 before you ever touch the paid DeepSeek key. Free endpoints get throttled/rotated, so treat it as a routing lane with fallback, not a guarantee. 200 RPM raise can be requested.

### Mistral La Plateforme free tier **[NEW — spare lane]**
Free experiment tier, roughly 1 req/sec with TPM in the tens of thousands per tested snapshots (~50K TPM measured May 2026). Worth grabbing a key as another lane in the router. Check current license terms; some trial keys restrict commercial use (irrelevant for a personal build).

### DeepSeek (paid) **[NEW — the overflow layer, and it changed pricing 5 days after the report's data]**

**Current state (post-Aug 16 2026 repricing):**
- Lineup is **deepseek-v4-flash** and **deepseek-v4-pro**. The old `deepseek-chat` / `deepseek-reasoner` names were retired July 24 2026 — they now return errors. Flash has a reasoning-effort knob (low/high/max), so it covers both the old chat and R1-reasoner roles in one model. 1M context, up to 384K output.
- **Flat pricing is gone.** Peak/off-peak billing since Aug 16, 16:00 UTC:
  - **V4-Flash:** $0.22 in / $0.66 out per 1M **off-peak**; $0.44 / $1.32 at peak. Cache-hit input: $0.007/M off-peak.
  - **V4-Pro:** $0.66 / $1.98 off-peak; $1.32 / $3.96 peak. Exactly 3× Flash, and independent scoring puts Pro barely a point above Flash — **default to Flash, basically never Pro.**
  - **Peak windows: 01:00–04:00 and 06:00–10:00 UTC = 6:00–9:00am and 11:00am–3:00pm PKT.** Your evenings, nights, and early mornings are all off-peak. Schedule batch jobs accordingly; even interactive evening use is off-peak for you.
- New accounts have gotten a ~5M token free grant (verify at signup, promos rotate).

**Where it slots — complement, not replacement:**
1. Free tiers stay first. Free beats cheap, and NIM even serves DeepSeek V4 itself at $0.
2. **DeepSeek V4-Flash is the paid overflow valve:** catches jobs when free tiers 429, and handles anything needing 1M context + real reasoning that free tiers can't (Cerebras is 8K context, Groq TPM is tight). With a stable cached system prompt you pay almost pure output cost.
3. **It replaces most of the report's "keep an ANTHROPIC_API_KEY as overflow" advice.** Claude API output is $15+/M vs Flash's $0.66 off-peak — a 20–70× gap. Keep the Claude key with a tiny cap only for jobs that genuinely need Claude-quality agentic execution when Max limits are hit. Everything else that overflows goes to Flash.
4. **Does it change the "reserve Claude Max for smart work" strategy? No — it adds a middle rung.** The ladder is now: free tiers (cheap/fast/dumb-to-mid) → DeepSeek Flash (mid-to-strong, near-free) → Claude Max subscription (strongest agentic work, flat rate) → Claude API key (emergency only).

**Budget math at $2–5/mo:** $3 ≈ 4.5M output tokens off-peak on Flash (input nearly free with caching). A single-user assistant doing a few hundred routed calls/day lands well under $2/mo. Your PKR 3,000 ceiling is nowhere in sight.

**Caveat:** DeepSeek has signaled further price changes without publishing rates or dates. Also international payment from Pakistan for the DeepSeek platform may need a workaround (their platform takes cards; verify yours works before architecting around it — if it doesn't, DeepSeek via OpenRouter paid credit is the fallback route, small markup).

### The routing pattern **[UPDATED]**
Fallback chain on the VPS, simple priority list + 429 backoff (a LiteLLM proxy or ~100 lines of your own code):
1. **Groq** — latency-sensitive chat, STT, small tool loops
2. **Cerebras** — batch volume under 8K context
3. **NVIDIA NIM** — DeepSeek-class free inference, wide model coverage
4. **Gemini Flash (AI Studio)** — long context + vision, free
5. **OpenRouter `openrouter/free`** — rotating spare capacity
6. **DeepSeek V4-Flash (paid, prefer off-peak)** — overflow + long-context reasoning
7. **Claude Max (subscription)** — the smart agentic executor, invoked as `claude -p` jobs, not as a router target
8. **Claude API key** — capped, emergencies only

Read rate-limit headers at runtime; never hardcode a provider's published numbers. Spread load across providers, not extra keys (org-level limits everywhere).

---

## 1. Controlling the computer **[UNCHANGED]**

Everything in this section holds. File formats > accessibility APIs > pixels, in that order:
- **PyFLP** for FL Studio `.flp` edits with FL closed (unofficial/reverse-engineered — back up, reopen to verify). Still the single most impressive early win.
- **pywinauto** (`backend="uia"`) for apps with an accessibility surface; FlaUI if you want .NET robustness; AutoHotkey v2 for hotkeys.
- FL Studio's built-in Python MIDI Controller Scripting API for live control while FL is open.
- **UI-TARS** as last-resort vision agent, second Windows user session so it doesn't fight your desktop. Still demo-grade for complex flows. Claude computer use for occasional gnarly tasks only (screenshot costs burn Max limits).
- Windows virtual desktops still don't isolate input; second user session / RDP-to-self / VM are the real options.

One addition worth noting: vision fallback calls can route through **Gemini Flash free tier or NIM-hosted vision models** before paying anyone.

---

## 2. Voice **[UNCHANGED]**

All holds: amd/whisper.cpp fork for NPU-offloaded STT (Urdu/English stays on Whisper large-v3 — Parakeet is English/European only), openWakeWord for "Hey JARVIS," Kokoro-82M for TTS, Piper if latency ever matters more than quality, XTTS/Chatterbox/F5 for cloning, Pipecat + Silero VAD for the interruptible loop, Groq Whisper as the cloud STT fallback. WhatsApp voice note → transcript → bus → executor → Kokoro spoken reply, as written.

---

## 3. Always-on presence **[UPDATED]**

- **VPS/laptop split unchanged:** VPS holds webhook receiver, FastAPI bus, job queue, scheduler, web UI, light LLM calls. Laptop is the executor for files, FL/PyFLP, NPU inference, UIA, local memory.
- **Oracle Cloud Always Free — confirmed, still the winner.** 2 OCPU / 12GB Ampere A1 (1,500 OCPU-hrs + 9,000 GB-hrs/mo), 200GB block storage, 10TB egress. The Aug 18 2026 enforcement date has passed — provision new instances at 2/12 from day one and you're clean. 2/12 is ample for this stack. ARM capacity shortages in some regions still apply; retry or pick a quieter region. Cost: PKR 0.
- **Hetzner CX22 (~PKR 1,240/mo) stays the paid fallback.** Fly/Railway/Cloudflare notes unchanged.
- **Modern Standby / no-WoL constraint unchanged:** `powercfg` stay-awake-on-AC profile when jobs are expected, durable queue so sleeping just delays execution.
- **[UPDATED] The laptop-off story got better:**
  - Cowork **scheduled tasks now run in Anthropic's cloud** on all paid plans — anything not needing local files can be a scheduled Cowork task with zero infra.
  - **Cloud Routines can be triggered via HTTP** — so the VPS bus can fire an Anthropic-hosted Claude job on demand ("summarize my starred emails now") while the laptop sleeps. This shrinks the set of jobs that actually need the laptop to: local files, FL Studio, NPU inference, and UIA. Everything else runs on Oracle or Anthropic infra.
- **Job queue + checkpointing unchanged:** Supabase table or Redis on the VPS, laptop polls, idempotent jobs, checkpointed state.

---

## 4. Memory **[UPDATED — one correction, verdict holds]**

- **Mem0 is still the right starting pick** for a single-user assistant — cleanest API, shortest path to working memory, strongest ecosystem, free self-host. Confirmed against mid-2026 comparisons.
- **Correction to the migration path:** Zep retired its self-hosted Community Edition in 2025. If you outgrow Mem0 on temporal reasoning ("what changed since last month"), the free migration target is **Graphiti** (Zep's open-source engine, standalone) — Zep hosted costs money. The ~1,000-entry / stale-recall threshold for considering the move stands.
- Embeddings (nomic-embed-text default, EmbeddingGemma/Qwen3-Embedding for quality), sqlite-vec on laptop, Supabase pgvector on VPS, raw personal data local-only: all unchanged.
- Plain markdown + local semantic search remains the underrated portable option. Also note Anthropic ships an example "import-memory" skill pattern — Claude-native memory files are a legit lightweight layer alongside Mem0 for the Claude-executor side.

---

## Build Order — expanded roadmap **[UPDATED]**

Each phase: what you build, what "done" looks like, what it depends on.

### Phase 0 — Harden the bus (days)
**Build:** HMAC verification on the Meta webhook, bearer token on FastAPI, durable job queue (Supabase table: id, payload, status, checkpoint, created_at), structured logs, `/status` endpoint. **[NEW]** Also: create all API keys now (Groq, Cerebras, Gemini AI Studio, OpenRouter, NVIDIA NIM, Mistral, DeepSeek) and drop a minimal router module with the 8-rung fallback chain into the bus, reading rate-limit headers. One evening of work, and every later phase gets model access for free.
**Done when:** a WhatsApp message survives the laptop being asleep and executes on wake; unauthorized webhook calls bounce; you can watch a job move queued → running → done in logs.

### Phase 1 — Persistent memory (1–2 weeks)
**Build:** sqlite-vec + nomic-embed-text locally, Mem0 wrapping it, backfill from notes/WhatsApp exports, wire read/write into every bus interaction. Fact-extraction calls route through the free tiers (Gemini Flash or NIM), overflow to DeepSeek Flash — not through Claude Max.
**Done when:** you tell it something on Monday and it uses it unprompted on Thursday.

### Phase 2 — FL Studio win + deterministic Windows automation (1–2 weeks)
**Build:** PyFLP end-to-end: WhatsApp message → queue → laptop executor renames mixer tracks in a closed `.flp` → backup kept → confirmation reply. Then pywinauto (UIA) for 2–3 accessible apps.
**Done when:** "sort out this FLP" works from your phone with FL closed and reopening the project confirms clean edits. This is the headline demo; do the PyFLP proof-of-concept THIS WEEK alongside Phase 0.

### Phase 3 — Voice (1–2 weeks)
**Build:** amd/whisper.cpp on the NPU, openWakeWord, Kokoro TTS, Pipecat + Silero VAD for barge-in, wired into the WhatsApp bus (voice note in → action → spoken reply out). Groq Whisper as the cloud STT fallback if NPU latency disappoints.
**Done when:** you say "Hey JARVIS" at the desk and it answers out loud, and a WhatsApp voice note from campus comes back as an executed action + audio reply.

### Phase 4 — Always-on split (1 week)
**Build:** move webhook/bus/queue/web UI to Oracle (2 OCPU/12GB from day one). Laptop becomes pull-based executor. `powercfg` stay-awake-on-AC profile. **[UPDATED]** Set up cloud Cowork scheduled tasks for recurring laptop-off jobs, and at least one **API-triggered Cloud Routine** the VPS can fire on demand. Route jobs three ways at enqueue time: needs-laptop (queue), Anthropic-cloud-capable (Routine trigger), VPS-local (run inline).
**Done when:** laptop lid closed, you message it from campus, and the right jobs still run — with the laptop-only ones waiting cleanly in the queue.

### Phase 5 — Vision fallback (optional)
**Build:** UI-TARS Desktop in a second Windows user session, for the shortlist of apps with no file format or UIA surface. Vision-model calls through Gemini Flash / NIM free tiers first. Treat as best-effort, never a critical path.

---

## Who does what — the actual runbook **[NEW]**

Three workers on this project, not two:

- **You** — the only one with your phone, your ears, your card, 2FA codes, passwords, and taste. Also the dictation layer: anywhere a spec or a decision needs writing, you can voice-dictate it into Claude web / the extension instead of typing, and paste the result to the agent.
- **CLI agents (Claude Code / Codex in terminal)** — full arms on the machine: pip/npm/git, build from source, edit and move files anywhere, SSH into the VPS, run elevated commands from an admin terminal, create Windows services and scheduled tasks.
- **Browser agents (Claude in Chrome / Codex extension)** — click through web consoles: navigate dashboards, fill forms, create API keys, set webhook fields, read docs. You keep the tab visible; you personally type passwords, approve 2FA, solve captchas, and enter card numbers. Never let a browser agent free-run on a payment or billing page.

Hard rules that never bend:
1. **Secrets never pass through chat.** CLI agent creates `.env` + `.env.example` and gitignores `.env` before the first commit; you paste real keys into `.env` yourself.
2. **Payments and card entry are you, always.**
3. **Dashboard changes get your eyeball before save** (webhooks, DNS, billing, permissions).
4. **Destructive ops need your explicit go** — deleting instances, dropping tables, writing to an original `.flp`. Agents work on copies until proven.

### Phase 0 — Harden the bus

**0.1 Repo + skeleton — CLI agent, ~30 min.** Creates the project repo: `bus/` (FastAPI app), `router/` (LLM routing module), `executor/` (laptop worker, stub for now), `infra/` (terraform later), `.env.example`, `.gitignore`, README. Venv, pinned deps, git init.

**0.2 API key harvest — browser agent drives, you supervise, ~1 hr for all seven.** Same pattern each time: browser agent opens the console and walks to the key page, stops at the auth wall for you, you log in, agent creates a key named `jarvis-router`, you copy the key straight into `.env` (never into the chat).
- Groq: console.groq.com
- Cerebras: cloud.cerebras.ai
- Google AI Studio: aistudio.google.com — you do the Google login; have the agent make the key in a fresh project so limits don't tangle with anything else you run
- OpenRouter: openrouter.ai — key is free; the one-time $10 that unlocks 1,000/day is your call and your card
- NVIDIA: build.nvidia.com — free Developer Program signup, you verify the email
- Mistral: console.mistral.ai — experiment tier key
- DeepSeek: platform.deepseek.com — you attempt the $2–3 top-up with your card FIRST, before any code depends on it. Card fails from Pakistan → skip direct DeepSeek, note in `.env` that DeepSeek routes through OpenRouter paid instead, move on.

**0.3 Meta webhook config — you + browser agent, ~20 min.** CLI agent generates the verify token (`openssl rand -hex 32`) into `.env`. Browser agent opens developers.facebook.com → your app → WhatsApp → Configuration, fills the callback URL (your Cloudflare tunnel) and the verify token. You press Save and confirm the handshake passes.

**0.4 Supabase — you create, agent builds, ~30 min.** You create the project (org, region, DB password → `.env`). CLI agent writes and applies the `jobs` table migration: id uuid pk, kind text, payload jsonb, status text (queued/running/done/failed), checkpoint jsonb, run_after timestamptz, created_at, updated_at, index on (status, run_after). Also writes the small `jobs.py` client both bus and executor will import.

**0.5 Bus hardening — CLI agent, one session.** HMAC-SHA256 verification of `X-Hub-Signature-256` on the webhook (bad sig → 403 + log), bearer-token middleware on every non-webhook route, JSON-lines structured logging with request IDs, `/status` endpoint (queue depth, last job, per-provider health), and converting any inline "do the work" code into enqueue-only.

**0.6 Router module — CLI agent, same session.** `providers.yaml` with the 8 rungs (endpoint, key env-var, priority, default model), one client via the OpenAI SDK with base_url swap per provider, 429/5xx backoff that reads `retry-after` and `x-ratelimit-*` headers, a cooldown ledger so a limited provider gets skipped instead of hammered, a `route(task_profile)` entry point (latency / batch / long-context / vision / reasoning profiles reorder the rungs), and a DeepSeek off-peak gate: non-urgent DeepSeek-bound jobs wait for off-peak UTC windows unless flagged urgent. Pytest that fakes a 429 cascade down the whole chain.

**0.7 Prove it — you, 10 min.** Laptop asleep, WhatsApp it from your phone, wake it, watch the job go queued → running → done in the logs. Then curl the webhook with no signature and confirm the 403.

### Phase 1 — Memory

**1.1 Local embedding stack — CLI agent.** Install Ollama, `ollama pull nomic-embed-text`, install sqlite-vec, create `memory.db` (vec table + plain `facts` table: id, text, source, created_at), wire Mem0 in self-host mode against the local embedder and sqlite, expose `remember()` / `recall()` to the bus.

**1.2 Choosing the corpus — you, one sitting.** Decide the ingest list: which notes folders, which WhatsApp chats. Export chats from your phone (per-chat → Export, no media), drop the .txt files into `ingest/`. Nothing enters memory that you didn't put in this folder — that's the privacy boundary, and it's yours to hold.

**1.3 Backfill pipeline — CLI agent.** Chunker (per-message for chats, ~500-token chunks for notes), local batch embedding (free), Mem0 fact-extraction with LLM calls routed through Gemini Flash / NIM rungs — batched under free-tier daily caps, spilling to DeepSeek Flash off-peak if the corpus is big. Resumable job (checkpoint = file + offset) so an interrupted backfill continues instead of restarting.

**1.4 Wire in + review — agent, then you.** Agent makes every inbound message do recall() before the model call and remember() after. Then you interrogate it: ask ten things it should know from the backfill. Wrong or creepy facts → you delete them and tell the agent which pattern to exclude (e.g. stop extracting "facts" from forwarded memes). The agent cannot judge whether a remembered fact about your life is right; that check is permanently yours.

### Phase 2 — FL Studio + Windows automation

**2.1 Guinea pigs — you, 5 min.** Copy 2–3 real `.flp` projects into `test_projects/`. Originals never get touched. Dictate your mixer conventions to the agent — what "sorted" actually means in your projects: order, name prefixes, colors, routing groups. This spec is the whole difference between "renamed tracks" and "sorted like I would."

**2.2 PyFLP scripts — CLI agent.** `pip install pyflp`, then: `flp_backup()` (timestamped copy before every write), parse → apply your rules → save, a diff report (old name → new name per insert), and a verify pass that re-parses the saved file and confirms edits stuck. Wrapped as an executor job type (`kind: flp_sort`, payload: path + ruleset).

**2.3 Verification loop — you.** Open each edited project in FL Studio: loads clean, mixer matches the diff report, audio plays, nothing else moved. Every run at first; spot-checks once it's boring.

**2.4 pywinauto targets — you pick, agent builds.** You name the 2–3 apps and dictate the end state per app in plain words. Agent dumps each app's UIA tree programmatically (inspect.exe as backup), finds control names, writes scripts with explicit waits and post-action verification (read the control state back — never assume the click landed), registers each as a job type.

### Phase 3 — Voice

**3.1 Builds — CLI agent.** Clone + build amd/whisper.cpp with NPU offload, download Whisper large-v3, install openWakeWord, Kokoro (+ voices), Pipecat, Silero VAD. Write a benchmark script reporting STT latency on a 10-second Urdu/English clip.

**3.2 Physical layer — you.** Mic placement, run the benchmark, make the call: NPU latency fine, or STT flips to Groq Whisper. Listen to Kokoro's voices, pick one. Record wake-word samples — 30–50 clips of you saying "Hey JARVIS" at different distances and tones. Agent writes the recording script that prompts and saves each clip; you just talk at it.

**3.3 Wake model + pipeline — CLI agent.** Train the custom openWakeWord model on your clips. Assemble the Pipecat loop: wake word → VAD → STT → bus → TTS, with barge-in. Separately the WhatsApp path: voice note in → transcript → bus → action → Kokoro reply encoded to ogg/opus for WhatsApp.

**3.4 Acceptance — you.** Say it from across the room. Send a voice note from campus. Judge latency and voice quality by ear, report what feels off, agent tunes.

### Phase 4 — Always-on split

**4.1 Oracle signup — you, browser agent assisting.** The one signup that regularly fights people. Browser agent walks the form; you do identity, card verification, and the region pick (choose one with A1 capacity; "out of capacity" → retry later or another region, your call — and if it drags for days, your call to just pay Hetzner ~PKR 1,240/mo). Then create the OCI API key and hand the CLI config to the agent.

**4.2 Provision + harden — CLI agent.** OCI CLI/terraform: one A1 instance at exactly 2 OCPU / 12GB, Ubuntu. SSH in: non-root user, key-only SSH, ufw (tunnel + SSH only), fail2ban, unattended-upgrades, Docker. Deploy bus + router + web UI as containers, point the Cloudflare tunnel at the box, flip the webhook URL — then you re-verify in the Meta dashboard (2 min).

**4.3 Laptop becomes executor — CLI agent.** Pull-based executor as a Windows service (or logon scheduled task): polls Supabase for `needs_laptop` jobs, runs, checkpoints. Plus the `powercfg` stay-awake-on-AC profile and the scheduled task that toggles it when jobs are expected.

**4.4 Anthropic cloud lane — you in the UI, agent on the VPS side.** You create the Cowork scheduled tasks and at least one Cloud Routine in the Claude UI — browser agent can navigate, but it's your account, so what each routine is allowed to touch is your approval. Grab the Routine's HTTP trigger endpoint into `.env`. CLI agent adds the enqueue-time classifier: needs-laptop → queue; cloud-capable → fire the Routine trigger; trivial → inline on the VPS. You set the data rule once (what may live on the VPS vs laptop-only); agent enforces it in the classifier.

**4.5 Acceptance — you.** Lid closed, at campus: send one job of each class. Cloud one runs now, VPS one runs now, laptop one waits cleanly and fires on wake.

### Phase 5 — Vision fallback

**You:** create the second Windows account, log in once to initialize the profile, then babysit the first UI-TARS runs — watch what it actually clicks before trusting it with anything.
**CLI agent:** install UI-TARS Desktop in that session, point it at a free VLM tier (Gemini Flash / NIM), wrap jobs with hard timeouts + screenshot-on-fail, register as a best-effort job type.

### Ongoing

**CLI agent, scheduled:** a monthly facts-check job — re-verify the Agent SDK pause, DeepSeek rates, free-model rosters, promo expiries, and write you a one-page diff report. Plus log triage, dependency bumps, and new job types as you invent them.
**You:** read the report, rotate any burnt keys, and make the call when memory or automation does something weird.

---

## Recommendations **[UPDATED]**

- **Do first, this week:** Phase 0 (including the router module + all API keys) and the PyFLP proof-of-concept in parallel.
- **Spend money only here:** DeepSeek prepaid credit, $2–3 to start — that's your overflow layer sorted for months. Hetzner (~PKR 1,240/mo) only if Oracle ARM capacity refuses to provision. Claude API key with a low cap for genuine emergencies. Realistic total: **PKR 600–1,500/mo**, most months near zero.
- **Don't:** rely on WoL from Modern Standby; use consumer ChatGPT/Gemini subs for scripting; put your Max OAuth token in the Agent SDK; reach for vision when a file format or UIA surface exists; hardcode any provider's rate limits or free-model IDs (read headers, use `openrouter/free`); default to DeepSeek V4-Pro (Flash is ~3× cheaper for ~1 benchmark point).
- **Thresholds that change the plan:**
  - Mem0 recall goes stale/contradictory past ~1,000 entries → migrate to **Graphiti** (not Zep hosted).
  - NPU Whisper too slow for live voice → Groq Whisper free tier.
  - Oracle free tier nerfed again → Hetzner CX22.
  - Agent SDK billing pause lifts → move headless/scheduled automation off Max onto DeepSeek Flash + free tiers; keep Max for interactive + Cowork.
  - The +50% weekly Claude promo lapsing (~end Aug 2026) → expect weekly walls ~1/3 sooner; shift more scheduled load to DeepSeek Flash.
  - DeepSeek raises prices again (signaled, undated) → re-check NIM/OpenRouter hosted DeepSeek routes, which have lagged the direct API's price hikes.

---

## Caveats **[UPDATED]**

- **Fast-moving specifics, worse than the original report assumed.** Groq's published limits changed shape (per-model + TPD) within weeks of the report; DeepSeek repriced 5 days after the report's data; the Cowork scheduling model changed within a month. Rule: read runtime headers, use auto-routers, verify any number older than ~30 days before hardcoding.
- PyFLP unofficial/reverse-engineered — back up every `.flp`, verify in FL. Unchanged.
- Thermals — NPU for local inference, cloud free tiers for heavy batch. Unchanged.
- Modern Standby remains the real "always-on laptop" constraint; the honest architecture keeps the brain on the VPS + Anthropic cloud and treats the laptop as an intermittently-available executor. Unchanged.
- Vision GUI agents remain demo-grade. Unchanged.
- DeepSeek platform payment from Pakistan: verify your card works before depending on the direct API; OpenRouter-paid is the fallback route.
- Exchange rate ~PKR 278/USD (21 Aug 2026).