"""Pull-based laptop executor integration points."""

from collections.abc import Mapping, Sequence
from typing import Any

from router import RoutedResult, route


def poll_once() -> None:
    """Reserve the executor integration point without running work yet."""
    return None


async def request_completion(
    task_profile: str, messages: Sequence[Mapping[str, Any]], *, urgent: bool = False
) -> RoutedResult:
    """Give executor jobs the provider router's single async entry point."""
    return await route(task_profile, messages, urgent=urgent)
