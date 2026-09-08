"""The channel-neutral reply brain: text in, reply text out.

Everything here is deliberately free of WhatsApp, Meta, sqlite paths and
audio. The WhatsApp handler wires it to the Graph API; the bus will call the
same object in-process on a VPS (``conversation-inline-reply``), and a desk
voice loop later calls it a third way. See
``docs/board/tasks/conversation-service-extract.md``.
"""

from executor.conversation.service import (
    SYSTEM_PROMPT,
    VOICE_REPLY_LANGUAGE_NOTE,
    ActionProposal,
    ConversationService,
    LazyMemory,
    ReplyResult,
)

__all__ = [
    "SYSTEM_PROMPT",
    "VOICE_REPLY_LANGUAGE_NOTE",
    "ActionProposal",
    "ConversationService",
    "LazyMemory",
    "ReplyResult",
]
