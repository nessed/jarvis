"""One implementation of "fold stored conversation turns into Mem0 facts".

Two callers drive this: the offline CLI (``tools/distill_memory.py``) and the
executor job kind (``executor/handlers/distill.py``). They share this function
rather than each carrying their own loop, so the invariant that matters cannot
drift between them: **a turn is marked distilled only after its extraction
succeeded**, so a crash, a timeout, or a killed executor leaves the turn
eligible for the next pass instead of silently dropping it.

The two callers differ in exactly one place, which is why ``on_error`` exists.
The CLI logs a failed turn and carries on through the rest of the batch,
because a human is watching the output. The executor handler lets the failure
propagate, so the poller's existing retry/backoff/dead-letter path owns it and
the failure shows up in ``/status``'s ``retry_health`` rather than being
swallowed by a background process nobody is reading.

Nothing here opens Ollama, a database, or a network connection. Both the turn
store and the Mem0 surface are passed in, which is what lets the executor tests
prove the chunking and yielding behaviour against fakes.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from memory.types import Fact


class TurnStore(Protocol):
    """The slice of :class:`memory.conversation.ConversationMemory` used here."""

    def undistilled_turns(self, *, limit: int | None = None) -> list[Fact]: ...

    def mark_distilled(self, fact: Fact) -> None: ...


class FactExtractor(Protocol):
    """The slice of :class:`memory.runtime.LocalMem0Runtime` used here."""

    def remember(self, text: str, **kwargs: Any) -> Any: ...


# Called with the turn and how long its extraction took, for progress output.
DistilledCallback = Callable[[Fact, float], None]
# Called with the turn and the exception. Returning normally swallows the
# failure and continues; raising propagates it to the caller.
ErrorCallback = Callable[[Fact, Exception], None]


@dataclass(frozen=True)
class DistillReport:
    """What one pass did, and whether the queue of turns is now empty."""

    attempted: int = 0
    distilled: int = 0
    failed: int = 0
    more_pending: bool = False

    @property
    def did_work(self) -> bool:
        return self.attempted > 0


def distill_turns(
    turns: TurnStore,
    extractor: FactExtractor,
    *,
    limit: int | None = None,
    on_distilled: DistilledCallback | None = None,
    on_error: ErrorCallback | None = None,
) -> DistillReport:
    """Extract facts from up to ``limit`` undistilled turns, oldest first.

    ``limit`` of ``None`` means the whole backlog, which is the CLI's default.
    The executor passes a small integer — one, in practice — because each
    extraction holds the single local Ollama for tens of seconds and the poll
    loop is serial, so the chunk size *is* the worst-case delay a live reply
    can inherit.

    One extra turn is fetched beyond ``limit`` purely to set
    ``more_pending``. It is never extracted. That flag is how the executor
    chain tells "come back promptly, there is a backlog" apart from "the
    backlog is empty, idle until later" without a second query.

    ``on_error`` defaults to re-raising.
    """
    if limit is not None and limit <= 0:
        raise ValueError("limit must be a positive integer or None")

    fetch = None if limit is None else limit + 1
    pending = turns.undistilled_turns(limit=fetch)
    more_pending = limit is not None and len(pending) > limit
    batch = pending if limit is None else pending[:limit]
    if not batch:
        return DistillReport(more_pending=False)

    distilled = failed = 0
    for fact in batch:
        user_id = str(fact.metadata.get("user_id") or "jarvis")
        role = str(fact.metadata.get("role") or "user")
        started = time.monotonic()
        try:
            extractor.remember(f"{role.capitalize()}: {fact.text}", user_id=user_id)
        except Exception as exc:
            failed += 1
            if on_error is None:
                raise
            on_error(fact, exc)
            continue
        # Marked only after extraction succeeded. See the module docstring.
        turns.mark_distilled(fact)
        distilled += 1
        if on_distilled is not None:
            on_distilled(fact, time.monotonic() - started)

    return DistillReport(
        attempted=len(batch),
        distilled=distilled,
        failed=failed,
        # A turn that failed is still undistilled, so there is more to do even
        # if the peek said otherwise.
        more_pending=more_pending or failed > 0,
    )


def preview(text: str, width: int = 60) -> str:
    """A one-line, length-bounded rendering of a turn, for logs."""
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"
