---
id: wakeword-fp-monitor
status: done
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

**2 Sep 2026 — done.** U4 is now one command plus one sentence.

### What Ali runs

```
.venv\Scripts\python.exe voice/listen_wakeword.py --seconds 0 --log
```

Then, whenever: **"read the wake word log"**. Written into `USER-TASKS.md` U4
verbatim, with the reasoning in `docs/tasks/wakeword-fp-report.md`.

### What an agent runs afterwards

```
.venv\Scripts\python.exe voice/listen_wakeword.py --summary
```

### Design decisions worth keeping

- **JSON Lines, flushed per detection.** An overnight session holds nothing in
  memory, and a laptop that sleeps still leaves everything written up to that
  point. Step 3's "no unbounded memory" falls out of this rather than needing
  a cap.
- **The footer is written in a `finally`.** Ctrl+C after an evening is the
  exit Ali will actually use, and without a footer there is no session
  duration, so there is no detections-per-hour. That would have made the one
  path that matters the one path that produced an unusable log.
- **Sessions are summed, not spanned.** A log appended to over three evenings
  is three sessions. Dividing detections by the wall-clock gap between the
  first and last record would divide by the nights in between and report a
  false-positive rate near zero. Tested.
- **The histogram prints empty buckets.** The shape of the tail is the whole
  point; hiding empty buckets makes a cluster at 0.5 look like one at 0.9.
- **`--summary` is handled before the threshold check and before any device
  is opened.** Reading a log is a desk job and must work on a machine with no
  microphone.
- **No audio, ever.** Timestamps and scores only. This runs for hours in
  Ali's room, and blueprint §5 is explicit that wake-word audio never leaves
  the moment it happens. There is a test that greps the written log for
  audio-shaped words and fails if any appear.

### Live verification, real microphone

`microphone-speakers` claimed for the duration and released after. Two real
sessions, both cited from the actual terminal:

```
.venv\Scripts\python.exe voice/listen_wakeword.py --seconds 8 --threshold 0.5 --log
Logging detections to voice\logs\wakeword.jsonl
Done. 0 detection(s). Highest score seen: 0.001
```

```
{"event": "session_start", "at": "2026-09-01T21:11:16.784741+00:00", "threshold": 0.5, "model": "hey_jarvis_v0.1", "device": null}
{"event": "session_end", "at": "2026-09-01T21:11:24.806645+00:00", "elapsed_seconds": 8.03, "detections": 0, "peak_score": 0.0014}
```

A non-zero peak score is the proof the microphone was genuinely read rather
than a silent device returning zeros. A second session ran at
`--threshold 0.0005` to try to cross the line on room noise; the room was
quiet enough that it still scored 0.000, so no detection line came from real
audio. The detection path is covered by tests instead, and that limit is
stated rather than papered over.

`--summary` over both sessions:

```
=== voice\logs\wakeword.jsonl ===
sessions      2
listening     0.00 hours (14s)
detections    0
rate          0.00 per hour
threshold     0.0005, 0.5
```

That run is what prompted the `(14s)` alongside the hours: a short session
otherwise reads as `0.00 hours`, which looks like an empty log rather than a
brief one.

**The verification log was deleted afterwards**, after being cited above, so
Ali's first real session starts from an empty file rather than inheriting two
14-second agent sessions into his own rate.

### Tests

20 new (52 in the file, from 32).

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=<private> tests/voice/test_listen_wakeword.py
52 passed in 0.20s
```

### Full offline suite

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=<private>
1288 passed, 9 deselected, 10 warnings in 68.29s
```

### Scope note

`.gitignore` gained `voice/logs/`. It is not in this task's `files:` and is
held by nobody; the directory is Ali's session data and had to be ignored
before the first log was written. Claimed and released like any other file.

### Specified but not done

`docs/state.md`'s Phase 3 row still calls the false-positive rate unmeasured,
which is still true — the tooling landed, the number has not. `docs/state.md`
has been held by another lane for this entire session.
