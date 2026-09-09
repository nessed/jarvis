"""Answer a text WhatsApp message in-process, right after the webhook returns.

Ali, 8 Sep 2026 (``QUESTIONS.md`` Q17.1): "for now, answer right away."
``bus/main.py`` schedules :func:`build_inline_reply_task`'s callable as a
FastAPI ``BackgroundTask`` once ``receive_webhook`` has verified, deduped and
returned ``{"accepted": true}`` -- so a slow reply never delays Meta's 200,
and a crash here does not blackhole the webhook response, only this one
reply. Voice notes and every action a message proposes still go through the
Supabase queue and ``executor.handlers.whatsapp`` unchanged; this module
only ever sees text.

Import weight matters here exactly as it does in
``executor.conversation.service``: this is meant to run on a rented box with
no GPU and no audio stack, so nothing here may pull ``torch``, ``kokoro``,
``pywinauto``, ``pyflp``, ``sounddevice`` or ``voice/`` in transitively.
Proven the same way that module's is, in
``tests/bus/test_conversation_runner.py``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Mapping, Sequence

from db.jobs import Job, enqueue
from executor.conversation.service import ConversationService, LazyMemory, owner_wa_id
from executor.handlers.command_intent import (
    PendingConfirmationStore,
    open_default_pending_confirmation_store,
    queued_reply,
)
from executor.handlers.outcome import WHATSAPP_OUTCOME_JOB_KIND
from executor.handlers.whatsapp import InboundMessage, commands_enabled, memory_writes_enabled
from executor.latency import ReplySpans
from executor.notify import NOTIFY_FIELD, notify_descriptor
from memory.conversation import open_conversation_memory
from router import RoutedResult, route_sync

logger = logging.getLogger(__name__)

INLINE_REPLY_ENV = "JARVIS_INLINE_REPLY"


def inline_reply_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Whether a text message answers in-process instead of queueing.

    Default **on**, per Ali's 8 Sep answer. ``JARVIS_INLINE_REPLY=0`` is the
    one-variable rollback to the previous all-queued behaviour, read the
    strict way round so a typo cannot silently disable it.
    """
    settings = os.environ if environ is None else environ
    return (settings.get(INLINE_REPLY_ENV, "1") or "").strip().lower() in {"1", "true", "yes", "on"}


MemoryOpener = Callable[[], Any]
PendingStoreOpener = Callable[[], PendingConfirmationStore]
CommandClassifier = Callable[[str], Any]
Completion = Callable[[str, Sequence[Mapping[str, Any]]], RoutedResult]
ActionEnqueuer = Callable[[str, Mapping[str, Any]], Job]
Sender = Callable[..., str]


def _with_outcome_notice(payload: Mapping[str, Any], reply_to: str, summary: str) -> dict[str, Any]:
    """The action payload, plus "and tell this person how it went".

    Mirrors ``executor.handlers.whatsapp``'s private helper of the same
    shape rather than importing it: that function is not part of this
    module's public surface, and the two channels agreeing on the descriptor
    shape (``executor/notify.py``) is what actually has to stay true, not
    which module renders it.
    """
    return {
        **dict(payload),
        NOTIFY_FIELD: notify_descriptor(WHATSAPP_OUTCOME_JOB_KIND, {"reply_to": reply_to, "summary": summary}),
    }


def build_inline_reply_task(
    *,
    open_memory: MemoryOpener = open_conversation_memory,
    complete: Completion | None = None,
    send_text_message: Sender | None = None,
    open_pending_confirmations: PendingStoreOpener = open_default_pending_confirmation_store,
    classify: CommandClassifier | None = None,
    enqueue_action: ActionEnqueuer | None = None,
    write_memory: bool | None = None,
    handle_commands: bool | None = None,
    owner_id: str | None = None,
) -> Callable[[InboundMessage], None]:
    """Build the ``BackgroundTasks`` callable that answers one text message.

    Same service, same action-enqueue shape, same reply-latency line as
    ``executor.handlers.whatsapp.build_whatsapp_webhook_handler``'s text
    path -- minus everything that is either voice-only (cue, STT/TTS) or
    already handled before this runs: the bus's webhook dedup has already
    decided this message is worth answering, so there is no second
    already-sent check here the way the queue path needs one against
    redelivery.

    Every dependency is injectable, same reason as everywhere else in this
    codebase: this must run under test with no Ollama, no provider, no queue
    and no Graph API.
    """

    def _default_complete(task_profile: str, messages: Sequence[Mapping[str, Any]]) -> RoutedResult:
        return route_sync(task_profile, messages, urgent=True)

    # One Graph client for the life of the bus process, built on first use --
    # same reasoning as executor/handlers/whatsapp.py's own ``_graph()``:
    # ``load_dotenv()`` has already run by the time ``create_app`` builds this
    # closure (bus/main.py calls it at module scope before ``create_app()``),
    # but importing ``bus.whatsapp_client`` lazily still keeps this function
    # cheap to call from a test that never sends anything.
    graph_client: list[Any] = []

    def _graph() -> Any:
        if not graph_client:
            from bus.whatsapp_client import WhatsAppClient, WhatsAppClientConfig

            graph_client.append(WhatsAppClient(WhatsAppClientConfig.from_environ()))
        return graph_client[0]

    def _default_send(*, to: str, text: str) -> str:
        return _graph().send_text_message(to=to, text=text)

    completion = complete or _default_complete
    sender = send_text_message or _default_send
    should_write_memory = memory_writes_enabled() if write_memory is None else write_memory
    action_enqueuer = enqueue_action or (lambda kind, payload: enqueue(kind, dict(payload)))
    commands_on = commands_enabled() if handle_commands is None else handle_commands

    def answer(inbound: InboundMessage) -> None:
        assert inbound.text is not None, "the caller filters to text messages before scheduling this"
        spans = ReplySpans.for_inline_reply(inbound.message_id, "whatsapp_webhook")

        with LazyMemory(open_memory) as memory:
            service = ConversationService(
                memory=memory,
                complete=completion,
                classify=classify,
                open_pending_confirmations=open_pending_confirmations,
                handle_commands=commands_on,
                owner_id=owner_id if owner_id is not None else owner_wa_id(),
            )
            sender_is_owner = service.is_owner(inbound.sender)
            result = service.reply(inbound.text, user_id=inbound.sender, spoken=False)
            spans.update(result.timings)

            if result.action is not None:
                job = action_enqueuer(
                    result.action.kind,
                    _with_outcome_notice(result.action.payload, inbound.sender, result.action.summary),
                )
                if result.action.confirmed:
                    logger.info("confirmed action enqueued (kind=%s, job=%s)", result.action.kind, job.id)
                else:
                    logger.info("action enqueued from message (kind=%s, job=%s)", result.action.kind, job.id)
                reply = queued_reply(result.action.summary, job.id, spoken=False)
            else:
                reply = result.reply

            with spans.stage("send"):
                sender(to=inbound.sender, text=reply)

            # Same ordering rationale as the queue path's ``_deliver``: reply
            # first, persist after, so no storage problem can delay or
            # discard a reply the user is waiting on. And the same owner gate
            # as ``ConversationService.remember`` -- checked here rather than
            # calling that method, because this path already has both halves
            # of the turn (the enqueue path's ``queued_reply`` text) that
            # ``remember`` alone does not see.
            if should_write_memory and sender_is_owner:
                try:
                    with spans.stage("remember"):
                        memory.remember_turn(inbound.text, user_id=inbound.sender, role="user")
                        memory.remember_turn(reply, user_id=inbound.sender, role="assistant")
                except Exception as exc:
                    logger.warning("inline reply sent but memory write failed (%s)", type(exc).__name__)

        spans.emit(logger)

    return answer
