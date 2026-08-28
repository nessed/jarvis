"""Dedup inbound Meta webhook deliveries before a job is ever enqueued.

Meta redelivers a webhook it didn't get a fast ``200`` for. Until this module
existed, ``bus/main.py``'s ``POST /webhook`` called ``enqueue()``
unconditionally on every delivery, so a redelivery of a message already
queued (or already replied to) created a second, wholly redundant job — a
wasted provider call and a wasted memory-recall/store cycle — before
``executor/handlers/whatsapp.py``'s ``SeenMessageStore`` ever got a chance to
catch it at the send step. That store only stops a *duplicate reply*; this
one stops the *duplicate job* one step earlier, at the point of enqueue.

Deliberately bus-local and independent of ``executor.handlers.whatsapp``:
that module already imports from ``bus`` (``bus.whatsapp_client``), so the
reverse import would be circular. This module therefore carries its own
small, id-only extraction of the same ``entry``/``changes``/``value``/
``messages`` shape ``parse_inbound_text_message`` walks, without that
function's sender/text/``type == "text"`` filtering — every message id
present counts here, since a redelivered non-text message is still a
redelivery.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

DEFAULT_WEBHOOK_DEDUP_DB_PATH = Path("webhook.seen-messages.db")


def extract_message_ids(payload: Mapping[str, Any]) -> list[str]:
    """Collect every message id present in a raw Meta webhook payload.

    Returns an empty list for anything with no ``messages`` array at all —
    status callbacks, malformed/empty bodies, or any other shape
    ``parse_inbound_text_message`` already treats as a no-op elsewhere in
    this codebase. A single delivery can carry more than one message, and
    every one of them counts, regardless of ``type``.
    """
    ids: list[str] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for message in value.get("messages") or []:
                message_id = message.get("id")
                if message_id:
                    ids.append(str(message_id))
    return ids


class SeenWebhookMessageStore:
    """Tracks which inbound webhook message ids have already been enqueued.

    Mirrors ``executor/handlers/whatsapp.py``'s ``SeenMessageStore`` exactly:
    an injectable sqlite path, ``INSERT OR IGNORE`` so a repeated mark is
    safe without a lock, and a ``mark_seen`` that is only ever called after
    the action it guards (here, ``enqueue()``) has actually succeeded — a
    crash between the check and the enqueue must not permanently blackhole a
    message.
    """

    def __init__(self, path: str | Path) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_webhook_messages "
            "(message_id TEXT PRIMARY KEY, seen_at TEXT NOT NULL)"
        )
        self._conn.commit()

    def has_seen(self, message_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_webhook_messages WHERE message_id = ?", (message_id,)
        ).fetchone()
        return row is not None

    def mark_seen(self, message_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_webhook_messages (message_id, seen_at) VALUES (?, ?)",
            (message_id, datetime.now(UTC).isoformat()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SeenWebhookMessageStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_default_seen_webhook_message_store(
    *, environ: Mapping[str, str] | None = None
) -> SeenWebhookMessageStore:
    """Open the webhook dedup store at its configured or default path.

    Follows the same env-var convention as ``executor/heartbeat.py``'s
    ``JARVIS_EXECUTOR_HEARTBEAT``: a single override variable with a literal
    default, rather than deriving the path from another setting. The default
    filename matches the ``*.seen-messages.db`` pattern already in
    ``.gitignore`` (added for ``SeenMessageStore``'s own default), so no
    gitignore change is needed for it.
    """
    settings = os.environ if environ is None else environ
    path = Path(
        settings.get("JARVIS_WEBHOOK_DEDUP_DB_PATH", str(DEFAULT_WEBHOOK_DEDUP_DB_PATH))
    )
    return SeenWebhookMessageStore(path)
