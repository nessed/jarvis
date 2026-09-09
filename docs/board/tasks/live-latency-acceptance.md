---
id: live-latency-acceptance
status: blocked
lane: AUTO
priority: 2
phase: 4
blocked-on: Q17-D13 — latency-spans landed 8 Sep 2026
files: tests/live/test_text_reply_latency.py, tests/live/test_voice_reply_latency.py (new), docs/blueprint.md (acceptance table, only with D13's yes)
resources: none
---

# live-latency-acceptance — stub

Q17-D13: make the reply-latency targets (text p50 < 3 s / p95 < 6 s,
voice < 8 s, laptop-off text < 3 s) assertions in `tests/live`, so a
phase is complete when a stopwatch says so. `latency-spans` records the
numbers; this task adds the thresholds and the blueprint acceptance
table. Nothing to build until D13 is answered.

## Log

_(empty)_
