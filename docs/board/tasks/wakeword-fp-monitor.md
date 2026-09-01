---
id: wakeword-fp-monitor
status: ready
lane: AUTO
priority: 3
phase: 3
blocked-on: none
files: voice/listen_wakeword.py, tests/voice/test_listen_wakeword.py, docs/tasks/wakeword-fp-report.md
resources: none (Ali runs the live session — U4)
---

# wakeword-fp-monitor — make the false-positive test a one-command job

## Goal

The last unmeasured Phase 3 number is the wake word's false-positive rate
over hours of ordinary talking — sensory, so the *session* is Ali's (U4),
but today he'd have to babysit a meter. Reduce his part to: run one
command, live his life, say "read the log".

## Steps

1. Add `--log PATH` to `voice/listen_wakeword.py`: append one JSON line
   per detection (timestamp, score) plus a session header/footer
   (start/stop time, threshold, model). Default path under a gitignored
   `voice/logs/`.
2. Add `--summary PATH`: print detections/hour, score histogram, session
   duration from a log file — this is what an agent runs afterwards.
3. Make long sessions safe: no unbounded memory, Ctrl+C writes the footer.
4. Tests against the existing fakes in
   `tests/voice/test_listen_wakeword.py` (landed 1 Sep) — log format,
   summary math, footer-on-interrupt.
5. Write the exact one-liner for Ali into `docs/board/USER-TASKS.md` U4
   and stub `docs/tasks/wakeword-fp-report.md` with a table the summary
   fills.

## Verification

Full offline suite green; a short real `--log` run on this machine
produces a parseable log and correct `--summary` (cite).

## Done when

U4 is literally one command + one sentence to an agent.

## Log

_(empty)_
