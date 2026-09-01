# PyFLP crashes reading channels on a real project with channel groups (27 August 2026)

Distinct from `docs/blockers/pyflp-python-312.md`, which is resolved. That
blocker was the interpreter (3.12, and 3.11.6+) rejecting PyFLP's empty
`EventEnum` before any parsing could happen. This one is different: parsing
starts, gets partway through the file, and PyFLP's own channel-grouping code
raises on a real-world project. `.venv311` is pinned to CPython 3.11.5 and that
part of the earlier fix is confirmed still working — this is a new,
independent failure.

## Reproduction

```
.venv311\Scripts\python.exe -c "
import pyflp
p = pyflp.parse(r'C:\Users\Ali\Desktop\jarvis\test_projects\spaceship demo.flp')
print(p.title)
list(p.channels)
"
```

Interpreter: CPython 3.11.5, `.venv311`. PyFLP: `2.2.1`.

File: `test_projects\spaceship demo.flp`, a real user project (not the
synthetic PyFLP fixture the earlier blocker used). Gitignored, never leaves
this machine, not attached here.

## Failure

A warning fires first, before the crash:

```
RuntimeWarning: VSTPluginEvent: Unknown marker 12 detected. Open an issue at
https://github.com/demberto/PyFLP/issues if you are seeing this!
```

`p.title` returns `None` — the project has no title set, not a parse failure
on its own. Iterating `p.channels` then raises:

```
Traceback (most recent call last):
  File "<string>", line 7, in <module>
  File "...\.venv311\Lib\site-packages\pyflp\channel.py", line 1586, in __iter__
    cur_ch = ch_dict[iid] = ct(et, channels=ch_dict, group=groups[groupnum])
                                                           ~~~~~~^^^^^^^^^^
IndexError: list index out of range
```

`channel.py:1586` indexes a `groups` list by `groupnum` read from the file's
own channel-group event data. This project's channel(s) reference a group
number that PyFLP's `groups` list — built earlier in the same parse — does not
contain an entry for. Not investigated further: whether that means the file
has more channel groups than PyFLP expects, a grouping feature PyFLP doesn't
model, or an off-by-one in PyFLP's own group-index bookkeeping.

## What was already tried

Nothing yet — reproduced once, not twice, and logged immediately on the user's
request rather than retried blind. The known-good synthetic fixture
(`FL 20.8.4.flp`, used to resolve the 3.12 blocker) has no channel groups and
does not exercise this path, which is presumably why it parsed clean.

## Consequence for Phase 2

`executor/flp/sort.py` still cannot be exercised against a real project. The
3.11.5 interpreter fix was necessary but not sufficient — PyFLP itself has a
gap on at least one real-world file shape (grouped channels), separate from
the VST-plugin-marker warning, which may or may not be related.

## Single unblock

Not yet identified. Candidates to check next, in order of effort: whether this
is a known upstream PyFLP issue (search `demberto/PyFLP` issues for
"IndexError" and "groups"), whether the project's channel grouping can be
flattened in FL Studio before export as a workaround, or whether a patched
`channel.py` is warranted — the same kind of targeted fix Lane A already used
once for the interpreter side, not a reason to avoid it here, but a decision
for whoever picks this up rather than assumed.

---

## Update, 2 September 2026 — reproduced, understood, and worked around

Reproduced deliberately across every `.flp` copy on this machine, not once.
`spaceship demo.flp` still raises exactly as recorded above:

```
channels_iter  IndexError: list index out of range  @ channel.py:1586 in __iter__
```

**It is not the only failure of its kind.** `outroagain_2.flp` fails on the
same operation with a different exception:

```
channels_iter  KeyError: <ChannelID.Type: 21>  @ _events.py:505 in first
```

and `games_3.flp` raises `NoModelsFound` at `channel.py:1596` because that
project genuinely has no channels (53 events in total — it is an empty
project, not a damaged one). So `project.channels` has at least three distinct
ways to fail on real files, and the group `IndexError` is one of them.

### The consequence is smaller than it looked

Every channel fact this repo actually needs — the iid and the sample path —
is on the raw event stream, which never touches channel grouping.
`tools/flp_inspect.py` has read them that way since it was written
(`_samples_by_channel`), and it recovers the full set on all three projects:

| project | `project.channels` | channels off the event stream |
|---|---|---|
| `spaceship demo.flp` | `IndexError` | 22 |
| `outroagain_2.flp` | `KeyError` | 58 |
| `babydon'tgetsomad_8.flp` | 247 | 247 |

The last row is the control: where PyFLP's iteration works, the event stream
agrees with it exactly.

### So what is still blocked

Only what genuinely needs PyFLP's channel *objects* — anything reading a
channel's plugin state, volume, panning or group membership. Nothing in this
repo does today. `executor/flp/sort.py` works on the mixer, not on channels,
and it is exercised end to end against a real file by
`tests/flp/test_flp_real.py`.

### Still not done, deliberately

No guarded lookup was added around PyFLP's own `groups[groupnum]`, because
there is nothing to guard it *in* — the crash is inside PyFLP's `__iter__`,
and reaching it would mean patching the installed package. `agents.md` and
this task's rules both make that a component change and a stop-and-report, and
the event-stream route makes it unnecessary anyway.

The upstream write-up worth filing is in
`docs/tasks/pyflp-parse-failures-report.md`.

**Status: no longer blocking. Downgraded from a blocker to a known PyFLP
limitation with a working route around it.**
