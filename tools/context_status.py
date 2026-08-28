"""Regenerate the status block in docs/context.md from git and the test cache.

Everything this writes is derivable. Hand-maintaining it is what made the old
469-line context.md wrong: agents kept a copy of `git log` by hand, appended
new sections at the bottom, and never re-audited the top. The file claimed
fixes were uncommitted days after they landed and its checkpoint list ran five
commits behind HEAD.

So no agent writes this block. The pre-commit hook regenerates it and stages
it, every commit, silently.

Usage
-----
    python tools/context_status.py --write     rewrite the block in place
    python tools/context_status.py --check     exit 1 if the block has rotted
    python tools/context_status.py --record-suite "117 passed" [--live "1 passed"]

``--record-suite`` caches a test summary line into .context-status.json so
``--write`` never has to run pytest itself. The hook records the suite it
already ran.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTEXT = REPO_ROOT / "docs" / "context.md"
CACHE = REPO_ROOT / ".context-status.json"

BEGIN = "<!-- BEGIN GENERATED: tools/context_status.py. Do not edit by hand. -->"
END = "<!-- END GENERATED -->"

COMMIT_COUNT = 8

# The block always names the commit the work was built on, so one commit of lag
# is normal. More than this means it stopped being regenerated.
MAX_LAG = 2


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def working_tree() -> str:
    """Staged and unstaged paths, ignoring untracked noise."""
    porcelain = git("status", "--porcelain")
    if not porcelain:
        return "clean"
    lines = [ln for ln in porcelain.splitlines() if not ln.startswith("??")]
    untracked = sum(1 for ln in porcelain.splitlines() if ln.startswith("??"))
    if not lines:
        return f"clean ({untracked} untracked)" if untracked else "clean"
    shown = [f"  {ln}" for ln in lines[:12]]
    if len(lines) > 12:
        shown.append(f"  ...and {len(lines) - 12} more")
    tail = f" (plus {untracked} untracked)" if untracked else ""
    return f"{len(lines)} changed{tail}\n\n```\n" + "\n".join(shown) + "\n```"


def build_block() -> str:
    cache = load_cache()
    head = git("log", "-1", "--format=%h %s") or "(no commits)"
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    commits = git("log", f"-{COMMIT_COUNT}", "--format=- `%h` %s  _(%ad)_", "--date=short")
    ahead = git("rev-list", "--count", "@{u}..HEAD")
    behind = git("rev-list", "--count", "HEAD..@{u}")

    if ahead == "" and behind == "":
        sync = "no upstream configured"
    elif ahead == "0" and behind == "0":
        sync = "in sync with origin"
    else:
        sync = f"{ahead or '0'} ahead, {behind or '0'} behind origin"

    offline = cache.get("offline", "not recorded")
    offline_date = cache.get("offline_date", "")
    live = cache.get("live", "not recorded")
    live_date = cache.get("live_date", "")

    return "\n".join([
        BEGIN,
        "",
        f"**HEAD** `{head}` on `{branch}`, {sync}.",
        "",
        f"**Working tree:** {working_tree()}",
        "",
        f"**Offline suite:** {offline}" + (f" _(recorded {offline_date})_" if offline_date else ""),
        "",
        f"**Live acceptance suite:** {live}" + (f" _(recorded {live_date})_" if live_date else ""),
        "",
        "**Recent commits**",
        "",
        commits or "- (none)",
        "",
        END,
    ])


def splice(text: str, block: str) -> str:
    start = text.find(BEGIN)
    end = text.find(END)
    if start == -1 or end == -1:
        raise SystemExit(
            "docs/context.md has no generated block. Add the BEGIN and END "
            "markers before running this."
        )
    return text[:start] + block + text[end + len(END):]


def check(current: str) -> int:
    """Is the block genuinely rotten?

    The block is written by the pre-commit hook, so it names the commit the
    work was built on, not the commit that carries it. Being exactly one commit
    behind is normal and always true right after a commit. Byte-comparing
    against a fresh block would therefore fail constantly and teach everyone to
    ignore it.

    What actually matters is the failure this tool exists to prevent: a block
    that has drifted several commits behind, or that was hand-edited into
    something the tool never produced.
    """
    if BEGIN not in current or END not in current:
        print("docs/context.md has no generated block", file=sys.stderr)
        return 1

    block = current.split(BEGIN, 1)[1].split(END, 1)[0]
    recorded = re.search(r"\*\*HEAD\*\* `([0-9a-f]{7,40}) ", block)
    if not recorded:
        print("generated block has no HEAD line; it was hand-edited", file=sys.stderr)
        return 1

    sha = recorded.group(1)
    if not git("cat-file", "-t", sha):
        print(f"generated block names {sha}, which is not a commit in this repo", file=sys.stderr)
        return 1

    behind = git("rev-list", "--count", f"{sha}..HEAD")
    if behind and int(behind) > MAX_LAG:
        print(
            f"generated block is {behind} commits behind HEAD; run --write",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate the context.md status block.")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--record-suite", metavar="SUMMARY")
    parser.add_argument("--live", metavar="SUMMARY")
    args = parser.parse_args()

    if args.record_suite or args.live:
        cache = load_cache()
        today = date.today().isoformat()
        if args.record_suite:
            cache["offline"] = args.record_suite.strip()
            cache["offline_date"] = today
        if args.live:
            cache["live"] = args.live.strip()
            cache["live_date"] = today
        CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        if not (args.write or args.check):
            return 0

    if not CONTEXT.exists():
        print("docs/context.md is missing", file=sys.stderr)
        return 1

    current = CONTEXT.read_text(encoding="utf-8")

    if args.check:
        return check(current)

    updated = splice(current, build_block())

    if args.write:
        if updated != current:
            CONTEXT.write_text(updated, encoding="utf-8", newline="")
            print("refreshed docs/context.md status block", file=sys.stderr)
        return 0

    print(build_block())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
