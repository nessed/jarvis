"""Adapts the production Mem0 runtime to the backfill's ``FactSink`` protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Mem0BackfillSink:
    """Route backfilled text through the same ``remember()`` the bus uses.

    A chunk's ``source`` (the file it came from) has no home in
    ``Mem0Memory.remember``'s signature, so it travels in ``metadata``
    instead. ``user_id`` is fixed for the whole run: it must match the
    identity ``recall()`` will later be queried under, which the caller
    supplies explicitly rather than this module guessing at a phone number.
    """

    memory: Any
    user_id: str

    def remember(self, text: str, source: str, *, metadata: Mapping[str, Any] | None = None) -> object:
        return self.memory.remember(
            text,
            user_id=self.user_id,
            metadata={"source": source, **dict(metadata or {})},
        )
