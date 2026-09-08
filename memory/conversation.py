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

import os
from dataclasses import dataclass
from typing import Any, Mapping

from memory.runtime import LocalMemoryRuntime, open_local_memory
from memory.types import Fact

TURN_SOURCE_PREFIX = "whatsapp"

# Recall over-fetches before filtering because the sqlite-vec index is shared by
# conversation turns and distilled/backfilled facts alike, and nearest-neighbour
# order does not respect the source split.
_OVERFETCH = 6

#: How far a match may be and still count as remembered context. Measured on
#: this laptop's own 286-fact store, 9 Sep 2026: a near-duplicate scores
#: 0.0-0.52, a genuinely related fact 0.7-0.9, and an unrelated row 1.0 and up.
#: 0.9 keeps the middle band and drops the "least-unrelated row in the store"
#: answers that a thresholdless nearest-neighbour search always produces.
DEFAULT_RECALL_MAX_DISTANCE = 0.9
RECALL_MAX_DISTANCE_ENV = "JARVIS_RECALL_MAX_DISTANCE"


def recall_max_distance(environ: Mapping[str, str] | None = None) -> float | None:
    """The distance cut-off, or ``None`` for the old thresholdless behaviour."""
    settings = os.environ if environ is None else environ
    raw = (settings.get(RECALL_MAX_DISTANCE_ENV) or "").strip()
    if not raw:
        return DEFAULT_RECALL_MAX_DISTANCE
    if raw.lower() in {"none", "off"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_RECALL_MAX_DISTANCE


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
        """Return remembered *facts* — never raw conversation turns.

        Turns used to be included, and it was the right call while this was the
        only continuity mechanism there was. :meth:`recent_turns` is that now,
        and it does the job properly: in order, recent, and complete. Leaving
        turns in here as well stopped being redundant and became actively
        harmful.

        What it did, live on 9 Sep 2026: JARVIS answered "when will it be
        done" with "The document will be ready by August 26 2026." That reply
        was stored as a turn. The next question then recalled **its own
        previous answer** at distance 0.797, pasted it back in as remembered
        context, and it said the same thing again — then defended it when
        asked "what document bro". A nearest-neighbour search over a store
        containing the model's own output is a feedback loop, and the model
        cannot tell its own stale guess from something it was told.

        So: distilled memories and backfilled notes only. Those are statements
        *about* the owner, written deliberately by the distill chain, not a
        transcript of what was said thirty seconds ago.
        """
        if limit <= 0:
            return []
        matches = self.runtime.service.recall(
            query, limit=limit * _OVERFETCH, max_distance=recall_max_distance()
        )
        kept = [fact for fact in matches if not is_conversation_turn(fact)]
        return kept[:limit]

    def recent_turns(self, *, user_id: str, limit: int = 10) -> list[Fact]:
        """This conversation's most recent turns, oldest first.

        Deliberately **not** :meth:`recall`. Recall is a semantic
        nearest-neighbour search over every stored turn and every distilled
        fact, unordered and unbounded in time; it answers "what do I know that
        resembles this?". This answers "what were we just saying?", which is a
        different question and the one a conversation actually runs on.

        Confusing the two is what made JARVIS unable to hold a thread. Asked
        "when will it be done" seconds after queueing a job, it had no idea a
        job existed -- the prompt carried no prior turns at all -- so it
        answered out of whatever recall had surfaced, and said "Document ready
        by August 26, 2026." (live, 9 Sep 2026).

        Ordered by the store's indexed ``created_at``, newest-first, then
        reversed: the newest N turns are what a conversation needs, but a model
        needs them in the order they were said.
        """
        if limit <= 0:
            return []
        newest = self.runtime.store.list_facts(
            source=turn_source(user_id), limit=limit, oldest_first=False
        )
        return list(reversed(newest))

    def undistilled_turns(self, *, limit: int | None = None) -> list[Fact]:
        """Turns not yet folded into Mem0 facts, oldest first.

        Filters on the store's indexed ``distilled`` column so the emptiness
        check the distill chain runs on every tick (``limit=1``) is a single
        indexed lookup, not a full-table JSON-decode-and-filter. Only
        ``remember_turn``/``mark_distilled`` ever set the ``distilled``
        metadata key today, so the SQL filter already selects exactly this
        conversation's/every conversation's turns; ``is_conversation_turn`` is
        kept as a cheap defense-in-depth check on the small matched set, not
        as the thing doing the real filtering.
        """
        candidates = self.runtime.store.list_facts(distilled=False, limit=limit, oldest_first=True)
        turns = [fact for fact in candidates if is_conversation_turn(fact)]
        return turns

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
