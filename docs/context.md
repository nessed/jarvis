# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `0391f3f Land desktop automation, the typing-cue fix, and NPU voice STT` on `main`, in sync with origin.

**Working tree:** 19 changed (plus 9 untracked)

```
  M  bus/whatsapp_client.py
  M  docs/context.md
  M  docs/state.md
  M  executor/handlers/whatsapp.py
  M  tests/bus/test_whatsapp_client.py
  M  tests/executor/test_whatsapp_handler.py
  M  tests/tools/test_start_jarvis.py
   M tests/tools/test_work_board_claim.py
  A  tests/voice/test_audio.py
   M tests/voice/test_config.py
   M tests/voice/test_local_backend.py
  A  tests/voice/test_server_client.py
  ...and 7 more
```

**Offline suite:** 824 passed, 7 deselected, 2 warnings in 68.39s (0:01:08) _(recorded 2026-08-30)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `0391f3f` Land desktop automation, the typing-cue fix, and NPU voice STT  _(2026-08-29)_
- `4f39697` Land the voice runtime, the fact-review path, and an FLP project inspector  _(2026-08-29)_
- `221ce33` Record this session's lane briefs and consult exchanges  _(2026-08-29)_
- `50233bc` Record the model-ID gap, dual message-id dedup, and a full board pass  _(2026-08-29)_
- `77c07e5` Stop a Meta webhook redelivery from enqueueing a second job  _(2026-08-29)_
- `e4f15a7` Make queue_depths and retry_health O(1) queries, add distill-chain liveness  _(2026-08-29)_
- `ae158b9` Cover OpenAIChatClient construction and pin mem0ai's private-API surface  _(2026-08-29)_
- `a88dd21` Fix context_status --check being unreachable through main()  _(2026-08-29)_

<!-- END GENERATED -->

## Now

**Phase 3 voice: wired end to end, not yet live-verified.** A voice note to
JARVIS now gets a spoken reply instead of silence: `executor/handlers/whatsapp.py`
downloads it, decodes it, transcribes it against a warm `whisper-server`
(`tools/start_jarvis.py` now spawns it, best-effort), routes the transcript
like any text message, and answers with a synthesised voice note. Offline
suite covers every seam with fakes (820 passed); nothing has touched a real
voice note yet.

- **Wake word — done, cut.** Pretrained `hey_jarvis_v0.1`, 7/7 detections,
  0.873-0.993 against 0.5. Not used on the WhatsApp path — each message is
  already the trigger. False-positive rate over hours still unmeasured.
- **Language forced to Urdu.** `voice/config.py`'s default is `ur`, not
  `auto` — `auto` silently dropped the Urdu half of code-switched clips.
  `docs/history/voice-urdu-language-detection.md`

**FL Studio: the audit is done, the convention is not.** 24 of Ali's real
projects were read (`docs/tasks/flp-audit-data.json`, and the published report).
Takes land on random lanes because FL's own "auto-create audio clips" uses the
first free lane — the documented fix is Audio Track mode, no discipline needed.
He has three competing naming schemes, not one, and names things only above
~5h invested. 18 of 24 projects parse; the rest are PyFLP bugs, all loud.
`tools/flp_inspect.py` is read-only and has no tests yet — do not build the
writing half on it until it does.

## Waiting on you

**Send JARVIS a real voice note.** The wiring is done and offline-tested but
never exercised against real audio — confirm by ear that it transcribes,
replies, and the reply is audible. The one acceptance test the offline suite
can't cover.

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
