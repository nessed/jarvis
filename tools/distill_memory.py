"""Fold stored conversation turns into Mem0 facts, offline.

The live reply path stores turns verbatim because Mem0's 8B fact extraction
costs 20-130s on this hardware and failed on 100% of live messages. This is
where that extraction actually happens: a batch pass, run when nothing is
waiting on a reply, over turns that have not been distilled yet.

Run it while the executor is idle. Ollama is a single serial resource — this
competes with live replies for exactly the same model, which is what starved
eight inbound messages on 26 August.

    .venv\\Scripts\\python.exe tools/distill_memory.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from executor.heartbeat import refuse_if_executor_is_live
from memory.conversation import open_conversation_memory
from memory.runtime import open_local_mem0_memory

logger = logging.getLogger("distill")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None, help="stop after N turns")
    parser.add_argument("--dry-run", action="store_true", help="report what would run, change nothing")
    parser.add_argument("--database", default=None, help="memory database path")
    parser.add_argument("--force", action="store_true", help="run even while the executor is polling")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()

    if not args.force and not args.dry_run:
        refusal = refuse_if_executor_is_live("Distilling")
        if refusal:
            logger.error(refusal)
            return 2

    conversation = open_conversation_memory(args.database)
    try:
        pending = conversation.undistilled_turns(limit=args.limit)
        if not pending:
            logger.info("nothing to distill")
            return 0

        logger.info("%d turn(s) to distill", len(pending))
        if args.dry_run:
            for fact in pending:
                logger.info("  would distill %s  %s", fact.created_at.date(), _preview(fact.text))
            return 0

        mem0 = open_local_mem0_memory(args.database)
        distilled = failed = 0
        try:
            for fact in pending:
                user_id = str(fact.metadata.get("user_id") or "jarvis")
                role = str(fact.metadata.get("role") or "user")
                started = time.monotonic()
                try:
                    mem0.remember(f"{role.capitalize()}: {fact.text}", user_id=user_id)
                except Exception as exc:
                    failed += 1
                    logger.warning("  failed %s (%s)", _preview(fact.text), type(exc).__name__)
                    continue
                # Mark only after extraction succeeded, so a crash or a timeout
                # leaves the turn eligible for the next run instead of silently
                # dropping it.
                conversation.mark_distilled(fact)
                distilled += 1
                logger.info("  distilled in %.1fs  %s", time.monotonic() - started, _preview(fact.text))
        finally:
            mem0.close()

        logger.info("done: %d distilled, %d failed, %d remaining", distilled, failed, len(pending) - distilled)
        return 0 if distilled or not failed else 1
    finally:
        conversation.close()


def _preview(text: str, width: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
