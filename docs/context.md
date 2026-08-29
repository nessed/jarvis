# JARVIS context

Temporary tier. What is in flight right now, and nothing else. Read this first,
then `docs/state.md` if you need component status.

Keep the hand-written part under about fifteen lines. If a section is growing,
the facts in it have stopped being temporary and belong somewhere else.

<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->

**HEAD** `4f39697 Land the voice runtime, the fact-review path, and an FLP project inspector` on `main`, in sync with origin.

**Working tree:** 66 changed

```
  M  .gitignore
  M  bus/whatsapp_client.py
  A  docs/blockers/cloudflare-quick-tunnel-ipv6-connectex.md
  M  docs/blueprint.md
  A  docs/consults/2026-08-29-typing-executor-split-decision/prompt.md
  M  docs/context.md
  A  docs/history/voice-first-outbound-note.md
  M  docs/plan.md
  M  docs/state.md
  A  docs/tasks/deps-laptop-system-control.txt
  A  docs/tasks/deps-pywinauto-zoom-whatsapp.txt
  A  docs/tasks/deps-whisper-npu.txt
  ...and 54 more
```

**Offline suite:** 786 passed, 7 deselected, 2 warnings in 68.38s (0:01:08) _(recorded 2026-08-29)_

**Live acceptance suite:** 1 passed in 39.63s _(recorded 2026-08-26)_

**Recent commits**

- `4f39697` Land the voice runtime, the fact-review path, and an FLP project inspector  _(2026-08-29)_
- `221ce33` Record this session's lane briefs and consult exchanges  _(2026-08-29)_
- `50233bc` Record the model-ID gap, dual message-id dedup, and a full board pass  _(2026-08-29)_
- `77c07e5` Stop a Meta webhook redelivery from enqueueing a second job  _(2026-08-29)_
- `e4f15a7` Make queue_depths and retry_health O(1) queries, add distill-chain liveness  _(2026-08-29)_
- `ae158b9` Cover OpenAIChatClient construction and pin mem0ai's private-API surface  _(2026-08-29)_
- `a88dd21` Fix context_status --check being unreachable through main()  _(2026-08-29)_
- `c6565c0` Add coverage for distill_memory's CLI, start_jarvis's uncovered paths, and request_completion  _(2026-08-29)_

<!-- END GENERATED -->

## Now

**The dedicated worker split is live.** `whatsapp_webhook` and
`distill_memory` now have separate supervised pollers, so background extraction
cannot delay the typing cue. The earlier Quick Tunnel IPv6 failures did not
reproduce on relaunch — `tools/start_jarvis.py` provisioned a tunnel
(`https://guns-librarian-carol-choose.trycloudflare.com`) on the first clean
attempt, and `tools/repoint_webhook.py`'s read-back confirms Meta's callback
points at it. Both workers are running (`[4/4] Workers` reported them
polling). Detail and the prior failure's evidence stay in
`docs/tasks/whatsapp_worker_split.md`; this work is still uncommitted.

Two injection fixes landed. Recalled memory reached the model as a **system**
message, so stored inbound text carried operator authority; it is now
user-role and fenced. `tools/consult.py` framed sub-model output the same way.
The distill chain gained a fork guard evaluated at the write site, and
`assert_timeouts_ordered` finally has production callers.

PyFLP works on `.venv311`, pinned to **3.11.5** — 3.11.6 backported the
empty-enum guard, so plain "3.11" is not enough. Blocker 4 is resolved.

**Desktop automation (blueprint 2.4) landed and is wired, not committed.**
Ali named the targets via a personal-context agent: power/wifi/bluetooth/
display/scheduled-tasks/printing/file-ops/process-kill (CLI-only, see
`docs/tasks/laptop-system-control-report.md`), plus Zoom's join-dialog tail
and WhatsApp Desktop send-as-personal-number (real UIA, see
`docs/tasks/pywinauto-zoom-whatsapp-report.md`). Both registered in
`executor/poller.py`'s `DEFAULT_HANDLERS`; neither reachable from WhatsApp
yet (`enqueue-classifier` still undecided). Ali also dictated the target
second-monitor UI — ambient state-circle, no chat/transcript — recorded in
`docs/blueprint.md` §5. **Commit is queued, blocked on `whisper-npu-build`**
(a separate, still-running session) leaving the tree red; will commit/push
automatically once that clears.

## Waiting on you

**The noninteractive Claude consult is unavailable.** Two `tools/consult.py`
attempts launched the CLI but returned no response or verdict; see
`docs/blockers/consult-cli-no-response.md`. Restore the CLI's noninteractive
session without sharing credentials so Class B decisions can use the required
consult path.

1. **Rotate the Meta verify token.** It was written to `tools/bus.out.log` in
   plaintext — the redaction only matched `hub.verify_token`, and the live
   handshake also carried `hub_verify_token`. Gitignored, never committed, now
   fixed both ways.
2. **Typing cue is intermittent, and it is not our bug.** Five real inbound
   messages after the clean relaunch each got a `200 OK` from Meta's
   `POST /messages` typing-indicator call — `0` failures, confirmed by new
   INFO-level logging in `executor/poller.py` and `executor/handlers/
   whatsapp.py`. The cue still only showed sometimes. Meta's own docs say
   this signal is dismissed after 25s and is not a guaranteed/queued
   delivery like the reply text, so intermittent display looks like
   WhatsApp only rendering it when the phone's app has an active connection
   at that moment. Nothing left to fix server-side without evidence of a
   real failure.
3. **Phase 2 needs real `.flp` copies** in `test_projects/` and the dictated
   mixer-sorting convention. Both are yours; PyFLP itself is unblocked.

## Where facts go

| Question | File |
|---|---|
| Will this be false next week? | `docs/context.md`, here |
| Will this still be true next phase? | `docs/state.md` |
| Is it finished, and only evidence now? | `docs/history/` |
| Is it a decision about how the system is built? | `docs/blueprint.md`, and stop and ask first |

`docs/history/` is append-only. Nothing in it is ever edited.
