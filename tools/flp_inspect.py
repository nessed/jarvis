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
    """Everything read out of one project. Read-only; nothing here was written."""

    path: str
    parsed: bool
    clip_count: int
    tracks_used: int
    clips: tuple[Clip, ...]
    samples_without_clip: tuple[str, ...]
    warnings: tuple[str, ...]


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


def inspect_project(path: Path) -> ProjectReport:
    """Parse one ``.flp`` and report its contents. Never writes to ``path``."""
    import pyflp
    from pyflp.arrangement import ArrangementID

    caught: list[str] = []
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        project = pyflp.parse(path)
        caught = [str(w.message) for w in captured]

    samples = _samples_by_channel(project)

    clips: list[Clip] = []
    for arrangement in project.arrangements:
        if ArrangementID.Playlist not in arrangement.events.ids:
            continue
        playlist = arrangement.events.first(ArrangementID.Playlist)
        for item in playlist:
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
        warnings=tuple(caught),
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
        f"=== {Path(report.path).name} ===",
        f"{report.clip_count} clips across {report.tracks_used} playlist tracks",
        "",
    ]

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
        lines.append(f"  {len(report.samples_without_clip)} samples not paired to a clip:")
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

    return 0 if len(reports) == len(projects) else 1


if __name__ == "__main__":
    raise SystemExit(main())
