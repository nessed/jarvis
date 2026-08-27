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
