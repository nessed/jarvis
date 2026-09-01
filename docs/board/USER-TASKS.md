# Ali's checklist

Things only you can do — hands, ears, accounts, cards. No order except
where noted. Agents: never nag about these individually; mention at most
once in a batched handoff, and only ones that newly became actionable.

- **U1 — Answer `QUESTIONS.md`.** One message makes 6 agent tasks ready
  immediately and 3 more behind their build dependencies.
  Highest-leverage 10 minutes available.
- **U2 — Paste the 5 model-ID lines into `.env`** (exact lines in Q5).
  2 minutes. Unblocks `live-routing-probe`.
- **U3 — Sleep/wake probe.** Send a WhatsApp message with the lid closed,
  wake the laptop, confirm the reply arrives. The one Phase 0 criterion
  with no evidence. You said you'd do it later (1 Sep) — whenever.
- **U4 — Wake-word false-positive day.** After `wakeword-fp-monitor`
  lands: run the one command it gives you, leave it listening while you
  work/talk normally for a few hours, then tell an agent "read the FP
  log". Closes the last Phase 3 measurement.
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
- **U10 — UI-TARS second Windows account** (Phase 5, parked until you
  care): create it, log in once, babysit the first runs.
