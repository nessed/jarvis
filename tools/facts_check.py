"""The blueprint's own anti-rot check: re-verify its volatile provider claims.

``docs/blueprint.md``'s Ongoing section specifies this and it was never built:

    a monthly facts-check job -- re-verify the Agent SDK pause, DeepSeek
    rates, free-model rosters, promo expiries, and write you a one-page diff
    report.

It is the mechanism that would have caught the Claude promo expiry and the
Groq/Cerebras model retirements that were already wrong on the day the
blueprint was written. The 1 Sep 2026 docs audit found ~12% of checkable
claims had drifted in four days.

    .venv\\Scripts\\python.exe -m tools.facts_check
    .venv\\Scripts\\python.exe -m tools.facts_check --claim deepseek-pricing
    .venv\\Scripts\\python.exe -m tools.facts_check --dry-run

What it does **not** do
-----------------------

**It never edits the blueprint.** It produces a diff and writes a dated report
to ``docs/tasks/facts-check-reports/``. Blueprint edits are decisions and go
through Q10-style approval, so a tool that quietly rewrote a spec claim
because a marketing page changed its wording would be exactly the wrong thing.

**It sends nothing.** Every request is an unauthenticated GET of a public
page. No key is read, so no key can leak, and nothing here can spend money or
change an account. A page that needs a login is reported as ``unverifiable``
rather than worked around.

How a claim is checked
----------------------

A claim records what the blueprint asserts plus markers that must still be
present -- and, where the drift is a *removal*, markers that must now be
absent. A marker is deliberately a short literal, not a regex over prose:
these pages rewrite their sentences constantly, and a check that goes yellow
on a reworded paragraph gets ignored within two months.

Three verdicts, and the third is a first-class outcome, not a failure:

``unchanged``    every marker still holds.
``changed``      at least one marker broke. Read the blueprint line.
``unverifiable`` the page could not be fetched or read -- login wall, JS-only
                 render, 404, timeout. Check it by hand.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPORT_DIR = Path("docs/tasks/facts-check-reports")

#: How old the newest report may get before a run says so out loud. The
#: blueprint says monthly, and ``board-audit``'s guide already tells an agent
#: to run this when the newest report is older than this.
STALE_AFTER_DAYS = 30

UNCHANGED = "unchanged"
CHANGED = "changed"
UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class Claim:
    """One volatile blueprint assertion, and how to tell if it still holds."""

    id: str
    topic: str
    #: What the blueprint says today, in one line, as a human reads it.
    recorded: str
    #: Where in docs/blueprint.md it says it.
    blueprint_ref: str
    source_url: str
    #: Literals that must still appear on the page.
    expect_present: tuple[str, ...] = ()
    #: Literals whose *appearance* means the claim broke. Used where the drift
    #: would be an addition -- a free DeepSeek variant returning to a roster,
    #: a paused billing split un-pausing.
    expect_absent: tuple[str, ...] = ()
    #: Set when the source is known to need a login or to render client-side.
    #: Such a claim is reported unverifiable without a request being made.
    needs_human: str = ""


# ---------------------------------------------------------------------------
# The checklist
#
# Every ``recorded`` line below is quoted from docs/blueprint.md, not
# paraphrased, so a reader can diff the report against the spec without
# opening both. Markers are lowercase; matching is case-insensitive.
# ---------------------------------------------------------------------------

CLAIMS: tuple[Claim, ...] = (
    Claim(
        id="agent-sdk-billing-pause",
        topic="Claude / Agent SDK",
        recorded=(
            "The June 15 Agent SDK billing split is still paused -- Agent SDK, "
            "claude -p and third-party app usage draw from subscription limits."
        ),
        blueprint_ref="blueprint.md:10, :23",
        source_url="https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan",
        # The article's own wording, read 2 Sep 2026: "Update June 15: We're
        # pausing the changes to Claude Agent SDK usage described below."
        # Matching that sentence, not the bare word: "pause" is not a
        # substring of "pausing", and a marker that misses the live text
        # reports drift that is not there. The first run of this tool did
        # exactly that.
        expect_present=("pausing the changes", "still draw from your subscription"),
    ),
    Claim(
        id="claude-weekly-promo",
        topic="Claude / Agent SDK",
        recorded=(
            "The +50% weekly-limit promo (running since May 13) is extended "
            "through ~Aug 31 2026. When it lapses, weekly walls arrive ~1/3 sooner."
        ),
        blueprint_ref="blueprint.md:25",
        source_url="https://support.claude.com/en/articles/9797557-usage-limit-best-practices",
        needs_human=(
            "The promo and its expiry are announced in-product and in changelog "
            "posts, not on a stable page this tool can diff. Today is already past "
            "the ~Aug 31 2026 date the blueprint records, so treat it as lapsed "
            "until Ali confirms from his own usage screen."
        ),
    ),
    Claim(
        id="deepseek-pricing",
        topic="DeepSeek",
        recorded=(
            "V4-Flash $0.22 in / $0.66 out per 1M off-peak, $0.44/$1.32 peak; "
            "V4-Pro exactly 3x Flash. Peak windows 01:00-04:00 and 06:00-10:00 UTC."
        ),
        blueprint_ref="blueprint.md:66-68",
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
        # The off-peak input price is on the page as a literal. DeepSeek has
        # signalled further price changes without dates, so this is the marker
        # most likely to break first, and it should.
        expect_present=("0.22", "off-peak"),
    ),
    Claim(
        id="deepseek-model-names",
        topic="DeepSeek",
        recorded=(
            "Lineup is deepseek-v4-flash and deepseek-v4-pro. The old "
            "deepseek-chat / deepseek-reasoner names were retired July 24 2026."
        ),
        blueprint_ref="blueprint.md:65",
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
        expect_present=("deepseek-v4-flash",),
        # A retired name coming back is what silently un-breaks the old guides
        # this blueprint line exists to warn against.
        expect_absent=("deepseek-reasoner",),
    ),
    Claim(
        id="groq-rate-limits",
        topic="Groq",
        recorded=(
            "Limits are per-model with TPD caps: gpt-oss-120b/20b ~30 RPM, "
            "1,000 RPD, 8K TPM, 200K TPD (Aug 2026 snapshot). Org-level."
        ),
        blueprint_ref="blueprint.md:36-42",
        source_url="https://console.groq.com/docs/rate-limits",
        # Not the numbers. The blueprint's own rule is to read those from
        # x-ratelimit-* headers at runtime. What is checked is that the shape
        # still holds: per-day token caps, and headers to read them from.
        expect_present=("tokens per day", "x-ratelimit"),
    ),
    Claim(
        id="groq-whisper-free",
        topic="Groq",
        recorded="Whisper v3 Turbo STT still free (~2,000 audio req/day).",
        blueprint_ref="blueprint.md:41",
        source_url="https://console.groq.com/docs/speech-to-text",
        expect_present=("whisper-large-v3-turbo",),
    ),
    Claim(
        id="cerebras-free-tier",
        topic="Cerebras",
        recorded=(
            "1M tokens/day free, 8K context cap, 5 RPM / 30K TPM; catalogue "
            "narrowed to gpt-oss-120b and GLM-4.7."
        ),
        blueprint_ref="blueprint.md:45-46",
        source_url="https://inference-docs.cerebras.ai/support/rate-limits",
        # The catalogue half is checkable; the RPM/TPM numbers live in a table
        # this crude reader does not see, which the report says out loud rather
        # than implying they were confirmed.
        #
        # ``glm`` is in here because it is doing real work, not because it is
        # safe: neither the rate-limits page nor models/overview mentioned GLM
        # on 2 Sep 2026, while the blueprint says the catalogue is "gpt-oss-120b
        # and GLM-4.7". If that is a genuine removal, the routing lane's model
        # choice is narrower than the spec assumes, and this is the marker that
        # says so every month until someone rules on it.
        expect_present=("gpt-oss-120b", "free tier", "glm"),
    ),
    Claim(
        id="gemini-free-tier",
        topic="Gemini (AI Studio)",
        recorded=(
            "Flash/Flash-Lite free tier for long-context + vision. Free prompts "
            "may train Google's models -- no private memory content here."
        ),
        blueprint_ref="blueprint.md:48-49",
        source_url="https://ai.google.dev/gemini-api/docs/rate-limits",
        expect_present=("free tier", "flash"),
    ),
    Claim(
        id="openrouter-free-roster",
        topic="OpenRouter",
        recorded=(
            "openrouter/free auto-router exists; mid-2026 snapshots show zero "
            "free DeepSeek or Gemini variants on the roster."
        ),
        blueprint_ref="blueprint.md:52-54",
        # The public models endpoint, no key required. The one claim on this
        # list checked against data rather than prose.
        source_url="https://openrouter.ai/api/v1/models",
        expect_present=("openrouter/free",),
        expect_absent=("deepseek-r1:free",),
    ),
    Claim(
        id="openrouter-limits",
        topic="OpenRouter",
        recorded=(
            "50 req/day free; a one-time $10 credit purchase raises it to "
            "1,000/day permanently; 20 RPM fixed either way."
        ),
        blueprint_ref="blueprint.md:52",
        source_url="https://openrouter.ai/docs/api-reference/limits",
        needs_human=(
            "The daily allowance is account-scoped. The public docs page describes "
            "402/429 handling and never states the numbers; reading them needs the "
            "key endpoint, and this tool sends no credentials by design."
        ),
    ),
    Claim(
        id="nvidia-nim-free",
        topic="NVIDIA NIM",
        recorded=(
            "100+ hosted open models at ~40 RPM, free, OpenAI-compatible at "
            "integrate.api.nvidia.com/v1. Geo-blocked from Pakistan."
        ),
        blueprint_ref="blueprint.md:56, :322",
        source_url="https://build.nvidia.com/models",
        needs_human=(
            "build.nvidia.com renders its catalogue client-side, and the endpoint is "
            "geo-blocked from Pakistan anyway -- a fetch from this machine proves "
            "nothing either way."
        ),
    ),
    Claim(
        id="oracle-always-free",
        topic="Oracle Cloud",
        recorded=(
            "Always Free: 2 OCPU / 12GB Ampere A1 (1,500 OCPU-hrs + 9,000 GB-hrs/mo), "
            "200GB block storage, 10TB egress."
        ),
        blueprint_ref="blueprint.md:120",
        source_url="https://www.oracle.com/cloud/free/",
        # Phase 4 rests on this tier existing at all. Ampere is the marker
        # that matters: an Always Free tier without A1 is a different plan.
        expect_present=("always free", "ampere"),
    ),
)


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fetched:
    """What a fetcher returns: page text, or a reason it could not be read."""

    text: str = ""
    error: str = ""


Fetcher = Callable[[str], Fetched]


@dataclass(frozen=True)
class Finding:
    """One claim's outcome."""

    claim: Claim
    verdict: str
    detail: str = ""
    broken_markers: tuple[str, ...] = field(default_factory=tuple)


def check_claim(claim: Claim, fetch: Fetcher) -> Finding:
    """Check one claim. Never raises: a broken source is a verdict, not a crash."""
    if claim.needs_human:
        return Finding(claim, UNVERIFIABLE, claim.needs_human)

    try:
        fetched = fetch(claim.source_url)
    except Exception as exc:  # a fetcher is third-party code; treat it as data
        return Finding(claim, UNVERIFIABLE, f"fetch raised {type(exc).__name__}")

    if fetched.error:
        return Finding(claim, UNVERIFIABLE, fetched.error)
    if not fetched.text.strip():
        return Finding(claim, UNVERIFIABLE, "the page came back empty")

    haystack = fetched.text.lower()
    missing = tuple(m for m in claim.expect_present if m.lower() not in haystack)
    appeared = tuple(m for m in claim.expect_absent if m.lower() in haystack)

    if not missing and not appeared:
        return Finding(claim, UNCHANGED)

    parts = []
    if missing:
        parts.append("no longer says " + ", ".join(repr(m) for m in missing))
    if appeared:
        parts.append("now says " + ", ".join(repr(m) for m in appeared))
    return Finding(claim, CHANGED, "; ".join(parts), missing + appeared)


def check_all(claims: Sequence[Claim], fetch: Fetcher) -> list[Finding]:
    return [check_claim(claim, fetch) for claim in claims]


# ---------------------------------------------------------------------------
# The real fetcher
# ---------------------------------------------------------------------------


_TAG = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_MARKUP = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def strip_markup(html: str) -> str:
    """Reduce a page to its visible text.

    Deliberately crude -- no parser dependency. Script and style bodies go
    first, because a marker found inside a bundled JS blob is not the page
    saying anything, and that false 'unchanged' is the failure mode that would
    make this whole tool untrustworthy.

    Whitespace is collapsed afterwards, and that step is load-bearing rather
    than cosmetic. A tag becomes a space, so ``<b>Always</b> <i>Free</i>``
    leaves three spaces between the two words and a marker like
    ``"always free"`` would never match -- reporting drift on a page that had
    not changed at all. Half this checklist's markers are multi-word.
    """
    without_code = _TAG.sub(" ", html)
    return _WHITESPACE.sub(" ", _MARKUP.sub(" ", without_code)).strip()


def http_fetch(url: str, *, timeout_seconds: float = 20.0) -> Fetched:
    """Unauthenticated GET. No key is read, so no key can leak."""
    import httpx

    try:
        response = httpx.get(
            url,
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"user-agent": "jarvis-facts-check/1.0 (+local, read-only)"},
        )
    except httpx.HTTPError as exc:
        return Fetched(error=f"could not reach the page ({type(exc).__name__})")

    if response.status_code == 403:
        return Fetched(error="HTTP 403 -- the page refuses an unauthenticated read")
    if response.status_code == 404:
        return Fetched(error="HTTP 404 -- the recorded URL is gone; find the new one")
    if response.status_code >= 400:
        return Fetched(error=f"HTTP {response.status_code}")

    body = response.text
    if "application/json" in response.headers.get("content-type", ""):
        return Fetched(text=body)
    return Fetched(text=strip_markup(body))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report_paths(report_dir: Path) -> list[Path]:
    return sorted(report_dir.glob("*.md")) if report_dir.exists() else []


def newest_report_age_days(report_dir: Path, *, today: date) -> int | None:
    """Age in days of the newest dated report, or ``None`` if there are none.

    The date is read off the filename rather than the filesystem, because a
    checkout, a copy, or a rebase rewrites mtimes and would quietly reset the
    staleness clock this tool exists to keep.
    """
    newest: date | None = None
    for path in report_paths(report_dir):
        try:
            stamp = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if newest is None or stamp > newest:
            newest = stamp
    return None if newest is None else (today - newest).days


def staleness_line(age_days: int | None) -> str:
    """The nudge printed at the top of every run. There is no scheduler."""
    if age_days is None:
        return "No previous report. This is the first facts-check run."
    if age_days > STALE_AFTER_DAYS:
        return (
            f"Newest report is {age_days} days old -- past the {STALE_AFTER_DAYS}-day "
            "monthly cadence the blueprint asks for."
        )
    return f"Newest report is {age_days} day(s) old."


def render_report(findings: Sequence[Finding], *, run_date: date, age_days: int | None) -> str:
    """The one-page diff. Changed first, because that is the only actionable part."""
    by_verdict = {
        verdict: [f for f in findings if f.verdict == verdict]
        for verdict in (CHANGED, UNVERIFIABLE, UNCHANGED)
    }

    lines = [
        f"# Facts check — {run_date.isoformat()}",
        "",
        f"{len(by_verdict[CHANGED])} changed · "
        f"{len(by_verdict[UNVERIFIABLE])} unverifiable · "
        f"{len(by_verdict[UNCHANGED])} unchanged, of {len(findings)} claims.",
        "",
        staleness_line(age_days),
        "",
        "This report never edits `docs/blueprint.md`. Every line below is a diff "
        "for Ali to rule on.",
        "",
    ]

    lines += ["## Changed", ""]
    if not by_verdict[CHANGED]:
        lines += ["Nothing. Every checkable claim still holds.", ""]
    for finding in by_verdict[CHANGED]:
        lines += [
            f"### {finding.claim.id} — {finding.claim.topic}",
            "",
            f"**Blueprint says** ({finding.claim.blueprint_ref}): {finding.claim.recorded}",
            "",
            f"**The page** {finding.detail}.",
            "",
            f"Source: {finding.claim.source_url}",
            "",
        ]

    lines += ["## Unverifiable — check by hand", ""]
    if not by_verdict[UNVERIFIABLE]:
        lines += ["Nothing. Every claim had a readable source.", ""]
    for finding in by_verdict[UNVERIFIABLE]:
        lines += [
            f"- **{finding.claim.id}** ({finding.claim.topic}) — {finding.detail}",
            f"  - Blueprint ({finding.claim.blueprint_ref}): {finding.claim.recorded}",
            f"  - {finding.claim.source_url}",
        ]
    lines += [""]

    lines += ["## Unchanged", ""]
    if not by_verdict[UNCHANGED]:
        lines += ["Nothing could be positively confirmed this run.", ""]
    for finding in by_verdict[UNCHANGED]:
        lines += [f"- `{finding.claim.id}` — {finding.claim.topic}"]
    lines += [""]

    return "\n".join(lines)


def write_report(text: str, *, report_dir: Path, run_date: date) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{run_date.isoformat()}.md"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _force_utf8_output() -> None:
    """cp1252 is this machine's default and provider pages are full of
    en dashes and currency signs it cannot encode."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


def select_claims(claims: Sequence[Claim], wanted: Iterable[str]) -> list[Claim]:
    wanted = list(wanted)
    if not wanted:
        return list(claims)
    known = {claim.id for claim in claims}
    unknown = [name for name in wanted if name not in known]
    if unknown:
        raise SystemExit(
            f"error: no such claim(s): {', '.join(unknown)}\n"
            f"known: {', '.join(sorted(known))}"
        )
    return [claim for claim in claims if claim.id in set(wanted)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-verify the blueprint's volatile provider claims and write a diff report."
    )
    parser.add_argument(
        "--claim", action="append", default=[], metavar="ID",
        help="check only this claim (repeatable); default is all of them",
    )
    parser.add_argument(
        "--report-dir", type=Path, default=REPORT_DIR,
        help=f"where dated reports go (default: {REPORT_DIR})",
    )
    parser.add_argument(
        "--no-write", action="store_true",
        help="print the report instead of writing it",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list what would be checked and where from; fetch nothing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = build_parser().parse_args(argv)
    # Local date, not UTC: every other dated artifact under docs/ is written
    # in Ali's timezone, and a report filed as "yesterday" because PKT is
    # UTC+5 reads as a stale report to whoever opens the directory next.
    return run(args, fetch=http_fetch, today=date.today())


def run(args: argparse.Namespace, *, fetch: Fetcher, today: date) -> int:
    """The CLI body, with the clock and the network injected for tests."""
    claims = select_claims(CLAIMS, args.claim)
    age = newest_report_age_days(args.report_dir, today=today)
    print(staleness_line(age))
    print("")

    if args.dry_run:
        for claim in claims:
            where = claim.needs_human and "(needs a human)" or claim.source_url
            print(f"  {claim.id:<28} {where}")
        return 0

    findings = []
    for claim in claims:
        finding = check_claim(claim, fetch)
        findings.append(finding)
        print(f"  {finding.verdict:<13} {finding.claim.id}")

    report = render_report(findings, run_date=today, age_days=age)
    if args.no_write:
        print("")
        print(report)
        return 0

    path = write_report(report, report_dir=args.report_dir, run_date=today)
    changed = sum(1 for f in findings if f.verdict == CHANGED)
    print("")
    print(f"{changed} changed. Report: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
