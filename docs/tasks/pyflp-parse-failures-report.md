# PyFLP parse failures — diagnosed

2 September 2026. Read-only throughout: every file below was opened from a copy
under `test_projects/`, nothing was written to any `.flp`, and the writing half
stays unbuilt (see `PARKED.md`).

The audit that prompted this recorded 17 clean, 7 partial and 2 outright
failures across Ali's 25 projects plus one fixture. All four failure classes
are now reproduced, root-caused, and — except where PyFLP's own object model is
unavoidable — worked around inside `tools/flp_inspect.py`.

## Verdicts

| class | count | cause | now |
|---|---|---|---|
| clean | 17 | — | unchanged |
| playlist unreadable | 7 | PyFLP 2.2.1 does not know an **80-byte playlist item stride** | samples + a loud diagnosis; clips still unavailable |
| `channels` iteration | (cuts across) | three distinct PyFLP bugs on `project.channels` | never used; the event stream gives the same facts |
| parse aborts | 2 | one malformed event kills the whole file | **now readable** — samples recovered from raw bytes |

## 1. The seven "partial" projects: an 80-byte playlist stride

Every one of them warns and then dies the same way:

```
RuntimeWarning: Cannot parse event ArrangementID.Playlist as event size 8240
                is not a multiple of struct size(s) [32, 60]
AttributeError: 'PlaylistEvent' object has no attribute 'data'   @ __init__.py:1237 in __len__
```

PyFLP refuses the event, leaves the object without its `data` attribute, and
then `len()`/iteration raises on an object it handed back as if it were fine.

**The stride is 80 bytes.** Measured across all 195 `.flp` copies on this
machine, not inferred from one file. 26 of them carry a playlist event whose
size divides by neither 32 nor 60 — and every one of those 26 divides by 80:

```
rejected event sizes: 80, 560, 2000, 2320, 3920, 5840, 8240, 10960, 13040,
                      14320, 15920, 16880, 18160, 18800, 19120, 19600, 20080, 20240

struct sizes that divide EVERY rejected size: [8, 10, 16, 20, 40, 80]
```

80 is the only candidate in that list large enough to be a plausible playlist
item, and it is consistent with PyFLP's own progression (32 bytes pre-12.9.1,
60 bytes after). These projects were saved by a newer FL Studio that widened
the item again.

That makes the count recoverable even though the fields are not: `8240 / 80 =
103 items`. `flp_inspect` now says exactly that instead of dying:

```
playlist unreadable: PyFLP 2.2.1 knows 32- and 60-byte playlist items, this
file's event is 8240 bytes, which is 103 items at 80 bytes each. Clips are NOT
reported for this project.
```

**What is still lost:** the clips themselves — position, length, track lane.
Decoding those needs the 80-byte layout, which is not documented anywhere this
lane could check, and guessing offsets would produce confident wrong output in
a tool whose entire premise is not doing that. Sample paths are unaffected;
they come from channel events, not the playlist.

## 2. `project.channels` fails three different ways

Not one bug. Three, on three real projects:

| project | exception | where |
|---|---|---|
| `spaceship demo.flp` | `IndexError: list index out of range` | `channel.py:1586` in `__iter__` |
| `outroagain_2.flp` | `KeyError: <ChannelID.Type: 21>` | `_events.py:505` in `first` |
| `games_3.flp` | `NoModelsFound` | `channel.py:1596` in `__len__` |

The third is not a bug at all: `games_3.flp` has 53 events and no channels. It
is an empty project, and the audit's `PARTIAL` label for it is misleading —
PyFLP is correctly reporting that there is nothing there.

**None of this matters here**, which is the useful finding. Every channel fact
this repo needs is on the raw event stream, and reading it there never touches
grouping:

| project | `project.channels` | event stream |
|---|---|---|
| `spaceship demo.flp` | `IndexError` | 22 channels |
| `outroagain_2.flp` | `KeyError` | 58 channels |
| `babydon'tgetsomad_8.flp` | 247 | 247 |

The last row is the control: where PyFLP works, the two agree exactly.
`tools/flp_inspect.py` has read channels this way since it was written.
`docs/blockers/pyflp-channel-groups-indexerror.md` is updated and downgraded
from a blocker.

No guard was added around PyFLP's `groups[groupnum]` lookup, because there is
nowhere in our code to put one — the crash is inside PyFLP's own `__iter__`,
and reaching it would mean patching the installed package. That is a component
change and a stop-and-report under this task's rules, and the event-stream
route makes it unnecessary.

## 3. The two hard failures — both now partially readable

Both abort on a single malformed event, and both files are otherwise
structurally intact. A hand walk of the event framing reaches EOF cleanly on
each:

**`outroforest__outroforest.flp`** (182 KB, 2,273 events, clean to EOF)

```
UnicodeDecodeError: 'ascii' codec can't decode byte 0x93 in position 2
  pyflp/__init__.py:136 in parse
      parts = value.decode("ascii").rstrip("\0").split(".")
```

The FL version event (id 199) carries 89 bytes of binary data where a dotted
ASCII version string belongs — `b'n$\x93\xe6@\x00\x00\xc0...'`, and 0x93 is
indeed at position 2. PyFLP decodes it unguarded during header parsing, so it
dies before a single channel is read.

**`prayon__prayon.flp`** (66 KB, 1,819 events, clean to EOF)

```
StringError: cannot use encoding 'utf-16-le' to decode b'\x00\x00\x00@\x06\x00@\x02\x00'
  pyflp/_events.py:125 in __init__
      self.value = self.STRUCT.parse(data, **self._kwds)
```

A text event (id 192) with a **9-byte** payload. UTF-16 needs an even length,
so it cannot be a string at all — either the event is misframed in the file or
PyFLP has mistyped that id for this FL version.

### What was salvaged

`pyflp.parse()` is all-or-nothing, so one bad event costs the whole project.
`tools/flp_inspect.py` now falls back to walking the event stream itself:

```
=== outroforest__outroforest.flp ===   [RECOVERED -- PyFLP could not parse this file]
partial read: 24 channels, 8 sample paths, no playlist

=== prayon__prayon.flp ===   [RECOVERED -- PyFLP could not parse this file]
partial read: 11 channels, 5 sample paths, no playlist
```

Recovered paths are real and readable, e.g.
`...\artist drumkits\Kicks-A\Kick (Ambjaay - Uno).wav` and
`...\Songs\prayon\Samples\Missionary Travelers   Pray On My Child.mp3`.

The walker was cross-checked against `spaceship demo.flp`, which PyFLP *can*
parse: it recovers 22 sample paths across 22 channels, matching PyFLP's own
event-stream count exactly.

**Kept loud, per the task's rule.** A recovered project prints a `[RECOVERED]`
banner, never prints a clip count (zero clips would read as "this project has
none" rather than "unreadable"), labels its samples as recovered rather than
unpaired, names the exception, and lists what is missing. The CLI prints the
recovered files on stderr and exits **2** — distinct from 0 (clean) and 1 (a
file could not be read at all).

## Worth filing upstream

Three, in descending order of how likely they are to affect other people:

1. **Playlist item stride is 80 bytes in current FL Studio.** `PlaylistEvent`
   knows 32 and 60. Evidence: 26 real projects, every rejected event size
   divisible by 80. This is the one that silently costs users their whole
   playlist.
2. **A refused event leaves the object half-constructed.** When
   `PlaylistEvent` declines to parse it warns and returns an object with no
   `data`, so the caller gets an `AttributeError` from `len()` rather than a
   catchable parse error. Raising, or exposing an `unparsed` flag, would let
   callers degrade instead of crash.
3. **The version string is decoded as ASCII without a guard**
   (`__init__.py:136`). One project with a corrupt version event cannot be
   opened at all, when everything after it is intact.

Not filed from here — opening issues on Ali's behalf is outward-facing and his
call. The reproductions above are written so they can be pasted if he wants
them filed.

## Files this could not check

20 of the 26 audited projects no longer have copies under `test_projects/`;
only `FL 20.8.4`, `outroagain_2`, `babydon'tgetsomad` (two saves), `games`,
`spaceship demo`, `outroforest` and `prayon` remain. The four failure classes
above cover every *kind* of failure the audit recorded, but per-project
verdicts for the other 20 are inherited from the audit rather than re-verified.
Originals were not read: the task's rules say copies only.
