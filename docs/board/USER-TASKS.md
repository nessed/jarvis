# Ali's checklist

Things only you can do — hands, ears, accounts, cards. No order except
where noted. Agents: never nag about these individually; mention at most
once in a batched handoff, and only ones that newly became actionable.

- **U1 — Answer `QUESTIONS.md`. Done 1 Sep 2026** — all 10 answered in one
  message; 6 tasks went `ready`, 2 more shed their `Q` gate.
  Q9 and Q10b were followed up and closed the same day — Q9 approved with
  the orphan row carved out for your review, Q10b answered with your own
  §3.3 text.

  **One new question, Q11**, falls out of that §3.3: it makes a rung
  eligible only with "a verified 200 within the current verification
  window", and the window has no duration. Recommendation is in the file
  — "24h + eligible-but-last" takes it. Blocks one new router task, and
  nothing that is currently `ready`.
- **U2 — Paste the 5 model-ID lines into `.env`. Still open, and it is now
  a *latency* item, not just a dead-rung item.** Measured 4 Sep 2026: the
  ladder has collapsed to `openrouter`, which answers a one-word question
  in 2.4-2.65 s, and a text reply makes two such calls — about 5 s of a
  ~10 s reply. `groq` is priority 1 in the manifest because it is the fast
  rung, and the only thing excluding it is the unset `GROQ_DEFAULT_MODEL`.
  This is the largest single remaining lever on reply speed and it costs
  one paste. Detail: `docs/history/infra-audit-2026-09-04.md`. Ali gave the
  values on 1 Sep (his own, differing from the researched set: Groq 120b
  not 20b, Gemini 3.6-flash not 2.5-flash, Cerebras deliberately blank)
  and said "pasted" — but a key-name check of the repo-root `.env` that
  day found none of the five keys present. 2 minutes. Unblocks
  `live-routing-probe`, which is the only thing that proves the new IDs
  serve.
  **DONE 9 Sep 2026.** The agent set all four model IDs after verifying each
  against the provider's own live `/models` endpoint. The ladder went from
  three rungs to six, with Groq leading. See `docs/state.md`, "Provider ladder".


  **Now measurable, 2 Sep evening.** `router-unresolvable-model-rungs` made
  the router say which rungs it is refusing and why. Against the current
  `.env`, **three** are excluded rather than the two previously reported:

  ```
  groq        no model: its default_model placeholder is unset in .env
  cerebras    no model: its default_model placeholder is unset in .env
  gemini      no model: its default_model placeholder is unset in .env
  nvidia_nim  no API key in NVIDIA_API_KEY
  ```

  That leaves `openrouter, mistral, deepseek` as the entire ladder for both
  `latency` and `batch`. Filling in `GROQ_DEFAULT_MODEL`,
  `CEREBRAS_DEFAULT_MODEL` and `GEMINI_DEFAULT_MODEL` restores the top three
  rungs by itself.
- **U3 — Sleep/wake probe.** Send a WhatsApp message with the lid closed,
  wake the laptop, confirm the reply arrives. The one Phase 0 criterion
  with no evidence. You said you'd do it later (1 Sep) — whenever.
- **U4 — Wake-word false-positive day.** Ready now — `wakeword-fp-monitor`
  landed 2 Sep 2026. Run this, then live your evening and Ctrl+C when you
  are done:

  ```
  .venv\Scripts\python.exe voice/listen_wakeword.py --seconds 0 --log
  ```

  Then say **"read the wake word log"** to an agent. That is the whole task.

  It records a timestamp and a score per firing and nothing else — no audio
  is captured or written. The log is gitignored (`voice/logs/`).

  Worth a second evening at `--threshold 0.3`: if 0.3 is quiet enough in your
  room, the wake word gets much easier to trigger from across it.

  Closes the last unmeasured Phase 3 number. What only you can answer: of the
  firings logged, how many were you actually saying it?
  See `docs/tasks/wakeword-fp-report.md`.
- **U5 — The ten-question memory review** (blueprint 1.4, Phase 1's real
  acceptance gate). Only after `backfill-run` completes: ask JARVIS ten
  things it should know, delete what's wrong via `tools/review_facts.py`,
  name exclusion patterns. Your judgment, permanently.
- **U6 — Desk voice acceptance.** After `voice-loop` lands: talk to it at
  your desk, judge latency, interruption, and voice by ear; report what
  feels off.
- **U7 — Oracle Cloud signup** (Phase 4's gate). One sitting with a
  browser agent driving: identity, card verification, region pick,
  provision at **exactly 2 OCPU / 12 GB** (over-limit auto-terminates),
  then hand over the OCI API key config. `phase4-prep` will have the
  runbook ready so the agent side is same-day.
- **U8 — Create the Cloud Routine** in the Claude UI (Phase 4, after U7):
  decide what it may touch, paste its trigger endpoint + token into
  `.env`.
- **U9 — Mistral 403** (optional, low value): one logged-in look at
  admin.mistral.ai → workspace limits to see why chat 403s. Or ignore and
  answer Q6 accordingly.
- **U11 — One code-switched voice note, whisper-server off** (2 min,
  sensory). The Groq STT fallback is live and word-perfect on English, but
  the production language hint is forced `ur`, and on a pure-English test
  clip that came back as garbage. That is the documented trade
  (`voice/config.py`), and a synthetic English clip is not how you talk — so
  it proves nothing either way about your real messages. Stop
  whisper-server, send one normal Urdu/English voice note, and say whether
  the reply shows it understood you. If forced `ur` degrades the cloud tier
  the way it degrades English, the fallback gets its own language setting
  instead of inheriting the local backend's. Which way that goes is a
  judgement about your own speech.
- **U12 — Fill `SUPABASE_DB_PASSWORD` in `.env`** (2 min, unblocks
  `db-maintenance`'s live half). The key is already there and empty. It is
  the database password you set when you created the Supabase project —
  Dashboard → Project Settings → Database → Reset password if it is lost.
  Paste it straight into `.env`, never into a chat.
  Nothing else needs it: the REST key already in `.env` can read and write
  rows, but it cannot run DDL, which is why `0003` cannot be applied without
  this. The migration runner, its ledger and `0003` are built, tested and
  committed; `.venv\Scripts\python.exe -m db.migrate --dry-run` will print
  the plan the moment the value lands, and applying it is one command after
  that.
- **U13 — One `git config` line: `.git` is owned by another Windows account**
  (1 min, unblocks git for every agent session). Every `git` command in this
  repo now fails outright:

  ```
  fatal: detected dubious ownership in repository at
  'C:/Users/Ali/Desktop/Projects/Code/jarvis'
  '.../.git' is owned by: DESKTOP-68UQJNR/CodexSandboxOffline
  but the current user is: DESKTOP-68UQJNR/Ali
  ```

  `.git` changed owner to the `CodexSandboxOffline` account at some point, so
  git refuses to touch the repo as `Ali`. It also fails **four**
  `tests/tools/test_context_status.py` tests, which shell out to `git` — those
  four are an environment fault, not a regression, and they pass the moment
  git works.

  The fix is one line, and `agents.md` puts global git config on the
  ask-first list, so it is yours to run rather than an agent's:

  ```
  git config --global --add safe.directory C:/Users/Ali/Desktop/Projects/Code/jarvis
  ```

  Until then agents can work around it per command
  (`GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0=...`),
  which is what `distill-chain-stall` used to commit on 2 Sep — but that has
  to be re-exported in every shell, and the first session that forgets reads a
  red suite as a real failure.

  Worth knowing **why** the owner changed if you can tell — a repo whose
  `.git` another account can write is a bigger question than the warning.

- **U14 — Send one WhatsApp command and check you get two replies**
  (1 min, sensory; needs `start-jarvis.bat` running). The outcome reply
  shipped 2 Sep 2026 and the machine half is proved live end to end — a real
  `system_control` job produced a real `whatsapp_outcome` row carrying
  `Wi-Fi (connected)`, and a deliberately-broken one produced its failure
  twin. What no test can prove is the part with your thumb in it.

  Send: **"what wifi interfaces does this laptop have?"**

  Expect **two** messages, a few seconds apart:

  ```
  On it: list wifi interfaces. Queued as job a8b4785b.
  Done: list wifi interfaces. Wi-Fi (connected).
  ```

  If only the first arrives, say so — the likely cause is `whatsapp-worker`
  not having picked up the new `whatsapp_outcome` kind, which needs a
  restart rather than a fix.

- **U10 — UI-TARS second Windows account** (Phase 5, parked until you
  care): create it, log in once, babysit the first runs.

- **U15 — Kill two orphaned `whisper-server.exe` processes** (30 s). Two
  are alive from launches at 18:17 and 19:50 on 4 Sep, 750 MB between them,
  both holding port 8081, with the stack down. The launcher now attaches
  every child to a Windows Job Object so this cannot recur, but the two
  that already exist are yours to end — agents never kill a process they
  did not spawn. Task Manager, or:

  ```
  taskkill /PID 9748 /PID 21308
  ```

  (PIDs as of 4 Sep 20:30; check Task Manager first if it is a later day.)

- **U16 — Time the new startup and one reply of each kind** (5 min,
  sensory). Double-click `start-jarvis.bat`; the last banner line now
  prints the total seconds. Then send one text and one voice note and note
  roughly how long each reply took. Report the three numbers. That is the
  only way to know whether 4 Sep's connection-reuse and warm-up work is
  felt on the phone rather than only in a probe.

- ~~**U7 is what "deploy" means.**~~ Superseded 8 Sep 2026 by U17 — the
  hosting answer moved from Oracle Always Free to a rented x86 box. The
  Oracle runbook section stays valid if you ever go that way instead.

- **U17 — The box. Now Azure, on your own account, not your brother's AWS**
  (Q17-D1, re-answered 9 Sep 2026). You have the GitHub Student Pack, so
  **Azure for Students** gives you $100/year of credit with **no credit
  card**, and your brother's money goes to voice/LLM API costs instead.

  **What to do** (~20 min, all yours — signup and card-free verification
  can't be delegated):
  1. Activate **Azure for Students** at
     `azure.microsoft.com/free/students` with your student email. No card.
  2. Create a **Virtual Machine**: Ubuntu **24.04 LTS**, size **B2s or
     B1ms** (2 GB RAM — do not take the 1 GB B1s, it is too tight once
     memory lives on the box), region **Central India** (nearest to you;
     `South India` is the alternative).
  3. Authentication: **SSH public key**. Paste in the contents of
     `~/.ssh/id_ed25519.pub` from this laptop — the agent can print that
     one for you, it is public by definition. If it does not exist yet, ask
     and the agent generates it.
  4. Networking: allow **SSH (22) only**. Nothing else needs to be open —
     the webhook arrives through a Cloudflare tunnel that dials outward.
  5. Paste the VM's **public IP** into chat. It is not a secret. The SSH
     *private* key never leaves this laptop.

  **The cliff, so it does not surprise you:** $100 is ~7 months at this VM
  size, and Azure **cancels the subscription** when the credit runs out
  rather than charging you. That means JARVIS goes offline, not that you
  get a bill. Renew the student credit annually, or convert to pay-as-you-go
  before it lapses.

  **Fallback, unchanged and still valid:** your brother's AWS Lightsail,
  2 GB plan (~$10-12/month), Ubuntu 24.04 x86, region Mumbai
  (`ap-south-1`). The runbook keeps both sections and nothing built so far
  is cloud-specific, so switching costs one provisioning sitting.

  Unblocks `vps-harden-deploy` → laptop-off replies.

- **U18 — Paste `JARVIS_OWNER_WA_ID` into `.env`** — **DONE 9 Sep 2026.**
  Ali pasted his own WhatsApp sender id in international form (the shape
  Meta sends in the payload, no leading zero and no `+`). Verified without
  printing it: the gate recognises the owner, rejects another number, and
  rejects a near-miss with one extra digit. The startup warning no longer
  fires. The value stays in `.env` only and appears in no other file.

- **U19 — One-time $10 OpenRouter credit** (Q17-D9, only if you say yes
  to D9). Lifts its free tier from 50 to 1,000 requests/day permanently
  and is the overflow lane behind Groq. Card entry is yours; the agent
  navigates.

- **U20 — One real reply, timed end to end** (5 min, sensory + one env
  line). `latency-spans` landed the measurement: every replied job now
  logs one `reply-latency` line, and `tools/reply_latency.py` prints
  p50/p95 per stage. What is missing is a run through the *real* queue and
  the *real* Graph API send, which needs two things from you:
  1. Add `JARVIS_LIVE_WHATSAPP_TO=<your own WhatsApp number, as Meta
     writes it in a webhook `from` field>` to `.env`. It is deliberately
     not in the repo — a phone number is personal data and the test file is
     committed.
  2. Start the stack (`start-jarvis.bat`) and leave it up for a minute.

  Then the agent runs
  `.venv\Scripts\python.exe -m pytest -q -m live tests/live/test_text_reply_latency.py -s`,
  which enqueues one probe job and **sends you one real WhatsApp reply**.
  That number is the baseline every task in the September latency batch is
  measured against. Without it the batch's before/after is three replayed
  samples, not the phone.
