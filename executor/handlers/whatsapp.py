"""Blueprint step 1.4: recall -> route -> send -> remember for one inbound message.

Turns a claimed ``whatsapp_webhook`` job's raw Meta payload into a routed LLM
reply, sent back over the same client used everywhere else outbound
(``bus.whatsapp_client.WhatsAppClient``). Memory, routing, and sending are all
injectable so this can be unit-tested without Ollama, a live provider, or the
Graph API.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from bus.whatsapp_client import WhatsAppClient, WhatsAppClientConfig
from db.jobs import Job
from memory.conversation import ConversationMemory, open_conversation_memory
from router import RoutedResult, route

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are JARVIS, replying to a user over WhatsApp. Keep replies short, "
    "plain, and direct. Use the remembered context below if it's relevant to "
    "this message; ignore it if it isn't."
)


@dataclass(frozen=True)
class InboundMessage:
    """The one thing this handler needs out of a raw Meta webhook payload."""

    sender: str
    text: str
    message_id: str


def parse_inbound_text_message(payload: Mapping[str, Any]) -> InboundMessage | None:
    """Extract the first inbound text message from a raw Meta webhook payload.

    Returns ``None`` for anything that is not an inbound text message —
    delivery/read status callbacks, non-text message types (image, audio,
    reaction, ...), and malformed or empty payloads are all silent no-ops,
    not errors, since Meta sends all of those to the same webhook.
    """
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for message in value.get("messages") or []:
                if message.get("type") != "text":
                    continue
                sender = message.get("from")
                text = (message.get("text") or {}).get("body")
                message_id = message.get("id")
                if sender and text and message_id:
                    return InboundMessage(sender=str(sender), text=str(text), message_id=str(message_id))
    return None


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
Completion = Callable[[str, Sequence[Mapping[str, Any]]], RoutedResult]
Sender = Callable[..., str]


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


def build_whatsapp_webhook_handler(
    *,
    open_memory: MemoryOpener = open_conversation_memory,
    open_seen_messages: SeenStoreOpener = open_default_seen_message_store,
    complete: Completion | None = None,
    send_text_message: Sender | None = None,
    write_memory: bool | None = None,
) -> Callable[[Job], None]:
    """Return a plain ``JobHandler`` closure wiring recall -> route -> send -> remember.

    Any raised exception (recall, routing, or send failure) propagates
    unchanged to the poller, which already retries/backs off/dead-letters it
    with a type-only diagnostic — this handler adds no error handling of its
    own on top of that. A message id already marked sent is a silent no-op,
    same as an unparseable payload; it is not an error either.

    ``write_memory`` defaults to ``memory_writes_enabled()`` (off unless
    ``JARVIS_MEMORY_WRITES`` is set); ``recall()`` runs either way.
    """

    def _default_complete(task_profile: str, messages: Sequence[Mapping[str, Any]]) -> RoutedResult:
        return asyncio.run(route(task_profile, messages, urgent=True))

    def _default_send(*, to: str, text: str) -> str:
        client = WhatsAppClient(WhatsAppClientConfig.from_environ())
        return client.send_text_message(to=to, text=text)

    completion = complete or _default_complete
    sender = send_text_message or _default_send
    write_memory = memory_writes_enabled() if write_memory is None else write_memory

    def handle(job: Job) -> None:
        inbound = parse_inbound_text_message(job.payload)
        if inbound is None:
            logger.info("whatsapp webhook job carried no inbound text message (job=%s)", job.id)
            return

        with open_seen_messages() as seen:
            if seen.has_sent(inbound.message_id):
                logger.info(
                    "duplicate whatsapp message, already replied (job=%s, message_id=%s)",
                    job.id,
                    inbound.message_id,
                )
                return

        with open_memory() as memory:
            recalled = memory.recall(inbound.text, user_id=inbound.sender)
            messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
            context = _format_recalled_context(recalled)
            if context:
                messages.append({"role": "system", "content": f"Remembered context:\n{context}"})
            messages.append({"role": "user", "content": inbound.text})

            result = completion("latency", messages)
            reply = _extract_reply_text(result.response)

            # Reply first, then persist — a deliberate amendment to the
            # blueprint's recall -> route -> remember -> send order, authorized
            # 26 August 2026. Writing is only ~0.5s now that it embeds instead
            # of extracting, but the ordering still means no storage problem
            # can ever delay or discard a reply the user is waiting on.
            sender(to=inbound.sender, text=reply)
            with open_seen_messages() as seen:
                seen.mark_sent(inbound.message_id)

            # The reply is already delivered and deduped, so a failure past
            # this point must not fail the job: a retry could not resend it,
            # only repeat the write. Losing one turn is the smaller loss.
            if not write_memory:
                return
            try:
                memory.remember_turn(inbound.text, user_id=inbound.sender, role="user")
                memory.remember_turn(reply, user_id=inbound.sender, role="assistant")
            except Exception as exc:
                logger.warning(
                    "reply sent but memory write failed (job=%s, %s)", job.id, type(exc).__name__
                )

    return handle


def _format_recalled_context(recalled: Any) -> str:
    """Render recalled memory as prompt lines.

    Accepts ``Fact`` objects from :mod:`memory.conversation` and, for
    resilience against a caller still holding the older surface, Mem0's
    ``{"results": [{"memory": ...}]}`` dicts.
    """
    results = recalled.get("results", []) if isinstance(recalled, Mapping) else recalled
    lines: list[str] = []
    for entry in results or []:
        if isinstance(entry, Mapping):
            text = entry.get("memory")
        else:
            text = getattr(entry, "text", None)
        if isinstance(text, str) and text.strip():
            lines.append(text.strip())
    return "\n".join(lines)


def _extract_reply_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise ValueError("routed completion returned an unexpected response shape") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("routed completion returned an empty reply")
    return content.strip()
