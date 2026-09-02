"""Tell whoever asked for an action how it turned out.

An action job knows what happened. The worker that can reach the user is a
different process. This module is the one seam between them, and it is
deliberately the *only* thing either side has to learn.

Why a queued job and not a direct send
--------------------------------------
The obvious shape is for the action handler to send the outcome itself, and
it is wrong for a reason that has nothing to do with tidiness: a send that
raises propagates to ``executor.poller``, which retries **the whole job**. A
failed notification would re-run ``wifi.set_enabled`` or ``process.kill`` in
order to redeliver a message about it. The side effect and the message about
the side effect need separate retry lifecycles, and the queue already
provides one.

So the action handler enqueues a second, ordinary job. It gains a dependency
on ``db.jobs`` — which it already imports for ``Job`` — and none at all on
WhatsApp, the Graph token, or the client. ``whatsapp-worker`` already owns
those and already polls; it claims the new kind and sends. Nothing needs a
watcher, an in-memory map, or state that has to survive a restart, because
the durable queue is the state.

The alternative considered and rejected was a completion watcher inside
``whatsapp-worker`` polling the jobs it enqueued. Its one real advantage is
that it observes *any* terminal state with no poller change at all; its cost
is a second scheduling mechanism plus a local job-id-to-recipient map to
survive a restart. The full exchange, including why the privacy argument for
it does not survive contact with the live table, is at
``docs/consults/2026-09-02-action-outcome-reply-shape/``.

What may go in a notify payload
-------------------------------
The jobs table is **hosted**, so this module renders and truncates rather
than passing text through. What lands there is a status word, the action's
own name, and a bounded, already-truncated rendering of the action's return
value. Never an LLM-generated summary, never conversation text, and on the
failure side never more than the exception type plus the fixed-vocabulary
slug ``executor.poller._describe_failure`` already admits.

That bound is real but it is not absolute, and it should not be mistaken for
one: the sender's phone number and the inbound message body are *already* in
that table on every ``whatsapp_webhook`` row, because the bus is enqueue-only
and enqueues Meta's raw payload. Checked 2 Sep 2026 against the live table —
49 inbound messages, 49 carrying the sender's number, 46 carrying the text
body. The discipline this module keeps is about not making that worse.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from db.jobs import Job, JobRepository, enqueue

logger = logging.getLogger(__name__)

#: The action payload key carrying "and tell someone how this went".
#: Absent means nobody asked, which is the common case — a job enqueued by a
#: tool or a test notifies no one and this module is a no-op for it.
NOTIFY_FIELD = "notify"

WHATSAPP_OUTCOME_JOB_KIND = "whatsapp_outcome"

#: An outcome that raced ahead of the reply it belongs to is worse than one
#: that trails it, so give the queued acknowledgement a moment to land first.
DEFAULT_NOTIFY_DELAY_SECONDS = 0.0

#: How much of an action's rendered result reaches the hosted table. Long
#: enough for ``wifi.list_interfaces`` to be an answer rather than a tease,
#: short enough that no action can turn the queue into a document store.
MAX_DETAIL_CHARS = 400

STATUS_OK = "ok"
STATUS_FAILED = "failed"


def notify_descriptor(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build the descriptor an *enqueuer* attaches to an action's payload.

    Written by whoever knows who is waiting — today that is
    ``executor.handlers.whatsapp`` — and read only here. Keeping it a
    ``{kind, payload}`` pair rather than a WhatsApp-shaped field is what lets
    ``executor.poller`` carry it through the generic failure path without
    learning that WhatsApp exists.
    """
    return {"kind": str(kind), "payload": dict(payload)}


def outcome_payload(
    descriptor: Mapping[str, Any], *, status: str, action: str | None, detail: str
) -> dict[str, Any]:
    """The payload of the outcome job itself: the descriptor's, plus what happened."""
    payload = dict(descriptor.get("payload") or {})
    payload["status"] = status
    payload["detail"] = truncate_detail(detail)
    if action:
        payload["action"] = str(action)
    return payload


def truncate_detail(detail: object) -> str:
    """Render an action's result to a bounded single line.

    Actions return lists, dicts, strings and ``None``, and the reply has to
    survive all of them without either dropping the answer or shipping an
    unbounded blob to a hosted table.
    """
    text = "" if detail is None else str(detail)
    text = " ".join(text.split())
    if len(text) <= MAX_DETAIL_CHARS:
        return text
    return text[: MAX_DETAIL_CHARS - 1].rstrip() + "…"


def enqueue_outcome(
    job: Job,
    *,
    status: str,
    detail: object = "",
    repository: JobRepository | None = None,
    delay_seconds: float = DEFAULT_NOTIFY_DELAY_SECONDS,
) -> Job | None:
    """Enqueue this job's outcome notification, if it asked for one.

    Returns the enqueued job, or ``None`` when the action carried no notify
    descriptor — which is most of them.

    **This never raises.** It is called from the action handler's success path
    and from the poller's terminal failure paths, and in both a raise would be
    read as the *action* failing. An action that ran and then could not be
    reported on is not an action that needs re-running; the poller would
    retry ``process.kill`` to redeliver a message about it. So a broken
    notification is logged and swallowed, deliberately, and the log line is
    the thing to grep for when a user says the reply never came.
    """
    descriptor = _descriptor_of(job)
    if descriptor is None:
        return None
    kind = descriptor.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        logger.warning("job %s carries a notify descriptor with no kind; not notifying", job.id)
        return None

    payload = outcome_payload(
        descriptor,
        status=status,
        action=_action_of(job),
        detail=detail,
    )
    try:
        from datetime import UTC, datetime, timedelta

        run_after = datetime.now(UTC) + timedelta(seconds=max(0.0, delay_seconds))
        outcome = enqueue(kind.strip(), payload, run_after, repository=repository)
    except Exception as exc:  # noqa: BLE001 - see the docstring: never raise
        logger.warning(
            "could not enqueue the %s outcome for job %s (%s); the action itself is unaffected",
            kind,
            job.id,
            type(exc).__name__,
        )
        return None
    logger.info(
        "enqueued %s outcome %s for job %s (status=%s)", kind, outcome.id, job.id, status
    )
    return outcome


def _descriptor_of(job: Job) -> Mapping[str, Any] | None:
    payload = getattr(job, "payload", None)
    if not isinstance(payload, Mapping):
        return None
    descriptor = payload.get(NOTIFY_FIELD)
    return descriptor if isinstance(descriptor, Mapping) else None


def _action_of(job: Job) -> str | None:
    """The ``system_control``-style action name, when the payload has one.

    Best effort and optional: the two UIA kinds have no ``action`` key, and
    the outcome reads fine without it.
    """
    payload = getattr(job, "payload", None)
    if not isinstance(payload, Mapping):
        return None
    action = payload.get("action")
    return str(action) if isinstance(action, str) and action.strip() else None
