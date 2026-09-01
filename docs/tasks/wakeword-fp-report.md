# Wake word false positives — U4

**Status: waiting on Ali's session.** The tooling is built and verified; the
number is not measured yet, and cannot be by an agent.

## The question

`hey_jarvis_v0.1` fires 7/7 when Ali says "Hey JARVIS" — that half is proved.
The unmeasured half is the opposite one: **how often does it fire when he
didn't?** An always-on wake word that trips during a phone call is worse than
no wake word, and the answer decides two things:

- whether `wakeword-train` (a model on his own voice, blueprint 3.2) is needed
  at all, or whether the pretrained model is good enough;
- what threshold the desk loop should ship with. `0.5` is openWakeWord's own
  default, not a tuned value.

It cannot be simulated. It needs hours of Ali's actual room — him talking, a
video playing, someone else in the house — and only he can say whether a given
firing was a mistake.

## What Ali does

One command, then live your evening. Leave it running as long as you like;
Ctrl+C when you're done.

```
.venv\Scripts\python.exe voice/listen_wakeword.py --seconds 0 --log
```

Then say "read the wake word log" to an agent. Nothing else.

**What it records:** a timestamp and a score, per firing. Nothing else. No
audio is captured, buffered, or written — see the module docstring. The log
lives in `voice/logs/`, which is gitignored.

Worth doing at least once at `--threshold 0.3` too, on a separate evening: if
0.3 is quiet enough in his room, the wake word gets noticeably easier to
trigger from across the room.

## What an agent does afterwards

```
.venv\Scripts\python.exe voice/listen_wakeword.py --summary
```

## Results

Fill in per session. Empty until Ali runs one.

| date | hours | threshold | detections | per hour | Ali's read |
|---|---|---|---|---|---|
| _pending_ | | | | | |

`Ali's read` is the column an agent cannot fill: of the firings logged, how
many were him actually saying it? A session where he said it twice and it
logged two is a clean sheet; two said and nine logged is seven false
positives.

## How to read the number

Rough decision line, to be argued with rather than obeyed:

- **Under ~1/hour** — usable as-is. Ship `0.5`, skip `wakeword-train`.
- **1–5/hour** — try `0.3` and `0.7` on separate evenings before training
  anything; the threshold may be the whole story.
- **Over ~5/hour** — the pretrained model is not good enough for always-on in
  this room. Either train on his clips, or make push-to-talk the only input,
  which blueprint §5 already calls the default anyway.

That last option matters: §5 says push-to-talk (a remapped Copilot key) is the
default input and always-on is opt-in. So a bad false-positive rate does not
block the desk loop. It decides whether always-on is offered at all.

## Verification of the tooling itself

Two real sessions on this machine, 2 Sep 2026, cited in the task's Log: the
microphone opened, openWakeWord scored real frames, the log was written and
read back, and `--summary` aggregated both sessions with their different
thresholds. 20 tests cover the log format, the summary maths, the
footer-on-Ctrl+C, and the truncated-final-line case.
