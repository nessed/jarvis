"""Blueprint 1.4's review loop: see what JARVIS remembered, delete what is wrong.

    .venv\\Scripts\\python.exe tools/review_facts.py list [--source S] [--limit N] [--offset N]
    .venv\\Scripts\\python.exe tools/review_facts.py search --text SUBSTR [--source S] [--limit N]
    .venv\\Scripts\\python.exe tools/review_facts.py forget <id> [<id> ...] [--dry-run] [--force] [--yes]
    .venv\\Scripts\\python.exe tools/review_facts.py forget --pattern "substring:forwarded video" [--dry-run]

``list``/``search`` are read-only and never touch the executor liveness guard.
``forget`` always previews what it would remove before doing anything;
``--dry-run`` stops there. A real deletion refuses to start while the
executor is polling (mutating the fact store mid-recall is a race), the same
guard ``distill_memory.py``/``run_backfill.py`` use, with the same
``--force`` override. Deletion never runs without an explicit "yes" -- either
typed at the prompt, or ``--yes`` for scripted use -- because it is
irreversible.

Naming *what* to forget is Ali's call. ``--pattern`` accepts the same
``<kind>:<value>`` syntax ``ingest/noise_patterns.txt`` uses
(``substring:...`` / ``regex:...`` / ``source:...``), so a pattern that stops
future noise can also be pointed at this command to retroactively clean what
is already stored.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.noise import NoisePatternError, parse_pattern
from memory.distill import preview
from memory.review import (
    ReviewStore,
    delete_facts,
    facts_matching_pattern,
    list_recent,
    open_review_store,
    search,
)
from memory.types import Fact
from executor.heartbeat import refuse_if_executor_is_live

logger = logging.getLogger("review_facts")

DEFAULT_DATABASE = "memory.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", default=None, help="memory database path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list recent facts, newest first")
    list_parser.add_argument("--source", default=None)
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.add_argument("--offset", type=int, default=0)

    search_parser = subparsers.add_parser("search", help="search facts by text and/or source")
    search_parser.add_argument("--text", default=None, help="substring to match, case-insensitive")
    search_parser.add_argument("--source", default=None)
    search_parser.add_argument("--limit", type=int, default=None)

    forget_parser = subparsers.add_parser("forget", help="delete one or more facts")
    forget_parser.add_argument("ids", nargs="*", help="fact id(s) to delete")
    forget_parser.add_argument(
        "--pattern", default=None, help="'<kind>:<value>' pattern; deletes every currently-matching fact"
    )
    forget_parser.add_argument("--dry-run", action="store_true", help="show what would be deleted, change nothing")
    forget_parser.add_argument("--force", action="store_true", help="delete even while the executor is polling")
    forget_parser.add_argument("--yes", action="store_true", help="skip the interactive confirmation prompt")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.command == "list":
        return _run_list(args)
    if args.command == "search":
        return _run_search(args)
    return _run_forget(args)


def _run_list(args: argparse.Namespace) -> int:
    review = open_review_store(args.database or DEFAULT_DATABASE)
    try:
        facts = list_recent(review, source=args.source, limit=args.limit, offset=args.offset)
        _print_facts(facts)
        return 0
    finally:
        review.close()


def _run_search(args: argparse.Namespace) -> int:
    if not args.text and not args.source:
        logger.error("search requires --text and/or --source")
        return 2
    review = open_review_store(args.database or DEFAULT_DATABASE)
    try:
        facts = search(review, text_contains=args.text, source=args.source, limit=args.limit)
        _print_facts(facts)
        return 0
    finally:
        review.close()


def _run_forget(args: argparse.Namespace) -> int:
    if bool(args.ids) == bool(args.pattern):
        logger.error("forget requires either fact id(s) or --pattern, not both or neither")
        return 2

    pattern = None
    if args.pattern:
        try:
            pattern = parse_pattern(args.pattern)
        except NoisePatternError as exc:
            logger.error(str(exc))
            return 2

    review = open_review_store(args.database or DEFAULT_DATABASE)
    try:
        targets = _resolve_ids(review, args.ids) if args.ids else facts_matching_pattern(review, pattern)

        if not targets:
            logger.info("no facts match; nothing to delete")
            return 0

        logger.info("would delete %d fact(s):", len(targets))
        for fact in targets:
            logger.info("  %s", _fact_line(fact))

        if args.dry_run:
            return 0

        if not args.force:
            refusal = refuse_if_executor_is_live("Forgetting")
            if refusal:
                logger.error(refusal)
                return 2

        if not args.yes and not _confirm(f"Delete {len(targets)} fact(s)? [y/N]: "):
            logger.info("aborted; nothing deleted")
            return 0

        results = delete_facts(review, [fact.id for fact in targets])
        deleted = sum(1 for existed in results.values() if existed)
        logger.info("deleted %d fact(s)", deleted)
        return 0
    finally:
        review.close()


def _resolve_ids(review: ReviewStore, ids: list[str]) -> list[Fact]:
    targets: list[Fact] = []
    for fact_id in ids:
        fact = review.store.get(fact_id)
        if fact is None:
            logger.warning("fact %s not found", fact_id)
            continue
        targets.append(fact)
    return targets


def _print_facts(facts: list[Fact]) -> None:
    if not facts:
        logger.info("no facts found")
        return
    for fact in facts:
        logger.info(_fact_line(fact))


def _fact_line(fact: Fact) -> str:
    return f"{fact.id}  {fact.created_at.date()}  {fact.source}  {preview(fact.text)}"


def _confirm(prompt: str) -> bool:
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
