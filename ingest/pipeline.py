"""Deterministic, local-only preparation for explicitly selected corpora.

Nothing in this module sends data anywhere or discovers files outside the
intake directory the caller explicitly supplies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable


SUPPORTED_SUFFIXES = frozenset({".txt", ".md", ".markdown"})
DEFAULT_INTAKE_DIR = Path("ingest/data")
WHATSAPP_LINE = re.compile(
    r"^(?:\[(?P<bracket_timestamp>[^\]]+)\]\s+|"
    r"(?P<plain_timestamp>\d{1,4}[/-]\d{1,2}[/-]\d{1,4},?\s+.+?)\s+-\s+)"
    r"(?P<sender>[^:]+):\s*(?P<text>.*)$"
)


@dataclass(frozen=True)
class IngestManifest:
    """A stable description of one locally selected corpus file."""

    path: str
    source_type: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class Chunk:
    """Prepared text. ``index`` is stable for an unchanged source file."""

    source: str
    source_type: str
    index: int
    text: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class BackfillCheckpoint:
    """Serializable progress marker, advanced only after a chunk is persisted."""

    manifest_sha256: str
    next_chunk_index: int = 0
    updated_at: str = ""

    @classmethod
    def start(cls, manifest: IngestManifest) -> "BackfillCheckpoint":
        return cls(manifest_sha256=manifest.sha256, updated_at=_now())

    def advance(self, completed_chunk_index: int) -> "BackfillCheckpoint":
        if completed_chunk_index < self.next_chunk_index:
            raise ValueError("checkpoint cannot move backwards")
        return BackfillCheckpoint(
            manifest_sha256=self.manifest_sha256,
            next_chunk_index=completed_chunk_index + 1,
            updated_at=_now(),
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> "BackfillCheckpoint":
        data = json.loads(value)
        return cls(
            manifest_sha256=str(data["manifest_sha256"]),
            next_chunk_index=int(data.get("next_chunk_index", 0)),
            updated_at=str(data.get("updated_at", "")),
        )


def discover_intake(intake_dir: Path = DEFAULT_INTAKE_DIR) -> list[Path]:
    """Return only supported files directly placed beneath the opted-in folder."""
    if not intake_dir.exists():
        return []
    if not intake_dir.is_dir():
        raise ValueError("intake path must be a directory")
    return sorted(
        (path for path in intake_dir.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES),
        key=lambda path: path.as_posix().lower(),
    )


def build_manifest(path: Path, *, intake_dir: Path) -> IngestManifest:
    """Build a manifest only when ``path`` is within the caller's intake root."""
    root = intake_dir.resolve()
    candidate = path.resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("source file must be inside the selected intake directory") from exc
    if not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("source file must be a supported regular file")
    raw = candidate.read_bytes()
    return IngestManifest(
        path=relative.as_posix(),
        source_type=_source_type(candidate, raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )


def chunk_file(path: Path, manifest: IngestManifest, *, max_tokens: int = 500) -> list[Chunk]:
    """Normalize and deterministically chunk one manifest-matched local file."""
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest.sha256:
        raise ValueError("source changed since manifest creation")
    text = _normalize(raw.decode("utf-8-sig", errors="replace"))
    if manifest.source_type == "whatsapp_export":
        return _whatsapp_chunks(text, manifest)
    return _note_chunks(text, manifest, max_tokens)


def _source_type(path: Path, raw: bytes) -> str:
    normalized = _normalize(raw.decode("utf-8-sig", errors="replace"))
    if path.suffix.lower() == ".txt" and any(WHATSAPP_LINE.match(line) for line in normalized.splitlines()):
        return "whatsapp_export"
    return "note"


def _normalize(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.strip() for line in value.split("\n")).strip()


def _note_chunks(text: str, manifest: IngestManifest, max_tokens: int) -> list[Chunk]:
    words = text.split()
    if not words:
        return []
    return [
        Chunk(manifest.path, manifest.source_type, index, " ".join(words[start : start + max_tokens]), {})
        for index, start in enumerate(range(0, len(words), max_tokens))
    ]


def _whatsapp_chunks(text: str, manifest: IngestManifest) -> list[Chunk]:
    chunks: list[Chunk] = []
    current: dict[str, str] | None = None
    continuation: list[str] = []
    for line in text.splitlines():
        match = WHATSAPP_LINE.match(line)
        if match:
            if current and current["text"]:
                chunks.append(_chat_chunk(manifest, len(chunks), current, continuation))
            current = {
                "timestamp": match.group("bracket_timestamp") or match.group("plain_timestamp") or "",
                "sender": match.group("sender"),
                "text": match.group("text"),
            }
            continuation = []
        elif current and line:
            continuation.append(line)
    if current and current["text"]:
        chunks.append(_chat_chunk(manifest, len(chunks), current, continuation))
    return chunks


def _chat_chunk(manifest: IngestManifest, index: int, message: dict[str, str], continuation: Iterable[str]) -> Chunk:
    body = " ".join([message["text"], *continuation]).strip()
    return Chunk(
        manifest.path,
        manifest.source_type,
        index,
        body,
        {"sender": message["sender"].strip(), "timestamp": message["timestamp"].strip()},
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
