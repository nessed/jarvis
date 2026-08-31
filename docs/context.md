# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `37c51d4 Fix two live-verification bugs: wrong whisper-server binary, and force voice replies to stay in English` on `main`, 2 ahead, 0 behind origin.

**Working tree:** 25 changed

```
  A  docs/consults/2026-08-30-consult-selftest/prompt.md
  A  docs/consults/2026-08-30-consult-selftest/response.md
  A  docs/consults/2026-08-30-consult-selftest/verdict.json
  A  docs/consults/2026-08-30-work-board-silent-prune/prompt.md
  A  docs/consults/2026-08-30-work-board-silent-prune/response.md
  A  docs/consults/2026-08-30-work-board-silent-prune/verdict.json
  A  docs/history/voice-urdu-language-detection.md
  A  docs/history/work-board-silent-prune.md
  A  docs/tasks/laptop-power-lag-dc-overlay-test-report.md
  A  docs/tasks/laptop-power-lag-dc-overlay-test.md
  A  docs/tasks/laptop-power-lag-hp-bios-f11-report.md
  A  docs/tasks/laptop-power-lag-hp-bios-f11-staging/preflight-security.ps1
  ...and 13 more
```

**Offline suite:** 862 passed, 7 deselected, 2 warnings in 60.41s (0:01:00) _(recorded 2026-09-01)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `37c51d4` Fix two live-verification bugs: wrong whisper-server binary, and force voice replies to stay in English  _(2026-08-31)_
- `51e3a84` Wire voice notes into the WhatsApp handler and run whisper-server as a managed process  _(2026-08-30)_
- `0391f3f` Land desktop automation, the typing-cue fix, and NPU voice STT  _(2026-08-29)_
- `4f39697` Land the voice runtime, the fact-review path, and an FLP project inspector  _(2026-08-29)_
- `221ce33` Record this session's lane briefs and consult exchanges  _(2026-08-29)_
- `50233bc` Record the model-ID gap, dual message-id dedup, and a full board pass  _(2026-08-29)_
- `77c07e5` Stop a Meta webhook redelivery from enqueueing a second job  _(2026-08-29)_
- `e4f15a7` Make queue_depths and retry_health O(1) queries, add distill-chain liveness  _(2026-08-29)_

<!-- END GENERATED -->

## Now

**Phase 3 voice: live-verified end to end, 30 Aug 2026.** A real WhatsApp
voice note gets a spoken English reply. Two bugs surfaced and were fixed
during the live pass — `docs/history/voice-whatsapp-live-verification.md`.

- **Wake word — done, cut.** Pretrained `hey_jarvis_v0.1`, 7/7 detections,
  0.873-0.993 against 0.5. Not used on the WhatsApp path — each message is
  already the trigger. False-positive rate over hours still unmeasured.
- **Language forced to Urdu (STT input only).** `voice/config.py`'s default
  is `ur`, not `auto` — `auto` silently dropped the Urdu half of
  code-switched clips. Replies stay English regardless — Kokoro has no Urdu
  voice. `docs/history/voice-urdu-language-detection.md`

**FL Studio: the audit is done, the convention is not.** 24 of Ali's real
projects were read (`docs/tasks/flp-audit-data.json`, and the published report).
Takes land on random lanes because FL's own "auto-create audio clips" uses the
first free lane — the documented fix is Audio Track mode, no discipline needed.
He has three competing naming schemes, not one, and names things only above
~5h invested. 18 of 24 projects parse; the rest are PyFLP bugs, all loud.
`tools/flp_inspect.py` is read-only and has no tests yet — do not build the
writing half on it until it does.

## Waiting on you

**The FL Studio sorting convention is still yours.** The audit found three
competing schemes in your own projects; `outroagain`'s layout (DRUMS/BASS/
INSTRUMENTS/CHOPS/VOX1-8) is the most complete but exists on one song, so
adopting it is a pick, not a discovery.

1. **Rotate the Meta verify token.** It was written to `tools/bus.out.log` in
   plaintext — the redaction only matched `hub.verify_token`, and the live
   handshake also carried `hub_verify_token`. Gitignored, never committed, now
   fixed both ways.
2. **`queue-sleep-wake-probe`** — send a message with the lid closed, wake,
   confirm. Still the one Phase 0 criterion with no evidence anywhere.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
