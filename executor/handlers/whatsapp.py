"""Blueprint step 1.4: cue -> recall -> route -> send -> remember for one inbound message.

Turns a claimed ``whatsapp_webhook`` job's raw Meta payload into a routed LLM
reply, sent back over the same client used everywhere else outbound
(``bus.whatsapp_client.WhatsAppClient``). Memory, routing, and sending are all
injectable so this can be unit-tested without Ollama, a live provider, or the
Graph API.

Blueprint 3.3's second half lives here too: "WhatsApp voice note -> transcript
-> bus -> action -> Kokoro reply". A voice note is downloaded, decoded, and
transcribed before it ever reaches recall/routing, so from that point on it is
indistinguishable from a typed message -- and the reply comes back the same
way it arrived, voice for voice, text for text. Downloading, transcribing, and
synthesizing are each injectable for the same reason send/complete already
were: no NPU, no Kokoro model, and no Graph API needed to test the wiring.

What is left here is the WhatsApp half only. Deciding what to say — classify,
recall, route — moved to :mod:`executor.conversation.service` on 8 September
2026 so the bus can run the same brain in-process on a rented box without
importing Meta's Graph client, sqlite paths or an audio stack. Dedup, the
typing cue, media download, STT, TTS, sending, and the ``notify`` descriptor
that tells the queue who is waiting all stay here, because all of them are
this channel's problem and nobody else's.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from bus.whatsapp_client import WhatsAppClient, WhatsAppClientConfig
from db.jobs import Job, enqueue
from executor.conversation.service import (
    SYSTEM_PROMPT,
    VOICE_REPLY_LANGUAGE_NOTE,
    ConversationService,
    LazyMemory,
)
from executor.handlers.command_intent import (
    CommandVerdict,
    PendingConfirmationStore,
    open_default_pending_confirmation_store,
    queued_reply,
)
from executor.handlers.outcome import WHATSAPP_OUTCOME_JOB_KIND
from executor.latency import ReplySpans
from executor.notify import NOTIFY_FIELD, notify_descriptor
from memory.conversation import ConversationMemory, open_conversation_memory
from router import RoutedResult, route_sync

logger = logging.getLogger(__name__)

# Re-exported: the prompt and the voice note moved to the channel-neutral
# service with the rest of the reply brain (executor/conversation/service.py).
# They stay importable from here because this module is where they have always
# been read from.
__all__ = [
    "SYSTEM_PROMPT",
    "VOICE_REPLY_LANGUAGE_NOTE",
    "InboundMessage",
    "SeenMessageStore",
    "build_whatsapp_webhook_handler",
    "commands_enabled",
    "memory_writes_enabled",
    "open_default_seen_message_store",
    "parse_inbound_message",
    "parse_inbound_text_message",
]


@dataclass(frozen=True)
class InboundMessage:
    """The one thing this handler needs out of a raw Meta webhook payload.

    Exactly one of ``text`` or ``audio_media_id`` is set. A text message has
    ``text`` and no media id; a voice note has ``audio_media_id`` and no text
    until :func:`build_whatsapp_webhook_handler`'s transcription step fills it
    in downstream — this dataclass itself never runs STT.
    """

    sender: str
    text: str | None
    message_id: str
    audio_media_id: str | None = None


def parse_inbound_message(payload: Mapping[str, Any]) -> InboundMessage | None:
    """Extract the first inbound text or voice-note message from a raw Meta webhook payload.

    Returns ``None`` for anything that is neither — delivery/read status
    callbacks, other message types (image, reaction, ...), and malformed or
    empty payloads are all silent no-ops, not errors, since Meta sends all of
    those to the same webhook.
    """
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for message in value.get("messages") or []:
                sender = message.get("from")
                message_id = message.get("id")
                if not sender or not message_id:
                    continue
                message_type = message.get("type")
                if message_type == "text":
                    text = (message.get("text") or {}).get("body")
                    if text:
                        return InboundMessage(sender=str(sender), text=str(text), message_id=str(message_id))
                elif message_type == "audio":
                    media_id = (message.get("audio") or {}).get("id")
                    if media_id:
                        return InboundMessage(
                            sender=str(sender),
                            text=None,
                            message_id=str(message_id),
                            audio_media_id=str(media_id),
                        )
    return None


def parse_inbound_text_message(payload: Mapping[str, Any]) -> InboundMessage | None:
    """Extract the first inbound *text* message only.

    Kept as its own entry point — narrower than :func:`parse_inbound_message`
    — because it predates the voice path and existing callers/tests depend on
    its text-only contract. Delegates to the shared parser so the two never
    disagree about what counts as a valid text message.
    """
    message = parse_inbound_message(payload)
    if message is None or message.text is None:
        return None
    return message


class SeenMessageStore:
    """Tracks which inbound WhatsApp message ids have already been replied to.

    Meta redelivers a webhook it didn't get a fast 200 for — a connectivity
    gap on the bus side, for instance — which enqueues the same message
    several times. This is checked before doing any work and updated only
    after a reply actually sends, so a *failed* attempt (routing error,
    timeout, ...) is never mistaken for "already handled" and still gets
    retried normally by the poller's own backoff.
    """

    def __init__(self, path: str | Path) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sent_replies (message_id TEXT PRIMARY KEY, sent_at TEXT NOT NULL)"
        )
        self._conn.commit()

    def has_sent(self, message_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sent_replies WHERE message_id = ?", (message_id,)
        ).fetchone()
        return row is not None

    def mark_sent(self, message_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO sent_replies (message_id, sent_at) VALUES (?, ?)",
            (message_id, datetime.now(UTC).isoformat()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SeenMessageStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_default_seen_message_store(*, environ: Mapping[str, str] | None = None) -> SeenMessageStore:
    """Open the seen-message store next to the configured memory database."""
    settings = os.environ if environ is None else environ
    path = Path(settings.get("MEMORY_DB_PATH", "memory.db")).with_suffix(".seen-messages.db")
    return SeenMessageStore(path)


MemoryOpener = Callable[[], ConversationMemory]
SeenStoreOpener = Callable[[], SeenMessageStore]
PendingStoreOpener = Callable[[], PendingConfirmationStore]
CommandClassifier = Callable[[str], CommandVerdict]


def _with_outcome_notice(
    payload: Mapping[str, Any], reply_to: str, summary: str
) -> dict[str, Any]:
    """The action payload, plus "and tell this person how it went".

    This is the only place that knows *who* is waiting, so it is the only
    place that can say so. Everything downstream — the action handlers and
    the poller's dead-letter path — reads a generic ``notify`` descriptor and
    never learns that WhatsApp is involved. See ``executor/notify.py``.

    The summary is carried so the outcome can quote the same words the user
    was already told ("On it: turn wifi off"), which is what makes the two
    messages read as one exchange. It is a phrase this system generated about
    an action it is about to take, not conversation text, so it may travel
    through the hosted queue.
    """
    return {
        **dict(payload),
        NOTIFY_FIELD: notify_descriptor(
            WHATSAPP_OUTCOME_JOB_KIND, {"reply_to": reply_to, "summary": summary}
        ),
    }
ActionEnqueuer = Callable[[str, Mapping[str, Any]], Job]
Completion = Callable[[str, Sequence[Mapping[str, Any]]], RoutedResult]
Sender = Callable[..., str]
TypingIndicator = Callable[..., None]
MediaDownloader = Callable[[str], tuple[bytes, str]]
AudioTranscriber = Callable[[bytes], str]
VoiceSynthesizer = Callable[[str], bytes]


def memory_writes_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Whether to persist conversation turns after replying.

    Default **on**. Writes were briefly disabled when they went through Mem0's
    8B fact extraction, which cost 20-130s and failed on 100% of live turns.
    They now go through :mod:`memory.conversation`, which only embeds and
    stores (~0.5s), so the reason for disabling them is gone. Extraction still
    happens, as a batch pass over the stored turns — see
    ``tools/distill_memory.py``.

    Set ``JARVIS_MEMORY_WRITES=0`` to turn them off again.
    """
    settings = os.environ if environ is None else environ
    return settings.get("JARVIS_MEMORY_WRITES", "1").strip().lower() in {"1", "true", "yes", "on"}


def commands_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Whether inbound messages may enqueue action jobs.

    Default **on**: Ali answered Q1 "yes, with the recommended per-kind
    allowlist" on 1 September 2026. ``JARVIS_WHATSAPP_COMMANDS=0`` turns the
    whole producer off in one place without touching the allowlist, which is
    what to reach for if the classifier ever starts misreading messages —
    replies keep working, actions simply stop being enqueued.
    """
    settings = os.environ if environ is None else environ
    return settings.get("JARVIS_WHATSAPP_COMMANDS", "1").strip().lower() in {"1", "true", "yes", "on"}


def build_whatsapp_webhook_handler(
    *,
    open_memory: MemoryOpener = open_conversation_memory,
    open_seen_messages: SeenStoreOpener = open_default_seen_message_store,
    complete: Completion | None = None,
    send_text_message: Sender | None = None,
    show_typing_indicator: TypingIndicator | None = None,
    download_media: MediaDownloader | None = None,
    transcribe_audio: AudioTranscriber | None = None,
    synthesize_voice_reply: VoiceSynthesizer | None = None,
    send_voice_note: Sender | None = None,
    write_memory: bool | None = None,
    open_pending_confirmations: PendingStoreOpener = open_default_pending_confirmation_store,
    classify: CommandClassifier | None = None,
    enqueue_action: ActionEnqueuer | None = None,
    handle_commands: bool | None = None,
) -> Callable[[Job], None]:
    """Return a plain ``JobHandler`` closure wiring cue -> service -> send -> remember.

    The middle of that chain — classify, recall, route — is
    :class:`executor.conversation.service.ConversationService`, built per
    message around the lazily-opened turn store. An action it proposes is
    enqueued here, not there, because only this layer knows a WhatsApp user is
    waiting on the outcome.

    Any raised exception (recall, routing, or send failure) propagates
    unchanged to the poller, which already retries/backs off/dead-letters it
    with a type-only diagnostic — this handler adds no error handling of its
    own on top of that. A message id already marked sent is a silent no-op,
    same as an unparseable payload; it is not an error either.

    ``write_memory`` defaults to ``memory_writes_enabled()``, which is **on**:
    ``JARVIS_MEMORY_WRITES`` is read with a default of ``"1"``, and only
    ``1``/``true``/``yes``/``on`` keep writes enabled, so setting it to
    anything else — ``0`` is the documented off switch — turns them off.
    ``recall()`` runs either way.
    """

    def _default_complete(task_profile: str, messages: Sequence[Mapping[str, Any]]) -> RoutedResult:
        return route_sync(task_profile, messages, urgent=True)

    # One Graph client for the life of this handler, built on first use.
    # Lazily, because DEFAULT_HANDLERS constructs this closure at import time,
    # before load_dotenv has run, so the token is not readable yet. Until
    # 4 Sep 2026 every cue, send, download and upload built its own client
    # and paid a fresh 1.0 s TLS handshake to graph.facebook.com — two per
    # text reply, four per voice reply. The client keeps one connection now.
    graph_client: list[WhatsAppClient] = []

    def _graph() -> WhatsAppClient:
        if not graph_client:
            graph_client.append(WhatsAppClient(WhatsAppClientConfig.from_environ()))
        return graph_client[0]

    def _default_send(*, to: str, text: str) -> str:
        return _graph().send_text_message(to=to, text=text)

    def _default_show_typing_indicator(*, message_id: str) -> None:
        _graph().show_typing_indicator(message_id=message_id)

    def _default_download_media(media_id: str) -> tuple[bytes, str]:
        return _graph().download_media(media_id=media_id)

    def _default_transcribe_audio(audio: bytes) -> str:
        # Imported here, not at module scope: this handler runs on every
        # WhatsApp message, most of which are text, and soundfile/httpx-heavy
        # voice imports have no business loading for those.
        #
        # Local NPU first, Groq second, never both (Q8 = A, 1 Sep 2026). A
        # dead whisper-server used to mean a spoken message got silence back;
        # it now gets a cloud transcript, and a total failure raises loudly
        # rather than passing for an empty clip. See voice/stt_fallback.py for
        # why an empty transcript is a result and not a reason to fall back.
        from voice.audio import to_transcribable_wav
        from voice.config import whisper_language
        from voice.stt_fallback import transcribe_with_fallback

        wav = to_transcribable_wav(audio)
        return transcribe_with_fallback(wav, language=whisper_language())

    def _default_synthesize_voice_reply(text: str) -> bytes:
        from voice.speak import text_to_voice_note

        return text_to_voice_note(text)

    def _default_send_voice_note(*, to: str, audio: bytes) -> str:
        return _graph().send_voice_note(to=to, audio=audio)

    completion = complete or _default_complete
    sender = send_text_message or _default_send
    typing_indicator = show_typing_indicator or _default_show_typing_indicator
    media_downloader = download_media or _default_download_media
    audio_transcriber = transcribe_audio or _default_transcribe_audio
    voice_synthesizer = synthesize_voice_reply or _default_synthesize_voice_reply
    voice_sender = send_voice_note or _default_send_voice_note
    write_memory = memory_writes_enabled() if write_memory is None else write_memory
    action_enqueuer = enqueue_action or (lambda kind, payload: enqueue(kind, dict(payload)))
    # Left as ``None`` when nothing was injected: the service's own default is
    # the same ``classify_command`` bound to the same completion callable.
    classifier = classify
    commands_on = commands_enabled() if handle_commands is None else handle_commands

    def _enqueue_proposal(proposal: Any, sender_id: str) -> str:
        """Queue the action the service proposed and return the job id.

        The ``notify`` descriptor is added here and nowhere else: this is the
        only layer that knows a WhatsApp user is waiting on the outcome. See
        ``executor/notify.py``.
        """
        job = action_enqueuer(
            proposal.kind, _with_outcome_notice(proposal.payload, sender_id, proposal.summary)
        )
        if proposal.confirmed:
            logger.info("confirmed action enqueued (kind=%s, job=%s)", proposal.kind, job.id)
        else:
            logger.info("action enqueued from message (kind=%s, job=%s)", proposal.kind, job.id)
        return job.id

    def _deliver(
        inbound: InboundMessage,
        reply: str,
        message_text: str,
        memory: LazyMemory,
        spans: ReplySpans,
        *,
        is_voice: bool,
        job_id: str,
    ) -> None:
        """Send the reply, dedupe it, and store the turn.

        Reply first, then persist — a deliberate amendment to the blueprint's
        recall -> route -> remember -> send order, authorized 26 August 2026.
        Writing is only ~0.5s now that it embeds instead of extracting, but the
        ordering still means no storage problem can ever delay or discard a
        reply the user is waiting on.

        Voice in, voice out — blueprint 3.3. A voice note gets a spoken reply
        back, not a wall of text it has to open the chat to read.
        """
        if is_voice:
            with spans.stage("tts"):
                audio = voice_synthesizer(reply)
            with spans.stage("send"):
                voice_sender(to=inbound.sender, audio=audio)
        else:
            with spans.stage("send"):
                sender(to=inbound.sender, text=reply)
        with open_seen_messages() as seen:
            seen.mark_sent(inbound.message_id)

        # The reply is already delivered and deduped, so a failure past this
        # point must not fail the job: a retry could not resend it, only repeat
        # the write. Losing one turn is the smaller loss.
        if not write_memory:
            return
        try:
            with spans.stage("remember"):
                memory.remember_turn(message_text, user_id=inbound.sender, role="user")
                memory.remember_turn(reply, user_id=inbound.sender, role="assistant")
        except Exception as exc:
            logger.warning(
                "reply sent but memory write failed (job=%s, %s)", job_id, type(exc).__name__
            )

    def handle(job: Job) -> None:
        spans = ReplySpans.for_job(job)
        inbound = parse_inbound_message(job.payload)
        if inbound is None:
            logger.info("whatsapp webhook job carried no inbound message (job=%s)", job.id)
            return

        with open_seen_messages() as seen:
            if seen.has_sent(inbound.message_id):
                logger.info(
                    "duplicate whatsapp message, already replied (job=%s, message_id=%s)",
                    job.id,
                    inbound.message_id,
                )
                return

        # Send the cosmetic cue before any local-memory work.  Recall can wait
        # on Ollama, and postponing this call until after it leaves the user in
        # silence even though the executor has already claimed their message.
        # It remains best-effort: a Graph API failure must never delay a reply.
        try:
            with spans.stage("cue"):
                typing_indicator(message_id=inbound.message_id)
        except Exception as exc:
            logger.warning("whatsapp typing indicator failed (job=%s, %s)", job.id, type(exc).__name__)
        else:
            logger.info("whatsapp typing indicator sent (job=%s, message_id=%s)", job.id, inbound.message_id)

        is_voice = inbound.audio_media_id is not None
        if is_voice:
            # Download/decode/transcribe failures propagate unchanged, same as
            # every other step in this handler — see the module docstring. A
            # retry can plausibly succeed (whisper-server mid-restart, a
            # network blip on the media fetch); there is no special-cased
            # apology reply for a permanently broken NPU build, because that
            # is a deploy problem to notice from the dead-lettered job, not
            # something to paper over per-message.
            # Download and transcription are one span: both exist only because
            # the message arrived as audio, and splitting them would put a
            # Graph API fetch in a stage named for the NPU.
            with spans.stage("stt"):
                audio_bytes, _mime_type = media_downloader(inbound.audio_media_id)
                message_text = audio_transcriber(audio_bytes)
            if not message_text or not message_text.strip():
                # Same treatment an empty-body text message already gets in
                # parse_inbound_message: no text means no message, silently.
                logger.info(
                    "whatsapp voice note transcribed to nothing (job=%s, message_id=%s)",
                    job.id,
                    inbound.message_id,
                )
                return
            message_text = message_text.strip()
        else:
            message_text = inbound.text

        # Everything from here is channel-neutral and lives in the service:
        # classify, recall, route. Commands are decided before recall/routing,
        # and on the transcript rather than the audio, so a spoken "turn wifi
        # off" is the same command a typed one is.
        #
        # The store is opened lazily so a command message, which recalls
        # nothing, does not pay to load the embedding runtime before the
        # classifier has had its say — exactly where that cost sat before the
        # service existed.
        with LazyMemory(open_memory) as memory:
            service = ConversationService(
                memory=memory,
                complete=completion,
                classify=classifier,
                open_pending_confirmations=open_pending_confirmations,
                handle_commands=commands_on,
            )
            result = service.reply(message_text, user_id=inbound.sender, spoken=is_voice)
            spans.update(result.timings)

            if result.action is not None:
                action_job_id = _enqueue_proposal(result.action, inbound.sender)
                reply = queued_reply(result.action.summary, action_job_id, spoken=is_voice)
            else:
                reply = result.reply

            _deliver(inbound, reply, message_text, memory, spans, is_voice=is_voice, job_id=job.id)

        # One line, after the reply is out and the turn is stored, so the
        # numbers cover the whole path the user waited on. Only a job that
        # replied gets here: every early return above says nothing, because a
        # no-op timed at 3 ms would drag every percentile down with it.
        spans.emit(logger)

    return handle
