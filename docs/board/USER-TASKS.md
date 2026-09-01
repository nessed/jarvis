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
- **U2 — Paste the 5 model-ID lines into `.env`. Still open.** Ali gave the
  values on 1 Sep (his own, differing from the researched set: Groq 120b
  not 20b, Gemini 3.6-flash not 2.5-flash, Cerebras deliberately blank)
  and said "pasted" — but a key-name check of the repo-root `.env` that
  day found none of the five keys present. 2 minutes. Unblocks
  `live-routing-probe`, which is the only thing that proves the new IDs
  serve.
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
- **U10 — UI-TARS second Windows account** (Phase 5, parked until you
  care): create it, log in once, babysit the first runs.
