"""Report what is actually inside a ``.flp``, so a sorting convention can be
dictated against real content instead of guessed at.

This is the read-only half of ``flp-real-mixer-convention`` (blueprint 2.1). It
never writes to a project, never writes to disk at all, and never guesses what
"sorted" means. It answers one question: what clips are in here, what does each
one appear to be, and which playlist track is it on right now.

Two findings from 29 Aug 2026 make this possible on real projects, both proved
against ``test_projects/spaceship demo.flp``:

- **Sample paths are readable from raw events.** PyFLP's ``Channel`` iteration
  raises ``IndexError`` on that project (``docs/state.md`` open blocker 4,
  ``channel.py:1586``, a channel referencing a group number PyFLP's own
  ``groups`` list does not contain). Reading ``ChannelID.SamplePath`` off the
  event stream never touches channel grouping, so it works anyway.
- **Playlist placement is readable the same way.** ``Arrangement.tracks``
  iterates channels and so hits the same bug; the raw ``ArrangementID.Playlist``
  event does not.

Classification here is deliberately shallow and honest. It reports the evidence
that produced each guess and marks anything it cannot place as ``unknown``
rather than forcing it into a bucket. **It does not decide the convention.**
Blueprint 2.1 puts that with the user, and ``docs/blueprint.md`` §1.4's rule
applies by analogy: an agent cannot judge whether a call about the user's own
work is right.

Run under the pinned FLP interpreter, never the default venv::

    .venv311\\Scripts\\python.exe tools/flp_inspect.py test_projects/*.flp
    .venv311\\Scripts\\python.exe tools/flp_inspect.py test_projects --json

``.venv311`` is CPython 3.11.5 and must stay there: 3.11.6 backported the
empty-enum guard that breaks PyFLP. See ``docs/state.md``.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path

# The reverse index FL stores for playlist track placement. Track 0 is the
# topmost lane in the arrangement; a clip's stored value counts down from here.
# PyFLP applies the same constant in Arrangement.tracks for post-12.9.1 files.
PLAYLIST_TRACK_MAX_INDEX = 499

# Each rule is (label, compiled pattern, what the pattern is evidence of).
# Ordered: the first match wins, so put the specific ahead of the general.
#
# These are read off real projects, not invented. Every one of them is a guess
# about the user's habits and every one is his to correct.
_CLASSIFIERS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        # FL names a recording "<something>_<date> <time>_Insert <n>.wav". The
        # prefix is "untitled" on an unsaved project and the project name once
        # saved, so keying on "untitled" alone missed every take in a named
        # project -- 18 of them in babydon'tgetsomad.flp, all reported "unknown"
        # by the first version of this file. Key on the stamp, not the prefix.
        "vocal-take",
        re.compile(r"_\d{4}-\d{2}-\d{2}[ _]\d{2}-\d{2}-\d{2}_Insert[ _]?\d+", re.I),
        "FL recording stamp with an Insert number",
    ),
    (
        "drums",
        re.compile(r"[\\/](?:drums?|percussion)[\\/]", re.I),
        "sample pack folder named drums/percussion",
    ),
    (
        "drums",
        re.compile(r"\b(?:808|909|kick|snare|hi-?hat|clap|cymbal|tom|ride|crash)\b", re.I),
        "drum-part word in the filename",
    ),
    (
        "instrumental",
        re.compile(r"[\\/]Downloads[\\/]", re.I),
        "downloaded from outside the project",
    ),
)


@dataclass(frozen=True)
class Clip:
    """One playlist item, with where it sits and what it looks like."""

    track_index: int
    track_reverse_index: int
    position: int
    length: int
    kind: str
    evidence: str
    sample: str | None


@dataclass(frozen=True)
class ProjectReport:
    """Everything read out of one project. Read-only; nothing here was written.

    ``parsed`` means PyFLP read the file. ``recovered`` means it did not, and
    what follows came from :func:`recover_samples` walking the raw event
    stream instead — a strictly smaller set of facts. The two are separate
    fields rather than one status string because a caller that forgets to
    check gets ``parsed=False``, which is the safe reading.
    """

    path: str
    parsed: bool
    clip_count: int
    tracks_used: int
    clips: tuple[Clip, ...]
    samples_without_clip: tuple[str, ...]
    warnings: tuple[str, ...]
    recovered: bool = False
    channel_count: int | None = None


def classify(sample: str | None) -> tuple[str, str]:
    """Guess what a clip is from its sample path.

    Returns ``(kind, evidence)``. Anything unmatched comes back ``unknown`` with
    the reason, never forced into the nearest bucket -- a wrong confident label
    is worse here than an admitted gap, because the user is being asked to
    correct these by eye.
    """
    if not sample:
        return "unknown", "no sample path on this clip (pattern clip, or plugin)"
    for label, pattern, evidence in _CLASSIFIERS:
        if pattern.search(sample):
            return label, evidence
    return "unknown", "no rule matched this path"


def _samples_by_channel(project: object) -> dict[int, str]:
    """Map channel iid -> sample path, read off the raw event stream.

    Deliberately not ``project.channels``: that iteration raises ``IndexError``
    on real projects with channel groups (open blocker 4). The event stream
    carries the same data and never touches grouping. ``ChannelID.New`` opens
    each channel and carries its iid; the sample path follows within it.
    """
    from pyflp.channel import ChannelID

    samples: dict[int, str] = {}
    current: int | None = None
    for event in project.events:  # type: ignore[attr-defined]
        if event.id == ChannelID.New:
            current = int(event.value)
        elif event.id == ChannelID.SamplePath and current is not None:
            value = str(event.value)
            if value:
                samples[current] = value
    return samples


# --- reading a file PyFLP will not parse -------------------------------------
#
# PyFLP's parse() is all-or-nothing: one malformed event aborts the whole file.
# Two of Ali's 25 projects hit that, and both are otherwise structurally intact
# — a hand walk reaches EOF cleanly on each (2,273 and 1,819 events). Losing a
# whole project's sample list to one bad event is not honest degradation, so
# these two functions read what is legible directly.
#
# They deliberately take bytes, not a path or a PyFLP object. That keeps them
# pure, keeps PyFLP out of the import path, and lets the offline suite cover
# them on 3.12 with synthetic fixtures instead of real projects.

#: FLP's own event framing. The id band fixes the payload width: below 64 the
#: event carries one byte, below 128 two, below 192 four, and from 192 up a
#: varint length followed by that many bytes. Read off PyFLP's own parser
#: (``_events.py``), not guessed.
_ONE_BYTE_MAX = 64
_TWO_BYTE_MAX = 128
_FOUR_BYTE_MAX = 192

#: Event ids used by the recovery path, taken from PyFLP's enums at the
#: versions pinned here: ``ChannelID.New`` and ``ChannelID.SamplePath``.
CHANNEL_NEW_ID = 64
SAMPLE_PATH_ID = 196

#: FL writes text events as UTF-16-LE from FL 12 onwards.
_TEXT_ENCODING = "utf-16-le"


def walk_events(data: bytes) -> "list[tuple[int, bytes]]":
    """Split an ``.flp``'s event chunk into ``(event_id, payload)`` pairs.

    Stops cleanly at the first sign of a truncated or malformed frame rather
    than raising: the whole point of this function is being handed files that
    are already broken somewhere. A caller gets everything up to the damage.
    """
    start = data.find(b"FLdt")
    if start < 0:
        return []

    events: list[tuple[int, bytes]] = []
    pos, end = start + 8, len(data)
    while pos < end:
        event_id = data[pos]
        pos += 1
        if event_id < _ONE_BYTE_MAX:
            size = 1
        elif event_id < _TWO_BYTE_MAX:
            size = 2
        elif event_id < _FOUR_BYTE_MAX:
            size = 4
        else:
            size, shift, complete = 0, 0, False
            while pos < end:
                byte = data[pos]
                pos += 1
                size |= (byte & 0x7F) << shift
                if not byte & 0x80:
                    complete = True
                    break
                shift += 7
            if not complete:
                break  # varint ran off the end
        if pos + size > end:
            break  # payload claims more bytes than the file has
        events.append((event_id, data[pos : pos + size]))
        pos += size
    return events


def recover_samples(data: bytes) -> "tuple[dict[int, str], int]":
    """Sample paths by channel iid, and the channel count, from raw bytes.

    The salvage path for a file PyFLP refuses. Returns strictly less than a
    real parse does — no playlist, so no clips, no track layout — which is why
    every caller labels the result as recovered rather than folding it in
    silently.
    """
    samples: dict[int, str] = {}
    channels = 0
    current: int | None = None
    for event_id, payload in walk_events(data):
        if event_id == CHANNEL_NEW_ID:
            channels += 1
            current = int.from_bytes(payload, "little")
        elif event_id == SAMPLE_PATH_ID and current is not None:
            try:
                text = payload.decode(_TEXT_ENCODING).rstrip("\0")
            except UnicodeDecodeError:
                continue  # one unreadable path must not cost the others
            if text:
                samples[current] = text
    return samples, channels


_PLAYLIST_SIZE = re.compile(r"event size (\d+) is not a multiple of struct size")

#: The stride every playlist event PyFLP 2.2.1 rejects turns out to be a
#: multiple of. Measured across all 195 ``.flp`` copies on this machine: 26
#: files carry a playlist event divisible by neither 32 nor 60 (the two sizes
#: PyFLP knows), and every one of them divides by 80. See
#: docs/tasks/pyflp-parse-failures-report.md.
UNKNOWN_PLAYLIST_STRIDE = 80


def _playlist_diagnosis(parser_warnings: "list[str]") -> str | None:
    """Turn PyFLP's playlist complaint into something actionable, or None."""
    for message in parser_warnings:
        match = _PLAYLIST_SIZE.search(message)
        if not match:
            continue
        size = int(match.group(1))
        if size % UNKNOWN_PLAYLIST_STRIDE == 0:
            return (
                f"playlist unreadable: PyFLP 2.2.1 knows 32- and 60-byte playlist "
                f"items, this file's event is {size} bytes, which is "
                f"{size // UNKNOWN_PLAYLIST_STRIDE} items at {UNKNOWN_PLAYLIST_STRIDE} "
                f"bytes each. Clips are NOT reported for this project."
            )
        return (
            f"playlist unreadable: event is {size} bytes, a multiple of no known "
            f"item stride (32, 60, or {UNKNOWN_PLAYLIST_STRIDE}). Clips are NOT "
            f"reported for this project."
        )
    return None


def inspect_project(path: Path) -> ProjectReport:
    """Parse one ``.flp`` and report its contents. Never writes to ``path``."""
    import pyflp
    from pyflp.arrangement import ArrangementID

    caught: list[str] = []
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        try:
            project = pyflp.parse(path)
        except Exception as exc:  # noqa: BLE001 - salvage rather than lose the file
            return _recovered_report(path, exc, [str(w.message) for w in captured])
        caught = [str(w.message) for w in captured]

    samples = _samples_by_channel(project)

    clips: list[Clip] = []
    notes: list[str] = []
    for arrangement in project.arrangements:
        if ArrangementID.Playlist not in arrangement.events.ids:
            continue
        playlist = arrangement.events.first(ArrangementID.Playlist)
        try:
            items = list(playlist)
        except AttributeError:
            # PyFLP refused to parse this playlist event and left the object
            # without its data, so iterating raises. Losing the clips is
            # unavoidable; losing the sample list with them is not. Say
            # exactly what was dropped and carry on.
            notes.append(
                _playlist_diagnosis(caught)
                or "playlist unreadable: PyFLP parsed no items from the playlist event."
            )
            continue
        for item in items:
            item_index = int(item["item_index"])
            pattern_base = int(item["pattern_base"])

            # PyFLP's own rule (arrangement.py, Arrangement.tracks): at or below
            # the base it addresses a channel by iid, above it a pattern. The
            # raw event stream also carries padding rows that satisfy neither --
            # they have pattern_base 0 and an item_index matching no channel.
            # Including those is what made the first version of this tool report
            # 25 clips in a project that has 5, and label padding as vocal takes.
            if pattern_base == 0:
                continue

            if item_index <= pattern_base:
                sample = samples.get(item_index)
                if sample is None:
                    continue
                kind, evidence = classify(sample)
            else:
                sample = None
                kind = "pattern"
                evidence = f"pattern clip #{item_index - pattern_base}, not an audio clip"

            reverse = int(item["track_rvidx"])
            track_index = PLAYLIST_TRACK_MAX_INDEX - reverse
            if track_index < 0:
                # Seen on pattern clips in babydon'tgetsomad_2.flp: rvidx above
                # the 499 base yields a negative lane, which cannot be a real
                # track. The reverse-index rule evidently does not apply to
                # these rows. Skip rather than report a track that isn't there.
                continue
            clips.append(
                Clip(
                    track_index=track_index,
                    track_reverse_index=reverse,
                    position=int(item["position"]),
                    length=int(item["length"]),
                    kind=kind,
                    evidence=evidence,
                    sample=sample,
                )
            )

    paired = {clip.sample for clip in clips if clip.sample}
    orphans = tuple(v for v in samples.values() if v not in paired)

    return ProjectReport(
        path=str(path),
        parsed=True,
        clip_count=len(clips),
        tracks_used=len({clip.track_index for clip in clips}),
        clips=tuple(clips),
        samples_without_clip=orphans,
        warnings=tuple(notes) + tuple(caught),
        channel_count=len(samples) or None,
    )


def _recovered_report(
    path: Path, exc: BaseException, parser_warnings: "list[str]"
) -> ProjectReport:
    """What can still be read once PyFLP has given up on the file."""
    samples, channels = recover_samples(path.read_bytes())
    note = (
        f"PyFLP could not parse this project ({type(exc).__name__}: {exc}). "
        f"Read the raw event stream instead and recovered {len(samples)} sample "
        f"path(s) across {channels} channel(s). NO playlist, NO clips, NO track "
        f"layout -- one malformed event aborts PyFLP's parse, so everything that "
        f"needs its object model is missing from this report."
    )
    return ProjectReport(
        path=str(path),
        parsed=False,
        clip_count=0,
        tracks_used=0,
        clips=(),
        samples_without_clip=tuple(samples.values()),
        warnings=(note,) + tuple(parser_warnings),
        recovered=True,
        channel_count=channels,
    )


_INSERT = re.compile(r"_Insert[ _]?(\d+)", re.I)


def insert_number(sample: str | None) -> int | None:
    """The mixer insert a recording was captured on, from its filename.

    Takes sharing an insert are the same vocal layer -- the strongest grouping
    signal in the real projects, and the one that survives the fact that clip
    positions move around.
    """
    if not sample:
        return None
    match = _INSERT.search(sample)
    return int(match.group(1)) if match else None


def _shorten(sample: str | None, width: int = 52) -> str:
    if not sample:
        return "-"
    name = Path(sample).name
    return name if len(name) <= width else "..." + name[-(width - 3) :]


def render(report: ProjectReport) -> str:
    """Human-readable summary. The tail end is what the user actually reads."""
    lines = [
        "",
        f"=== {Path(report.path).name} ==="
        + ("   [RECOVERED -- PyFLP could not parse this file]" if report.recovered else ""),
    ]
    if report.recovered:
        # Never print a clip count for a recovered file. Zero clips here means
        # "not readable", not "this project has no clips", and the two must
        # never look the same in output Ali is reading by eye.
        lines.append(
            f"partial read: {report.channel_count or 0} channels, "
            f"{len(report.samples_without_clip)} sample paths, no playlist"
        )
    else:
        lines.append(f"{report.clip_count} clips across {report.tracks_used} playlist tracks")
    lines.append("")

    if report.clips:
        lines.append(f"{'track':>6}  {'kind':<13}  {'pos':>8}  sample")
        lines.append(f"{'-' * 6}  {'-' * 13}  {'-' * 8}  {'-' * 52}")
        for clip in sorted(report.clips, key=lambda c: (c.track_index, c.position)):
            lines.append(
                f"{clip.track_index:>6}  {clip.kind:<13}  {clip.position:>8}  {_shorten(clip.sample)}"
            )

    counts: dict[str, int] = {}
    for clip in report.clips:
        counts[clip.kind] = counts.get(clip.kind, 0) + 1
    if counts:
        lines.append("")
        lines.append("  by kind: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    # Layout by kind is the whole point: it is the evidence for or against a
    # "instrumental on top, drums below, vocals under that" convention.
    by_kind: dict[str, set[int]] = {}
    for clip in report.clips:
        by_kind.setdefault(clip.kind, set()).add(clip.track_index)
    if by_kind:
        lines.append("  tracks per kind:")
        for kind, tracks in sorted(by_kind.items()):
            lines.append(f"    {kind:<13} -> tracks {sorted(tracks)}")

    inserts: dict[int, int] = {}
    for clip in report.clips:
        number = insert_number(clip.sample)
        if number is not None:
            inserts[number] = inserts.get(number, 0) + 1
    if inserts:
        lines.append("  recordings per mixer insert: " + ", ".join(
            f"Insert {k}={v}" for k, v in sorted(inserts.items())
        ))

    if report.samples_without_clip:
        lines.append("")
        label = (
            "samples recovered from the raw event stream"
            if report.recovered
            else "samples not paired to a clip"
        )
        lines.append(f"  {len(report.samples_without_clip)} {label}:")
        for sample in report.samples_without_clip[:10]:
            lines.append(f"    {_shorten(sample)}")

    if report.warnings:
        lines.append("")
        lines.append("  parser warnings:")
        for warning in dict.fromkeys(report.warnings):
            lines.append(f"    {warning}")

    return "\n".join(lines)


def discover(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        candidate = Path(raw)
        if candidate.is_dir():
            # FL saves projects as a folder (the .flp plus Audio/, Backup/...),
            # so recurse. Backup/ holds prior autosaves of the same song and
            # would double-count every project.
            found.extend(
                sorted(
                    f
                    for f in candidate.rglob("*.flp")
                    if "backup" not in {part.lower() for part in f.parts}
                )
            )
        elif candidate.exists():
            found.append(candidate)
        else:
            print(f"skipped, not found: {candidate}", file=sys.stderr)
    return found


def main(argv: list[str] | None = None) -> int:
    # Sample paths come out of Ali's own filesystem and routinely carry
    # characters cp1252 cannot encode. Without this the tool dies printing a
    # filename rather than reporting it.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Report the contents of one or more .flp projects. Read-only."
    )
    parser.add_argument("paths", nargs="+", help=".flp files, or directories to scan")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args(argv)

    projects = discover(args.paths)
    if not projects:
        print("no .flp files found", file=sys.stderr)
        return 1

    reports: list[ProjectReport] = []
    for path in projects:
        try:
            reports.append(inspect_project(path))
        except Exception as exc:  # noqa: BLE001 - report and continue, never abort the batch
            print(f"FAILED to read {path.name}: {type(exc).__name__}: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps([asdict(r) for r in reports], indent=2))
    else:
        for report in reports:
            print(render(report))

    # A recovered file is a real result, not a failure -- but it is also not a
    # clean read, and a batch that quietly exits 0 over one would be the silent
    # narrowing this tool is not allowed to do. Say it on stderr and keep the
    # exit code honest.
    recovered = [r for r in reports if r.recovered]
    if recovered:
        print(
            f"\n{len(recovered)} of {len(projects)} project(s) were recovered from the raw "
            "event stream, not parsed. Their clips and track layout are missing:",
            file=sys.stderr,
        )
        for report in recovered:
            print(f"  {Path(report.path).name}", file=sys.stderr)

    if len(reports) != len(projects):
        return 1
    return 2 if recovered else 0


if __name__ == "__main__":
    raise SystemExit(main())
