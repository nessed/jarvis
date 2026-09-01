---
id: pyflp-parse-failures
status: done
lane: AUTO
priority: 2
phase: 2
blocked-on: none
files: tools/flp_inspect.py, tests/tools/test_flp_inspect.py, docs/blockers/pyflp-channel-groups-indexerror.md, docs/tasks/pyflp-parse-failures-report.md
resources: none (reads .flp copies only, .venv311 only)
---

# pyflp-parse-failures — diagnose the imperfect parses

## Goal

Of Ali's 25 real projects + 1 fixture: 17 parse clean, 7 partial, 2 fail
outright (`outroforest`, `prayon`). Additionally, one of the 17 "clean"
projects (`spaceship demo`) hits PyFLP's own `IndexError` in
channel-group code once channels are actually iterated — the audit tool
never iterated them (`channel.py:1586`,
`docs/blockers/pyflp-channel-groups-indexerror.md`). All read-path.
Diagnose; make `tools/flp_inspect.py` degrade informatively instead of
dying where that's honest to do.

## Rules

- `.venv311\Scripts\python.exe` only (3.11.5, never upgrade, never `py`).
- Copies in `test_projects/` only; originals never touched. Read-only —
  no writing half exists (see PARKED).
- Fixing PyFLP itself: a minimal local workaround **in our code** (e.g.
  catching/guarding around the group lookup in `flp_inspect.py`) is fine;
  vendoring or patching the installed PyFLP package is a component change
  — stop and report instead. An upstream issue write-up in the report is
  welcome.
- A partial parse must stay loud: report what was skipped, never silently
  narrow output.

## Steps

1. Reproduce each failure class against the copies; classify by exception
   and by what byte-level/event-level feature triggers it (the audit data
   in `docs/tasks/flp-audit-data.json` has the per-project notes).
2. For the channel-groups `IndexError`: determine whether a guarded lookup
   in our inspector recovers the rest of the file's data. If yes, guard +
   test with a synthetic fixture; update the blocker file to reflect it.
3. For `outroforest`/`prayon`: root-cause as far as evidence allows;
   document whether any read is salvageable.
4. Tests for every new guard path (28 exist in
   `tests/tools/test_flp_inspect.py`; follow their fixture pattern).
5. Report: `docs/tasks/pyflp-parse-failures-report.md` — per-project
   verdicts, what's now readable that wasn't, what stays unreadable & why.

## Verification

`.venv311` realflp/inspector tests green (cite exact command + output);
full main suite green.

## Done when

Report written, blocker file current, guards tested. Update the failure
counts in `docs/context.md` if they change.

## Log

**2 Sep 2026 — done.**

All four failure classes reproduced and root-caused. Two projects that were
unreadable are now partially readable; the seven "partial" ones now say
precisely what is missing instead of dying. Full write-up:

    docs/tasks/pyflp-parse-failures-report.md

### The seven PARTIAL projects: an 80-byte playlist stride

PyFLP 2.2.1 knows 32- and 60-byte playlist items. These files use 80.

Measured across all 195 `.flp` copies on this machine rather than inferred
from one file: 26 carry a playlist event divisible by neither 32 nor 60, and
every one of those divides by 80.

```
rejected event sizes: 80, 560, 2000, 2320, 3920, 5840, 8240, 10960, 13040,
                      14320, 15920, 16880, 18160, 18800, 19120, 19600, 20080, 20240
struct sizes that divide EVERY rejected size: [8, 10, 16, 20, 40, 80]
```

The item *count* is therefore recoverable even though the fields are not, and
the inspector now says so:

```
playlist unreadable: PyFLP 2.2.1 knows 32- and 60-byte playlist items, this
file's event is 8240 bytes, which is 103 items at 80 bytes each. Clips are NOT
reported for this project.
```

Decoding the clips would need the 80-byte field layout, which is documented
nowhere this lane could check. Guessing offsets in a tool whose whole premise
is not doing that was not on.

### The two hard failures are now partially readable

Both abort on a single malformed event while the rest of the file is intact —
a hand walk of the event framing reaches EOF cleanly on each (2,273 and 1,819
events).

- `outroforest`: the FL version event carries 89 bytes of binary where a
  dotted ASCII string belongs; PyFLP decodes it unguarded at
  `__init__.py:136` and dies before reading a channel.
- `prayon`: a text event with a **9-byte** payload — odd length, so it cannot
  be UTF-16 at all.

`pyflp.parse()` is all-or-nothing, so `flp_inspect` now falls back to walking
the stream itself:

```
.venv311\Scripts\python.exe tools/flp_inspect.py test_projects/sampled/outroforest__outroforest.flp

=== outroforest__outroforest.flp ===   [RECOVERED -- PyFLP could not parse this file]
partial read: 24 channels, 8 sample paths, no playlist

  8 samples recovered from the raw event stream:
    Kick (Ambjaay - Uno).wav
    Basic 808 Clap.wav
    ...
```

`prayon` likewise: 11 channels, 5 sample paths. The walker was cross-checked
against `spaceship demo.flp`, which PyFLP *can* parse — it recovers 22 sample
paths across 22 channels, matching PyFLP's own count exactly.

Kept loud, per the task's rule. A recovered project gets a `[RECOVERED]`
banner, **never prints a clip count** (zero clips would read as "this project
has none" rather than "unreadable"), labels its samples as recovered rather
than unpaired, and the CLI exits **2** — distinct from 0 and from 1.

### `project.channels` fails three ways, and none of them matter

| project | exception | where |
|---|---|---|
| `spaceship demo.flp` | `IndexError` | `channel.py:1586` in `__iter__` |
| `outroagain_2.flp` | `KeyError: <ChannelID.Type: 21>` | `_events.py:505` in `first` |
| `games_3.flp` | `NoModelsFound` | `channel.py:1596` in `__len__` |

The third is not a bug: `games_3.flp` has 53 events and no channels. It is an
empty project, and the audit's `PARTIAL` label for it is misleading.

The event stream gives the same facts on all of them — 22, 58, and a control
row (`babydon'tgetsomad_8.flp`) where PyFLP works and the two agree exactly at
247. `flp_inspect` has read channels that way since it was written.

**No guard was added around PyFLP's `groups[groupnum]`** (Step 2's question).
There is nowhere in our code to put one: the crash is inside PyFLP's own
`__iter__`, so reaching it means patching the installed package — a component
change and a stop-and-report under this task's own rules. The event-stream
route makes it unnecessary. `docs/blockers/pyflp-channel-groups-indexerror.md`
is updated and downgraded from a blocker to a known limitation with a route
around it.

### Tests

22 new, all pure byte fixtures built in the test file — no `.flp` is read and
PyFLP is never imported, so they run in the main 3.12 suite alongside the
existing 28. That is possible because `walk_events` and `recover_samples` take
`bytes` rather than a path or a PyFLP object.

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=<private> tests/tools/test_flp_inspect.py
50 passed in 0.15s
```

realflp suite, under the pinned 3.11.5 sandbox, with its intended fixture:

```
JARVIS_FLP_FIXTURE="test_projects/FL 20.8.4.flp" .venv311\Scripts\python.exe -m pytest -q -m realflp tests/flp
4 passed in 1.91s
```

Note for whoever runs that next: pointing `JARVIS_FLP_FIXTURE` at
`spaceship demo.flp` instead fails 2 of the 4, because that project's mixer
has no insert named `Master`. The test says so in its own assertion message.
It is a fixture-choice constraint, not a regression.

### Full offline suite

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=<private> --ignore=tests/voice/test_stt_fallback.py
1186 passed, 9 deselected, 10 warnings in 96.71s
```

`tests/voice/test_stt_fallback.py` is the `stt-groq-fallback` lane's untracked
work-in-progress, running in the same checkout. It is excluded above because
it is not this lane's and was mid-write; nothing this task touched is in it.

A private `--basetemp` was used throughout, for the reason recorded in
`phase4-prep`'s Log — the other lane has since fixed the shared-basetemp
hazard in `CLAUDE.md` and `.githooks/pre-commit`.

### Worth filing upstream, not filed

Three PyFLP issues are written up in the report, reproductions included, in
descending order of how likely they are to bite other people: the 80-byte
playlist stride, the half-constructed event object that turns a refused parse
into an `AttributeError` from `len()`, and the unguarded ASCII decode of the
version string. Opening issues on Ali's behalf is outward-facing and his call.

### Specified but not done

- **`docs/context.md` failure counts.** They are not in `context.md` — its
  hand-written section carries no FLP counts, and its status block is
  generated. Nothing to update there. `docs/state.md`'s FL Studio row does
  reference open blocker 4 and should be revised now that it is downgraded,
  but `docs/state.md` has been held by another lane for this whole session.
- **20 of the 26 audited projects have no copy left** under `test_projects/`.
  The four failure *classes* cover everything the audit recorded, but
  per-project verdicts for those 20 are inherited from the audit rather than
  re-verified. Originals were not read: the rules say copies only.
