# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `3695c05 Cover three untested voice CLIs, make the schema drift detector able to fail, and reconcile the docs` on `main`, in sync with origin.

**Working tree:** 3 changed

```
  M  docs/context.md
  M  docs/plan.md
  M  docs/state.md
```

**Offline suite:** 976 passed, 9 deselected, 2 warnings in 63.16s (0:01:03) _(recorded 2026-09-01)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `3695c05` Cover three untested voice CLIs, make the schema drift detector able to fail, and reconcile the docs  _(2026-09-01)_
- `52e2c03` push  _(2026-09-01)_
- `37c51d4` Fix two live-verification bugs: wrong whisper-server binary, and force voice replies to stay in English  _(2026-08-31)_
- `51e3a84` Wire voice notes into the WhatsApp handler and run whisper-server as a managed process  _(2026-08-30)_
- `0391f3f` Land desktop automation, the typing-cue fix, and NPU voice STT  _(2026-08-29)_
- `4f39697` Land the voice runtime, the fact-review path, and an FLP project inspector  _(2026-08-29)_
- `221ce33` Record this session's lane briefs and consult exchanges  _(2026-08-29)_
- `50233bc` Record the model-ID gap, dual message-id dedup, and a full board pass  _(2026-08-29)_

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

**FL Studio: the audit is done, the convention is not.** 26 entries were read
(`docs/tasks/flp-audit-data.json`) — 25 of Ali's real projects plus PyFLP's own
`FL 20.8.4` fixture.
Takes land on random lanes because FL's own "auto-create audio clips" uses the
first free lane — the documented fix is Audio Track mode, no discipline needed.
He has three competing naming schemes, not one, and names things only above
~5h invested. **17 parse clean, 7 parse partially, 2 fail outright**
(`outroforest`, `prayon`) — recounted 1 Sep 2026, the earlier "18 of 24" was
wrong in both numbers. Every failure is loud; none are silent.
`tools/flp_inspect.py` is read-only and now has 28 tests
(`tests/tools/test_flp_inspect.py`, landed in `52e2c03`), so the gate that
said "do not build the writing half on it until it does" is cleared. The
writing half is still blocked on the convention below, not on coverage.

**Docs were audited against the tree, 1 Sep 2026.** ~88% of checkable claims
held. The rest are fixed; the full finding list is
`docs/tasks/docs-drift-audit-report.md`. The two that mattered most: `state.md`
claimed the executor topology "is not live" when both workers had been polling
since 31 Aug, and `plan.md`'s cross-lane test-double index — the section that
exists to stop a stranded test double shipping a red tree — had rotted on 4 of
11 pointers.

## Waiting on you

**Closed by Ali, 1 Sep 2026** — two of the three items below were closed out on
his instruction. Recorded as closed by decision, not as verified by an agent.

1. ~~**Rotate the Meta verify token.**~~ **Closed on Ali's instruction, 1 Sep
   2026.** No agent verified a rotation and none can: the token's value is
   never read by an agent by design. This entry records his decision to stop
   tracking it, and is **not** evidence that the credential was rotated. The
   leak itself is fixed at the source either way — uvicorn's access log now
   redacts both `hub.verify_token` and `hub_verify_token`, and the log was
   gitignored throughout, so nothing reached a commit.
2. ~~**The FL Studio sorting convention.**~~ **Closed on Ali's instruction,
   1 Sep 2026 — no convention was dictated.** See the standing note below;
   this closes the *question*, not the gap.
3. **`queue-sleep-wake-probe`** — send a message with the lid closed, wake,
   confirm. **Ali will do this later** (his call, 1 Sep 2026). Still the one
   Phase 0 criterion with no evidence anywhere.

**Standing constraint, unchanged by the above.** No mixer-sorting convention
exists, so `apply_rules()` still runs on a **placeholder ruleset that nobody
approved**. Closing the question does not approve the placeholder. The FLP
*writing* half stays unbuilt, and no agent may infer a convention from the
audit, from `outroagain`'s layout, or from the placeholder itself. If that is
not what Ali meant, he says so and this note comes out — but guessing a
convention and writing to his real project files is not recoverable, so the
default is to not.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
