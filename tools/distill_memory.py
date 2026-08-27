"""Fold stored conversation turns into Mem0 facts, offline.

The live reply path stores turns verbatim because Mem0's 8B fact extraction
costs 20-130s on this hardware and failed on 100% of live messages. This is
where that extraction actually happens: a batch pass, run when nothing is
waiting on a reply, over turns that have not been distilled yet.

Run it while the executor is idle. Ollama is a single serial resource — this
competes with live replies for exactly the same model, which is what starved
eight inbound messages on 26 August.

    .venv\\Scripts\\python.exe tools/distill_memory.py [--limit N] [--dry-run]

This is no longer the only thing that distills. The executor now runs a
``distill_memory`` job kind that works one turn at a time and yields to any
queued live work, which is what actually closed ``docs/state.md`` open blocker
1 — see ``executor/handlers/distill.py`` and the adversarial comparison of the
three candidate mechanisms saved at
``docs/consults/2026-08-27-distill-scheduling-mechanism/``.

This CLI stays, unchanged in behaviour, as the guarded manual entry point: it
still refuses to run while the executor is polling, it still takes ``--force``,
and it still drains the whole backlog in one go rather than a turn at a time.
Both paths share ``memory.distill.distill_turns``, so the "mark distilled only
after extraction succeeded" invariant cannot drift between them.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from executor.heartbeat import refuse_if_executor_is_live
from memory.conversation import open_conversation_memory
from memory.distill import distill_turns, preview
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
                logger.info("  would distill %s  %s", fact.created_at.date(), preview(fact.text))
            return 0

        mem0 = open_local_mem0_memory(args.database)
        try:
            report = distill_turns(
                conversation,
                mem0,
                limit=args.limit,
                on_distilled=lambda fact, seconds: logger.info(
                    "  distilled in %.1fs  %s", seconds, preview(fact.text)
                ),
                # A human is watching this output, so a failed turn is logged
                # and the rest of the batch still runs. The executor handler
                # deliberately does the opposite and lets failures propagate
                # into the queue's retry path.
                on_error=lambda fact, exc: logger.warning(
                    "  failed %s (%s)", preview(fact.text), type(exc).__name__
                ),
            )
        finally:
            mem0.close()

        logger.info(
            "done: %d distilled, %d failed, %d remaining",
            report.distilled,
            report.failed,
            report.attempted - report.distilled,
        )
        return 0 if report.distilled or not report.failed else 1
    finally:
        conversation.close()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
