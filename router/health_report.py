"""A provider-health snapshot the routing process writes and the bus reads.

Q10c, answered by Ali on 1 September 2026: the router's cooldown ledger is
**process-lifetime**, and **the executor** — the process that actually routes —
reports provider health. Both halves of that answer need this file.

Why a file at all
-----------------

``/status`` used to read ``app.state.provider_router.health``: the *bus's* own
router. The bus is enqueue-only and never routes, so that map was every
provider at its constructed defaults — ``last_status: None``, no cooldown —
for as long as the process lived. It did not report health, it reported the
absence of any attempt to find out, in a shape indistinguishable from
"everything is fine".

The routing process is a different process, so its ledger cannot be read
in-memory. This mirrors ``executor/heartbeat.py``, which exists for the same
reason and is written the same way: a small file, written best-effort, read
with an age bound, and fail-open on every error. A stale or missing snapshot
degrades ``/status`` to "nobody has reported", which is honest; nothing here
is ever allowed to break a poll loop or a status request.

Why the countdown is stored relative
------------------------------------

``ProviderHealth.cooldown_until`` is a ``time.monotonic()`` reading. Monotonic
clocks share no origin across processes — the bus reading the executor's
number would be comparing against an unrelated zero point. The snapshot
therefore stores *seconds remaining at write time* alongside a wall-clock
``reported_at``, and :func:`read` subtracts the elapsed time. That also makes
the file correct while the writer is idle: the countdown keeps ticking down
for the reader without needing a rewrite every second.

What is in it
-------------

Only what ``/status`` already exposed: status codes, a relative countdown, and
rate-limit headers. No keys, no endpoints, no request or response bodies. The
writer filters headers to ``retry-after`` and ``x-ratelimit-*`` before they
ever reach ``ProviderHealth`` (see ``routing._record_response_headers``).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

DEFAULT_REPORT_PATH = Path(".provider-health.json")

#: Older than this and the snapshot is treated as nobody having reported. Sized
#: like the heartbeat's window and for the same reason: the writer only rewrites
#: when something *material* changes, so a healthy, quiet router can legitimately
#: leave the file untouched for a long time. Ten minutes is long enough to ride
#: out that quiet and short enough that a stopped executor stops being believed.
DEFAULT_MAX_AGE_SECONDS = 600.0


def report_path(environ: Mapping[str, str] | None = None) -> Path:
    settings = os.environ if environ is None else environ
    return Path(settings.get("JARVIS_PROVIDER_HEALTH_REPORT", str(DEFAULT_REPORT_PATH)))


def material_state(snapshot: Mapping[str, Any]) -> tuple:
    """The part of a snapshot worth rewriting the file for.

    A raw snapshot differs on every poll because the countdown decrements, so
    comparing whole snapshots would rewrite the file several times a second
    and never skip a write. What actually changes meaning is a provider's last
    status, its rate-limit headers, and whether it is cooling down at all —
    the exact remaining seconds are reconstructed by :func:`read` from
    ``reported_at``.
    """
    return tuple(
        (
            name,
            entry.get("last_status"),
            tuple(sorted((entry.get("rate_limit_headers") or {}).items())),
            bool((entry.get("cooldown_seconds_remaining") or 0) > 0),
        )
        for name, entry in sorted(snapshot.items())
    )


def write(snapshot: Mapping[str, Any], path: Path | None = None) -> None:
    """Publish a snapshot. Never raises.

    Written to a sibling temp file and moved into place so a reader can never
    observe half a JSON document. An ``OSError`` costs ``/status`` one refresh
    and must never reach the caller — this is called from the executor's poll
    loop, and the same reasoning as ``heartbeat.touch`` applies.
    """
    target = path or report_path()
    document = {"reported_at": time.time(), "providers": dict(snapshot)}
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(document), encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass


def read(
    path: Path | None = None, *, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
) -> dict[str, dict[str, Any]] | None:
    """The last published snapshot with countdowns brought up to date.

    ``None`` means nobody has reported: no file, an unreadable or malformed
    one, or one older than ``max_age_seconds``. Callers must render that as
    "unreported" rather than as healthy — telling the two apart is the entire
    point of this module.
    """
    target = path or report_path()
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, Mapping):
        return None
    reported_at = document.get("reported_at")
    providers = document.get("providers")
    if not isinstance(reported_at, (int, float)) or not isinstance(providers, Mapping):
        return None

    age = max(0.0, time.time() - float(reported_at))
    if age > max_age_seconds:
        return None

    aged: dict[str, dict[str, Any]] = {}
    for name, entry in providers.items():
        if not isinstance(entry, Mapping):
            continue
        remaining = entry.get("cooldown_seconds_remaining")
        remaining = float(remaining) if isinstance(remaining, (int, float)) else 0.0
        aged[str(name)] = {
            "last_status": entry.get("last_status"),
            "cooldown_seconds_remaining": round(max(0.0, remaining - age), 3),
            "rate_limit_headers": dict(entry.get("rate_limit_headers") or {}),
            "reported": True,
            "reported_age_seconds": round(age, 3),
        }
    return aged
