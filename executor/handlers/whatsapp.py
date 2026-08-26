"""Blueprint step 1.4: recall -> route -> remember -> send for one inbound message.

Turns a claimed ``whatsapp_webhook`` job's raw Meta payload into a routed LLM
reply, sent back over the same client used everywhere else outbound
(``bus.whatsapp_client.WhatsAppClient``). Memory, routing, and sending are all
injectable so this can be unit-tested without Ollama, a live provider, or the
Graph API.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from bus.whatsapp_client import WhatsAppClient, WhatsAppClientConfig
from db.jobs import Job
from memory.runtime import LocalMem0Runtime, open_local_mem0_memory
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
                if sender and text:
                    return InboundMessage(sender=str(sender), text=str(text))
    return None


MemoryOpener = Callable[[], LocalMem0Runtime]
Completion = Callable[[str, Sequence[Mapping[str, Any]]], RoutedResult]
Sender = Callable[..., str]


def build_whatsapp_webhook_handler(
    *,
    open_memory: MemoryOpener = open_local_mem0_memory,
    complete: Completion | None = None,
    send_text_message: Sender | None = None,
) -> Callable[[Job], None]:
    """Return a plain ``JobHandler`` closure wiring recall -> route -> remember -> send.

    Any raised exception (recall, routing, or send failure) propagates
    unchanged to the poller, which already retries/backs off/dead-letters it
    with a type-only diagnostic — this handler adds no error handling of its
    own on top of that.
    """

    def _default_complete(task_profile: str, messages: Sequence[Mapping[str, Any]]) -> RoutedResult:
        return asyncio.run(route(task_profile, messages, urgent=True))

    def _default_send(*, to: str, text: str) -> str:
        client = WhatsAppClient(WhatsAppClientConfig.from_environ())
        return client.send_text_message(to=to, text=text)

    completion = complete or _default_complete
    sender = send_text_message or _default_send

    def handle(job: Job) -> None:
        inbound = parse_inbound_text_message(job.payload)
        if inbound is None:
            logger.info("whatsapp webhook job carried no inbound text message (job=%s)", job.id)
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

            memory.remember(f"User: {inbound.text}", user_id=inbound.sender)
            memory.remember(f"Assistant: {reply}", user_id=inbound.sender)

        sender(to=inbound.sender, text=reply)

    return handle


def _format_recalled_context(recalled: Any) -> str:
    results = recalled.get("results", []) if isinstance(recalled, Mapping) else recalled
    lines = [entry["memory"] for entry in results if isinstance(entry, Mapping) and entry.get("memory")]
    return "\n".join(lines)


def _extract_reply_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise ValueError("routed completion returned an unexpected response shape") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("routed completion returned an empty reply")
    return content.strip()
