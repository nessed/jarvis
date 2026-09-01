---
id: cloud-routine-wire
status: blocked
lane: AUTO
priority: 3
phase: 4
blocked-on: U8, bus-offbox-packaging
files: bus/main.py (hot), bus/routines.py (new), tests/bus/, tests/router/test_routing.py (area-hot, only if the router is touched)
resources: none until live
---

# cloud-routine-wire — stub

Fire an Anthropic Cloud Routine from the bus
(`POST /v1/claude_code/routines/{id}/fire`). Before building, re-read
`docs/audit/blueprint-drift.md`'s six caveats: research-preview beta
header, `trig_` id prefix, UI-only token rotation, untrusted
`<routine-fire-payload>` framing, **no idempotency key** (dedupe on our
side before firing), claude.ai-login auth only. Expand into a real guide
when U8 exists.

## Log

_(empty)_
