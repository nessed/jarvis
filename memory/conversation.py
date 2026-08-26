"""Conversation-turn memory: embed and store, no LLM extraction on the live path.

Mem0's fact extraction runs an 8B model twice per message and cost 20-130s on
this hardware, failing on 100% of live WhatsApp turns (see
``docs/history/whatsapp-reply-failures.md``). Embedding the same text costs
~0.5s, because the embedding model is 137M parameters against the extraction
model's 8B.

So the live path stores turns verbatim through :class:`MemoryService`, which
deliberately performs no extraction, and recall searches those turns directly.
Distilling turns into Mem0 facts is a separate batch pass over the stored
turns — it is no longer in the way of a reply. This is the "plain text plus
local semantic search" option ``docs/blueprint.md`` section 4 calls the
underrated one; it keeps every byte on loopback exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from memory.runtime import LocalMemoryRuntime, open_local_memory
from memory.types import Fact

TURN_SOURCE_PREFIX = "whatsapp"

# Recall over-fetches before filtering because the sqlite-vec index is shared by
# conversation turns and distilled/backfilled facts alike, and nearest-neighbour
# order does not respect the source split.
_OVERFETCH = 6


def turn_source(user_id: str) -> str:
    """The ``source`` value marking a stored turn as one conversation's."""
    return f"{TURN_SOURCE_PREFIX}:{_require(user_id, 'user_id')}"


def is_conversation_turn(fact: Fact) -> bool:
    return fact.source.startswith(f"{TURN_SOURCE_PREFIX}:")


@dataclass
class ConversationMemory:
    """Store and recall raw conversation turns on the local embedding path."""

    runtime: LocalMemoryRuntime

    def remember_turn(
        self,
        text: str,
        *,
        user_id: str,
        role: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Fact:
        """Embed and persist one turn verbatim.

        ``distilled`` starts false so a later batch pass can find turns that
        have not yet been through Mem0's fact extraction.
        """
        if role not in {"user", "assistant"}:
            raise ValueError("role must be 'user' or 'assistant'")
        return self.runtime.service.remember(
            text,
            turn_source(user_id),
            metadata={**dict(metadata or {}), "role": role, "user_id": user_id, "distilled": False},
        )

    def recall(self, query: str, *, user_id: str, limit: int = 10) -> list[Fact]:
        """Return this conversation's turns and any non-conversation facts.

        Another conversation's turns are excluded. Facts that are not turns at
        all — backfilled notes, distilled Mem0 memories — stay eligible,
        because they are this machine owner's memory regardless of which
        thread produced them.
        """
        if limit <= 0:
            return []
        mine = turn_source(user_id)
        matches = self.runtime.service.recall(query, limit=limit * _OVERFETCH)
        kept = [f for f in matches if not is_conversation_turn(f) or f.source == mine]
        return kept[:limit]

    def undistilled_turns(self, *, limit: int | None = None) -> list[Fact]:
        """Turns not yet folded into Mem0 facts, oldest first."""
        facts = [
            fact
            for fact in self.runtime.store.list_facts()
            if is_conversation_turn(fact) and not fact.metadata.get("distilled")
        ]
        facts.sort(key=lambda f: f.created_at)
        return facts if limit is None else facts[:limit]

    def mark_distilled(self, fact: Fact) -> None:
        """Record that a turn has been through fact extraction."""
        self.runtime.store.update(fact.id, metadata={**fact.metadata, "distilled": True})

    def close(self) -> None:
        self.runtime.close()

    def __enter__(self) -> "ConversationMemory":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_conversation_memory(
    database_path: str | None = None, *, environ: dict[str, str] | None = None
) -> ConversationMemory:
    """Open the local-only turn store the WhatsApp handler writes through."""
    return ConversationMemory(open_local_memory(database_path, environ=environ))


def _require(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()
