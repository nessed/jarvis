"""The ``whatsapp_outcome`` job kind: say how the action the user asked for went.

A WhatsApp command already gets an immediate "On it: turn wifi off. Queued as
job a8b4785b." Until this handler existed, that was the last the user heard of
it — whether the action worked, failed, or was dead-lettered after three
attempts. Silence is worst in the failure case, which is precisely the case
the old code could not report.

This handler is the *sending* half. The deciding half is
``executor/notify.py``, which explains why the outcome travels as a durable
job rather than as a direct send from the action handler: a Graph send that
raises inside an action handler would make the poller retry the action, so a
failed notification would re-run ``process.kill`` in order to redeliver a
message about it.

Why this kind belongs to ``whatsapp-worker``
--------------------------------------------
``whatsapp-worker`` already owns the Graph client and the token; the
``action-worker`` process needs neither and does not get either. Registering
this kind there is the whole coupling, and it is one line of ``--kind``.

Why it cannot loop
------------------
An outcome is outbound. It is its own job kind with its own handler, and this
module never touches ``parse_inbound_message`` or ``classify_command``, so an
outcome reply is structurally incapable of re-entering the command
classifier — no flag, no marker, and nothing to get wrong later.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Mapping

from db.jobs import Job

logger = logging.getLogger(__name__)

WHATSAPP_OUTCOME_JOB_KIND = "whatsapp_outcome"

Sender = Callable[..., str]


class MissingOutcomeRecipient(Exception):
    """Raised when an outcome job names nobody to tell.

    Deliberately raised rather than logged and skipped: a payload with no
    ``reply_to`` means whoever enqueued it built the descriptor wrong, and
    that is a bug worth a dead-lettered row rather than a silent drop.
    """


def build_whatsapp_outcome_handler(*, send_text_message: Sender | None = None) -> Callable[[Job], None]:
    """Return the ``JobHandler`` that delivers one action outcome.

    ``send_text_message`` defaults to the same Graph client every other
    outbound path uses, constructed inside the closure rather than at import
    time so registering this handler never requires a token.
    """

    def _default_send(*, to: str, text: str) -> str:
        from bus.whatsapp_client import WhatsAppClient, WhatsAppClientConfig

        client = WhatsAppClient(WhatsAppClientConfig.from_environ())
        return client.send_text_message(to=to, text=text)

    sender = send_text_message or _default_send

    def _handle(job: Job) -> None:
        payload: Mapping[str, Any] = job.payload or {}
        recipient = payload.get("reply_to")
        if not isinstance(recipient, str) or not recipient.strip():
            raise MissingOutcomeRecipient(
                f"{WHATSAPP_OUTCOME_JOB_KIND} job payload has no reply_to"
            )
        sender(to=recipient.strip(), text=render_outcome(payload))
        logger.info("sent the outcome for %s (job=%s)", payload.get("action"), job.id)

    return _handle


def render_outcome(payload: Mapping[str, Any]) -> str:
    """Turn an outcome payload into the sentence the user reads.

    Every part comes from the payload the action handler rendered; nothing is
    generated here and nothing is quoted back from the user's own message.

    The summary is what the user was told when the action queued, so reusing
    it verbatim is what makes the two messages read as one exchange rather
    than as an acknowledgement followed by an unrelated status code.
    """
    status = str(payload.get("status") or "").strip().lower()
    summary = _text(payload.get("summary"))
    detail = _text(payload.get("detail"))
    subject = summary or _text(payload.get("action")) or "that"

    if status == "failed":
        # The detail here is an exception type plus a fixed-vocabulary slug,
        # never a message. Useless to read aloud, but it is the difference
        # between "it broke" and a user who can say which part broke.
        return f"That didn't work — {subject} failed ({detail})." if detail else (
            f"That didn't work — {subject} failed."
        )
    if not detail or detail == subject:
        return f"Done: {subject}."
    return f"Done: {subject}. {detail}" if detail.endswith((".", "!", "?")) else (
        f"Done: {subject}. {detail}."
    )


def _text(value: object) -> str:
    return str(value).strip() if isinstance(value, str) else ""
