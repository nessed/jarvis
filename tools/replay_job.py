"""Replay a real job payload through the real handler, with only the outside faked.

The tool ``docs/scalability-review.md`` and the blueprint-drift audit both
recommend into the standard toolkit. It found all three live WhatsApp bugs by
hand before it existed as a script: take the payload Meta actually sent, run
the actual handler over it, and watch the decision trail instead of guessing
at it from a dead-lettered row.

What stays real: the dedup lookup, memory recall, provider routing,
transcription. What is faked: everything that leaves the machine or mutates
durable state -- the outbound WhatsApp sends, the typing cue, the
seen-message write, and (by default) memory writes and Kokoro synthesis.

    .venv\\Scripts\\python.exe -m tools.replay_job --payload-file payload.json
    .venv\\Scripts\\python.exe -m tools.replay_job --job-id 0f3c... --transcript "test"
    .venv\\Scripts\\python.exe -m tools.replay_job --payload-file voice.json --audio-file clip.ogg

Run it as a module: this imports ``executor``/``memory``/``router`` as
siblings, which only resolves with the repo root on ``sys.path``, as ``-m``
guarantees.

Two deliberate refusals
-----------------------

**A replay never marks a message as sent.** ``SeenMessageStore.mark_sent`` is
faked out entirely. Replaying a real message must not make the live executor
skip it afterwards.

**Dedup is reported, then bypassed.** The interesting replay is almost always
of a message that already got a reply -- that is what "reproduce the bug"
means here. Honouring dedup would make the handler return immediately and
print nothing. The verdict is still shown, and ``--respect-dedup`` restores
the production behaviour.

Resources: a real recall embeds through Ollama (claim ``ollama-embed``), and a
real route spends a provider call. ``--transcript`` and ``--audio-file`` keep
whisper-server out of the loop; nothing here ever needs the NPU.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.jobs import Job
from executor.handlers.whatsapp import build_whatsapp_webhook_handler

WHATSAPP_KIND = "whatsapp_webhook"


class ReplayError(RuntimeError):
    """Raised when a replay cannot be set up. Never raised by the handler itself."""


# ---------------------------------------------------------------------------
# Reading a job
# ---------------------------------------------------------------------------


class JobSource(Protocol):
    """Read one job row, without claiming it or changing its status."""

    def fetch(self, job_id: str) -> Job | None: ...


class SupabaseJobSource:
    """Read-only ``SELECT`` against the live queue. No claim, no status change.

    ``db/jobs.py`` has no public single-row read: ``status_of_job`` returns
    only the status column, and every other repository method mutates. Rather
    than widen a file this lane does not own, the read goes through the
    repository's client directly. The query is a plain select, so it cannot
    claim, complete, or fail anything. A public ``fetch_job`` on
    ``SupabaseJobsRepository`` would be the better home, and is named in this
    task's report.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> "SupabaseJobSource":
        from db.jobs import SupabaseJobsRepository

        return cls(SupabaseJobsRepository.from_env()._client)

    def fetch(self, job_id: str) -> Job | None:
        response = self._client.table("jobs").select("*").eq("id", job_id).limit(1).execute()
        rows = getattr(response, "data", None) or []
        if not rows:
            return None
        return Job.from_row(rows[0])


def job_from_payload_file(path: Path, *, kind: str) -> Job:
    """Build a synthetic ``Job`` around a payload read off disk.

    The queue columns a handler never reads are filled with obvious
    placeholders rather than plausible values, so a trail printed from a file
    is never mistaken for one printed from the live queue.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ReplayError(f"Could not read {path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReplayError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ReplayError(f"{path} must hold a JSON object, not {type(payload).__name__}.")
    return Job(
        id="replay-from-file",
        kind=kind,
        payload=dict(payload),
        status="replay",
        checkpoint={},
        run_after="",
        created_at="",
        updated_at="",
    )


# ---------------------------------------------------------------------------
# The trail
# ---------------------------------------------------------------------------


@dataclass
class ReplayTrail:
    """Everything one replay observed, in the order the handler did it."""

    job_id: str = ""
    kind: str = ""
    already_replied: bool | None = None
    typing_cue: bool = False
    downloaded_media: str | None = None
    transcript: str | None = None
    recall_query: str | None = None
    recall_hits: list[str] = field(default_factory=list)
    #: Every routed completion, in call order, as (task_profile, provider,
    #: model). There is more than one per message since the command
    #: classifier landed, and a trail that showed only the last would hide a
    #: whole routed call from the person reading it.
    routed_calls: list[tuple[str, str, str]] = field(default_factory=list)
    routed_provider: str | None = None
    routed_model: str | None = None
    reply: str | None = None
    sent_as: str | None = None
    synthesized_bytes: int | None = None
    memory_writes: list[tuple[str, str]] = field(default_factory=list)
    memory_writes_stored: bool = False


def render_trail(trail: ReplayTrail, *, respected_dedup: bool) -> str:
    """The decision trail as lines. Pure, so a test can assert on it."""
    lines = [f"job        {trail.job_id}  ({trail.kind})"]

    if trail.already_replied is None:
        lines.append("dedup      not reached")
    elif trail.already_replied:
        note = "handler stopped here" if respected_dedup else "bypassed for replay"
        lines.append(f"dedup      already replied to this message id -- {note}")
    else:
        lines.append("dedup      not seen before")

    lines.append(f"typing     {'cue sent (faked)' if trail.typing_cue else 'no cue'}")

    if trail.downloaded_media is not None:
        lines.append(f"media      {trail.downloaded_media}")
    if trail.transcript is not None:
        lines.append(f"transcript {trail.transcript!r}")

    if trail.recall_query is not None:
        lines.append(f"recall     {len(trail.recall_hits)} hit(s) for {trail.recall_query!r}")
        lines.extend(f"           - {hit}" for hit in trail.recall_hits)

    for index, (profile, provider, model) in enumerate(trail.routed_calls, start=1):
        which = "reply" if index == len(trail.routed_calls) else "pre-reply"
        lines.append(f"routed     #{index} {profile} -> {provider} / {model}  ({which})")
    if trail.reply is not None:
        lines.append(f"reply      {trail.reply!r}")
    if trail.sent_as is not None:
        lines.append(f"send       {trail.sent_as} -- faked, nothing left this machine")
    if trail.synthesized_bytes is not None:
        lines.append(f"synthesis  {trail.synthesized_bytes} bytes of OGG/Opus")

    if not trail.memory_writes:
        lines.append("remember   nothing written")
    else:
        stored = "stored" if trail.memory_writes_stored else "dropped (--memory-writes to store)"
        for role, text in trail.memory_writes:
            lines.append(f"remember   {role}: {text!r} -- {stored}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fakes for the outbound half
# ---------------------------------------------------------------------------


class RecordingSeenStore:
    """Reports the real dedup verdict and never writes.

    ``mark_sent`` is a no-op on purpose -- see the module docstring. Whether
    the verdict is *honoured* is the caller's choice, not this store's.
    """

    def __init__(self, trail: ReplayTrail, *, real_verdict: bool, respect: bool) -> None:
        self._trail = trail
        self._real_verdict = real_verdict
        self._respect = respect

    def has_sent(self, message_id: str) -> bool:
        self._trail.already_replied = self._real_verdict
        return self._real_verdict if self._respect else False

    def mark_sent(self, message_id: str) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> "RecordingSeenStore":
        return self

    def __exit__(self, *_: object) -> None:
        return None


class RecordingMemory:
    """Wraps a real ``ConversationMemory``: recall passes through, writes are gated."""

    def __init__(self, inner: Any, trail: ReplayTrail, *, write: bool) -> None:
        self._inner = inner
        self._trail = trail
        self._write = write
        trail.memory_writes_stored = write

    def recall(self, query: str, *, user_id: str, limit: int = 10) -> Any:
        hits = self._inner.recall(query, user_id=user_id, limit=limit)
        self._trail.recall_query = query
        self._trail.recall_hits = [
            text.strip()
            for text in (getattr(hit, "text", None) for hit in hits or [])
            if isinstance(text, str) and text.strip()
        ]
        return hits

    def remember_turn(self, text: str, *, user_id: str, role: str) -> Any:
        self._trail.memory_writes.append((role, text))
        if not self._write:
            return None
        return self._inner.remember_turn(text, user_id=user_id, role=role)

    def close(self) -> None:
        self._inner.close()

    def __enter__(self) -> "RecordingMemory":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

Completion = Callable[[str, Sequence[Mapping[str, Any]]], Any]
Transcriber = Callable[[bytes], str]
Synthesizer = Callable[[str], bytes]


def build_replay_handler(
    trail: ReplayTrail,
    *,
    open_real_memory: Callable[[], Any],
    real_dedup_verdict: Callable[[], bool],
    completion: Completion,
    respect_dedup: bool = False,
    memory_writes: bool = False,
    transcript_override: str | None = None,
    audio_override: bytes | None = None,
    synthesize: Synthesizer | None = None,
    transcribe: Transcriber | None = None,
) -> Callable[[Job], None]:
    """Assemble the real WhatsApp handler with only its outbound seams faked.

    ``write_memory=True`` is passed through deliberately: the gate lives in
    :class:`RecordingMemory` instead, so the trail can show the write the
    handler *attempted* even when it is being dropped. Turning the handler's
    own flag off would make a dropped write indistinguishable from a handler
    that never tried.
    """

    def open_memory() -> RecordingMemory:
        return RecordingMemory(open_real_memory(), trail, write=memory_writes)

    verdict = real_dedup_verdict()

    def open_seen() -> RecordingSeenStore:
        return RecordingSeenStore(trail, real_verdict=verdict, respect=respect_dedup)

    def complete(task_profile: str, messages: Sequence[Mapping[str, Any]]) -> Any:
        result = completion(task_profile, messages)
        provider = getattr(result, "provider", None)
        model = getattr(result, "model", None)
        # Every routed call, not just the last. The handler's command
        # classifier routes through this same seam, so a trail that recorded
        # only the final call would silently drop a provider call the reader
        # is paying for and may be debugging.
        trail.routed_calls.append((task_profile, str(provider), str(model)))
        trail.routed_provider = provider
        trail.routed_model = model
        return result

    def send_text(*, to: str, text: str) -> str:
        trail.reply = text
        trail.sent_as = f"text to {to}"
        return "replay-text"

    def send_voice(*, to: str, audio: bytes) -> str:
        trail.sent_as = f"voice note to {to}"
        return "replay-voice"

    def typing(*, message_id: str) -> None:
        trail.typing_cue = True

    def download(media_id: str) -> tuple[bytes, str]:
        if audio_override is None:
            raise ReplayError(
                f"This payload is a voice note (media {media_id}) and downloading it would "
                "hit the Graph API. Pass --audio-file to replay from a local clip, or "
                "--transcript to skip the audio entirely."
            )
        trail.downloaded_media = f"{len(audio_override)} bytes from --audio-file"
        return audio_override, "audio/ogg"

    def transcribe_audio(audio: bytes) -> str:
        if transcript_override is not None:
            trail.transcript = transcript_override
            return transcript_override
        if transcribe is None:
            raise ReplayError("No transcriber available. Pass --transcript.")
        text = transcribe(audio)
        trail.transcript = text
        return text

    def synthesize_reply(text: str) -> bytes:
        trail.reply = text
        if synthesize is None:
            return b""
        audio = synthesize(text)
        trail.synthesized_bytes = len(audio)
        return audio

    return build_whatsapp_webhook_handler(
        open_memory=open_memory,
        open_seen_messages=open_seen,
        complete=complete,
        send_text_message=send_text,
        show_typing_indicator=typing,
        download_media=download,
        transcribe_audio=transcribe_audio,
        synthesize_voice_reply=synthesize_reply,
        send_voice_note=send_voice,
        write_memory=True,
    )


def replay(job: Job, handler: Callable[[Job], None], trail: ReplayTrail) -> ReplayTrail:
    """Run the handler over the job and return the filled trail."""
    trail.job_id = job.id
    trail.kind = job.kind
    handler(job)
    return trail


# ---------------------------------------------------------------------------
# Defaults that touch the real system. Imported lazily, like the handler's own.
# ---------------------------------------------------------------------------


def _real_dedup_verdict(message_id: str | None) -> Callable[[], bool]:
    def check() -> bool:
        if message_id is None:
            return False
        from executor.handlers.whatsapp import open_default_seen_message_store

        with open_default_seen_message_store() as store:
            return store.has_sent(message_id)

    return check


def _real_completion(task_profile: str, messages: Sequence[Mapping[str, Any]]) -> Any:
    import asyncio

    from router import route

    return asyncio.run(route(task_profile, messages, urgent=True))


def _real_transcriber(audio: bytes) -> str:
    from voice.audio import to_transcribable_wav
    from voice.config import whisper_language
    from voice.whisper.server_client import WhisperServerClient

    return WhisperServerClient().transcribe(to_transcribable_wav(audio), language=whisper_language())


def _real_synthesizer(text: str) -> bytes:
    from voice.speak import text_to_voice_note

    return text_to_voice_note(text)


def _real_memory_opener() -> Any:
    from memory.conversation import open_conversation_memory

    return open_conversation_memory()


def _message_id_of(payload: Mapping[str, Any]) -> str | None:
    from executor.handlers.whatsapp import parse_inbound_message

    inbound = parse_inbound_message(payload)
    return None if inbound is None else inbound.message_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _force_utf8_output() -> None:
    """cp1252 is this machine's default and a recalled Urdu turn is not
    representable in it. Without this, printing a real trail dies with
    UnicodeEncodeError instead of showing the bug being chased."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay a job payload through the real handler with outbound sends faked."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--payload-file", type=Path, help="a captured payload, as JSON")
    source.add_argument("--job-id", help="read this job row from the live queue (read-only)")
    parser.add_argument(
        "--kind",
        default=WHATSAPP_KIND,
        help=f"job kind to replay (default: {WHATSAPP_KIND})",
    )
    parser.add_argument(
        "--respect-dedup",
        action="store_true",
        help="stop if the message was already replied to, as production would",
    )
    parser.add_argument(
        "--memory-writes",
        action="store_true",
        help="really store the turn; recall is real either way (claims ollama-embed)",
    )
    parser.add_argument(
        "--transcript",
        help="use this text instead of transcribing -- keeps whisper-server out of it",
    )
    parser.add_argument(
        "--audio-file",
        type=Path,
        help="replay a voice note from a local clip instead of downloading it from Meta",
    )
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help="really run Kokoro on a voice reply (default: report the text, skip synthesis)",
    )
    parser.add_argument(
        "--allow-side-effects",
        action="store_true",
        help="required for kinds other than whatsapp_webhook, whose handlers have no "
        "fakeable outbound seam and would really move files or drive apps",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except ReplayError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def run(args: argparse.Namespace, *, job_source: JobSource | None = None) -> int:
    """The CLI body, with the live-queue reader injectable for tests."""
    if args.kind != WHATSAPP_KIND:
        # Two separate refusals, and the order matters: the side-effect one is
        # about consent, and it is answered before anything is read.
        if not args.allow_side_effects:
            raise ReplayError(
                f"{args.kind!r} has no injectable outbound seam, so replaying it runs the "
                "real handler for real -- it can move files or drive apps. Pass "
                "--allow-side-effects if that is genuinely what you want."
            )
        raise ReplayError(
            f"Replaying {args.kind!r} is not wired yet. Only {WHATSAPP_KIND!r} has the "
            "injectable seams this tool fakes; the action kinds get producers in "
            "enqueue-classifier."
        )

    if args.payload_file is not None:
        job = job_from_payload_file(args.payload_file, kind=args.kind)
    else:
        source = job_source if job_source is not None else SupabaseJobSource.from_env()
        found = source.fetch(args.job_id)
        if found is None:
            raise ReplayError(f"No job with id {args.job_id}.")
        job = found

    audio = None
    if args.audio_file is not None:
        try:
            audio = args.audio_file.read_bytes()
        except OSError as exc:
            raise ReplayError(f"Could not read {args.audio_file}: {exc}") from exc

    trail = ReplayTrail()
    handler = build_replay_handler(
        trail,
        open_real_memory=_real_memory_opener,
        real_dedup_verdict=_real_dedup_verdict(_message_id_of(job.payload)),
        completion=_real_completion,
        respect_dedup=args.respect_dedup,
        memory_writes=args.memory_writes,
        transcript_override=args.transcript,
        audio_override=audio,
        synthesize=_real_synthesizer if args.synthesize else None,
        transcribe=_real_transcriber,
    )
    replay(job, handler, trail)
    print(render_trail(trail, respected_dedup=args.respect_dedup))
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
