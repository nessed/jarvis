"""Exclusion-pattern matching that keeps junk from becoming a stored fact.

Blueprint 1.4: "wrong or creepy facts -> you delete them and tell the agent
which pattern to exclude." This module is the mechanism only. It never
guesses what should be excluded -- patterns come from a plain config file
Ali edits himself, loaded by :func:`load_patterns`. The shipped config
(``ingest/noise_patterns.txt``) ships with its pattern list empty; populating
it is Ali's step, not this lane's.

The same :class:`ExclusionPattern` shape is used by ``ingest.pipeline`` (to
filter chunks before they are ever stored) and by ``memory.review`` (to
retroactively delete facts that already matched a pattern named after the
fact), so "stop remembering things like this" means the same thing on both
sides of the store.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

DEFAULT_PATTERNS_PATH = Path("ingest/noise_patterns.txt")

_KINDS = frozenset({"substring", "regex", "source"})


class NoisePatternError(ValueError):
    """Raised when a pattern config file or a single pattern spec is malformed."""


@dataclass(frozen=True)
class ExclusionPattern:
    """One user-authored rule. ``origin`` is where it came from, for error messages."""

    kind: str
    value: str
    origin: str

    def matches(self, *, text: str, source: str) -> bool:
        if self.kind == "substring":
            return self.value.lower() in text.lower()
        if self.kind == "regex":
            return re.search(self.value, text) is not None
        if self.kind == "source":
            return source == self.value
        raise NoisePatternError(f"unknown pattern kind: {self.kind!r}")

    @property
    def key(self) -> str:
        """A stable, human-readable label for counting/reporting exclusions."""
        return f"{self.kind}:{self.value}"


@dataclass(frozen=True)
class FilterOutcome:
    """The result of filtering a batch of chunks: what survived, and why the rest didn't.

    ``excluded_by_pattern`` is keyed by :attr:`ExclusionPattern.key` so a
    caller can report "excluded N chunk(s) by pattern X" per ``agents.md``'s
    "no silent cap" rule -- a filtered chunk is counted, never silently
    dropped.
    """

    kept: list
    excluded_by_pattern: dict[str, int]

    @property
    def excluded(self) -> int:
        return sum(self.excluded_by_pattern.values())


def load_patterns(path: Path | str = DEFAULT_PATTERNS_PATH) -> list[ExclusionPattern]:
    """Parse a pattern config file. A missing file means no patterns, not an error.

    Format, one active rule per line: ``<kind>:<value>`` where kind is one of
    ``substring``, ``regex``, ``source``. Blank lines and lines starting with
    ``#`` are ignored.
    """
    file_path = Path(path)
    if not file_path.exists():
        return []
    patterns: list[ExclusionPattern] = []
    for lineno, raw_line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(_parse_pattern(line, origin=f"{file_path}:{lineno}"))
    return patterns


def parse_pattern(spec: str) -> ExclusionPattern:
    """Parse one ``<kind>:<value>`` pattern spec given directly, e.g. from a CLI argument."""
    return _parse_pattern(spec.strip(), origin="<argument>")


def filter_chunks(chunks, patterns: list[ExclusionPattern]) -> FilterOutcome:
    """Split ``chunks`` (each carrying ``.text`` and ``.source``) by the first pattern that matches.

    A chunk matching more than one pattern is counted once, against whichever
    pattern is listed first -- patterns are meant to be disjoint noise rules,
    not a priority-ordered pipeline.
    """
    if not patterns:
        return FilterOutcome(kept=list(chunks), excluded_by_pattern={})
    kept = []
    excluded_by_pattern: dict[str, int] = {}
    for chunk in chunks:
        matched = next((p for p in patterns if p.matches(text=chunk.text, source=chunk.source)), None)
        if matched is None:
            kept.append(chunk)
        else:
            excluded_by_pattern[matched.key] = excluded_by_pattern.get(matched.key, 0) + 1
    return FilterOutcome(kept=kept, excluded_by_pattern=excluded_by_pattern)


def _parse_pattern(line: str, *, origin: str) -> ExclusionPattern:
    if ":" not in line:
        raise NoisePatternError(f"{origin}: expected '<kind>:<value>', got {line!r}")
    kind, _, value = line.partition(":")
    kind = kind.strip()
    value = value.strip()
    if kind not in _KINDS:
        raise NoisePatternError(f"{origin}: unknown pattern kind {kind!r}; expected one of {sorted(_KINDS)}")
    if not value:
        raise NoisePatternError(f"{origin}: pattern value must not be empty")
    if kind == "regex":
        try:
            re.compile(value)
        except re.error as exc:
            raise NoisePatternError(f"{origin}: invalid regex {value!r}: {exc}") from exc
    return ExclusionPattern(kind=kind, value=value, origin=origin)
