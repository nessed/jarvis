"""Tests for the blueprint's anti-rot facts check.

Every test fakes the fetcher. Nothing here touches the network: a suite whose
result depends on whether Groq's docs site is up would be worse than no suite,
because it would train everyone to ignore a red run.

The behaviour worth guarding hardest is that ``unverifiable`` is a real
verdict. A checker that quietly reports "unchanged" when it could not read the
page is the exact failure this tool exists to prevent.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pytest

from tools.facts_check import (
    CHANGED,
    CLAIMS,
    STALE_AFTER_DAYS,
    UNCHANGED,
    UNVERIFIABLE,
    Claim,
    Fetched,
    Finding,
    build_parser,
    check_all,
    check_claim,
    newest_report_age_days,
    render_report,
    run,
    select_claims,
    staleness_line,
    strip_markup,
    write_report,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def fetcher(pages: dict[str, Fetched]):
    """A fetcher over a fixed page table. Unknown URLs are a 404-shaped error."""

    def fetch(url: str) -> Fetched:
        return pages.get(url, Fetched(error="HTTP 404 -- the recorded URL is gone"))

    return fetch


def exploding_fetcher(url: str) -> Fetched:
    raise RuntimeError("network is on fire")


def claim(**overrides) -> Claim:
    base = dict(
        id="test-claim",
        topic="Test",
        recorded="the sky is blue",
        blueprint_ref="blueprint.md:1",
        source_url="https://example.test/page",
        expect_present=("blue",),
    )
    base.update(overrides)
    return Claim(**base)


# ---------------------------------------------------------------------------
# Checking one claim
# ---------------------------------------------------------------------------


def test_a_present_marker_is_unchanged() -> None:
    fetch = fetcher({"https://example.test/page": Fetched(text="the sky is Blue today")})

    assert check_claim(claim(), fetch).verdict == UNCHANGED


def test_matching_is_case_insensitive() -> None:
    """Provider pages retitle and recapitalise constantly; that is not drift."""
    fetch = fetcher({"https://example.test/page": Fetched(text="THE SKY IS BLUE")})

    assert check_claim(claim(), fetch).verdict == UNCHANGED


def test_a_missing_marker_is_changed_and_names_it() -> None:
    fetch = fetcher({"https://example.test/page": Fetched(text="the sky is green")})

    finding = check_claim(claim(), fetch)

    assert finding.verdict == CHANGED
    assert finding.broken_markers == ("blue",)
    assert "no longer says 'blue'" in finding.detail


def test_a_marker_that_should_be_absent_but_appeared_is_changed() -> None:
    """The removal-shaped claims: a free DeepSeek variant coming back."""
    spec = claim(expect_present=(), expect_absent=("deepseek-r1:free",))
    fetch = fetcher({"https://example.test/page": Fetched(text='{"id": "deepseek-r1:free"}')})

    finding = check_claim(spec, fetch)

    assert finding.verdict == CHANGED
    assert "now says 'deepseek-r1:free'" in finding.detail


def test_both_kinds_of_break_are_reported_together() -> None:
    spec = claim(expect_present=("blue",), expect_absent=("green",))
    fetch = fetcher({"https://example.test/page": Fetched(text="the sky is green")})

    finding = check_claim(spec, fetch)

    assert finding.broken_markers == ("blue", "green")
    assert "no longer says" in finding.detail and "now says" in finding.detail


# ---------------------------------------------------------------------------
# Unverifiable is a verdict, not a failure
# ---------------------------------------------------------------------------


def test_an_unreachable_page_is_unverifiable_not_unchanged() -> None:
    finding = check_claim(claim(), fetcher({}))

    assert finding.verdict == UNVERIFIABLE
    assert "404" in finding.detail


def test_an_empty_page_is_unverifiable() -> None:
    """A JS-only render returns 200 with no text. That is not a confirmation."""
    fetch = fetcher({"https://example.test/page": Fetched(text="   \n  ")})

    assert check_claim(claim(), fetch).verdict == UNVERIFIABLE


def test_a_fetcher_that_raises_is_unverifiable_not_a_crash() -> None:
    finding = check_claim(claim(), exploding_fetcher)

    assert finding.verdict == UNVERIFIABLE
    assert "RuntimeError" in finding.detail


def test_a_needs_human_claim_is_unverifiable_without_any_request() -> None:
    def must_not_fetch(url: str) -> Fetched:  # pragma: no cover - must not run
        raise AssertionError("a needs-human claim must not be fetched")

    finding = check_claim(claim(needs_human="login-gated"), must_not_fetch)

    assert finding.verdict == UNVERIFIABLE
    assert finding.detail == "login-gated"


# ---------------------------------------------------------------------------
# Markup stripping
# ---------------------------------------------------------------------------


def test_script_bodies_are_stripped_before_matching() -> None:
    """The false-unchanged failure mode: a marker found inside a JS bundle."""
    html = "<html><script>var x = 'blue';</script><body>the sky is green</body></html>"

    text = strip_markup(html)

    assert "blue" not in text
    assert "green" in text


def test_style_bodies_are_stripped_too() -> None:
    assert "blue" not in strip_markup("<style>.a{color:blue}</style><p>hi</p>")


def test_tags_are_removed_but_their_text_survives() -> None:
    assert "always free" in strip_markup("<h1><b>Always</b> <i>Free</i></h1>").lower()


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def test_no_reports_means_no_age(tmp_path: Path) -> None:
    assert newest_report_age_days(tmp_path, today=date(2026, 9, 2)) is None
    assert "first facts-check run" in staleness_line(None)


def test_age_comes_from_the_filename_not_the_mtime(tmp_path: Path) -> None:
    """A checkout or a rebase rewrites mtimes and would reset the clock."""
    (tmp_path / "2026-08-01.md").write_text("old", encoding="utf-8")
    (tmp_path / "2026-07-01.md").write_text("older", encoding="utf-8")

    assert newest_report_age_days(tmp_path, today=date(2026, 9, 2)) == 32


def test_a_non_dated_filename_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("not a report", encoding="utf-8")
    (tmp_path / "2026-09-01.md").write_text("report", encoding="utf-8")

    assert newest_report_age_days(tmp_path, today=date(2026, 9, 2)) == 1


def test_a_missing_directory_is_not_an_error(tmp_path: Path) -> None:
    assert newest_report_age_days(tmp_path / "nope", today=date(2026, 9, 2)) is None


def test_the_nudge_fires_past_the_monthly_cadence() -> None:
    assert "past the" in staleness_line(STALE_AFTER_DAYS + 1)
    assert "past the" not in staleness_line(STALE_AFTER_DAYS)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def _findings() -> list[Finding]:
    return [
        Finding(claim(id="broke", topic="Groq"), CHANGED, "no longer says 'blue'", ("blue",)),
        Finding(claim(id="unknown", topic="NIM"), UNVERIFIABLE, "renders client-side"),
        Finding(claim(id="held", topic="Oracle"), UNCHANGED),
    ]


def test_the_report_leads_with_the_counts_and_the_changed_section() -> None:
    report = render_report(_findings(), run_date=date(2026, 9, 2), age_days=None)

    assert report.startswith("# Facts check — 2026-09-02")
    assert "1 changed · 1 unverifiable · 1 unchanged, of 3 claims." in report
    assert report.index("## Changed") < report.index("## Unverifiable")
    assert report.index("## Unverifiable") < report.index("## Unchanged")


def test_a_changed_claim_shows_the_blueprint_line_beside_the_page() -> None:
    report = render_report(_findings(), run_date=date(2026, 9, 2), age_days=1)

    assert "**Blueprint says** (blueprint.md:1): the sky is blue" in report
    assert "**The page** no longer says 'blue'." in report


def test_the_report_says_so_when_nothing_changed() -> None:
    report = render_report([Finding(claim(), UNCHANGED)], run_date=date(2026, 9, 2), age_days=1)

    assert "Nothing. Every checkable claim still holds." in report


def test_the_report_states_it_never_edits_the_blueprint() -> None:
    """Step 3 of the task, pinned: the tool produces a diff, not an edit."""
    report = render_report(_findings(), run_date=date(2026, 9, 2), age_days=1)

    assert "never edits `docs/blueprint.md`" in report


def test_writing_a_report_names_it_by_date(tmp_path: Path) -> None:
    path = write_report("body", report_dir=tmp_path / "reports", run_date=date(2026, 9, 2))

    assert path.name == "2026-09-02.md"
    assert path.read_text(encoding="utf-8") == "body"


def test_a_report_with_an_em_dash_round_trips_as_utf8(tmp_path: Path) -> None:
    """cp1252 machine; the report title has an em dash in it by construction."""
    report = render_report(_findings(), run_date=date(2026, 9, 2), age_days=1)

    path = write_report(report, report_dir=tmp_path, run_date=date(2026, 9, 2))

    assert "—" in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Selection and the CLI
# ---------------------------------------------------------------------------


def test_no_selection_means_every_claim() -> None:
    assert select_claims(CLAIMS, []) == list(CLAIMS)


def test_selecting_by_id_narrows_the_run() -> None:
    selected = select_claims(CLAIMS, ["deepseek-pricing"])

    assert [c.id for c in selected] == ["deepseek-pricing"]


def test_an_unknown_claim_id_exits_with_the_known_list() -> None:
    with pytest.raises(SystemExit, match="no such claim"):
        select_claims(CLAIMS, ["not-a-claim"])


def _args(**overrides) -> argparse.Namespace:
    base = dict(claim=[], report_dir=Path("unused"), no_write=False, dry_run=False)
    base.update(overrides)
    return argparse.Namespace(**base)


def test_a_dry_run_fetches_nothing(tmp_path: Path, capsys) -> None:
    code = run(_args(report_dir=tmp_path, dry_run=True), fetch=exploding_fetcher, today=date(2026, 9, 2))

    assert code == 0
    assert "deepseek-pricing" in capsys.readouterr().out


def test_a_real_run_writes_a_dated_report(tmp_path: Path) -> None:
    fetch = fetcher({})  # everything unverifiable; the report still lands

    run(_args(report_dir=tmp_path), fetch=fetch, today=date(2026, 9, 2))

    assert (tmp_path / "2026-09-02.md").exists()


def test_no_write_prints_instead_of_writing(tmp_path: Path, capsys) -> None:
    run(_args(report_dir=tmp_path, no_write=True), fetch=fetcher({}), today=date(2026, 9, 2))

    assert "# Facts check" in capsys.readouterr().out
    assert list(tmp_path.glob("*.md")) == []


def test_the_run_prints_the_staleness_line_first(tmp_path: Path, capsys) -> None:
    (tmp_path / "2026-07-01.md").write_text("old", encoding="utf-8")

    run(_args(report_dir=tmp_path, dry_run=True), fetch=exploding_fetcher, today=date(2026, 9, 2))

    assert capsys.readouterr().out.splitlines()[0].startswith("Newest report is 63 days old")


def test_the_parser_accepts_repeated_claim_flags() -> None:
    args = build_parser().parse_args(["--claim", "a", "--claim", "b"])

    assert args.claim == ["a", "b"]


# ---------------------------------------------------------------------------
# The checklist itself
# ---------------------------------------------------------------------------


def test_every_claim_has_a_source_and_a_blueprint_reference() -> None:
    for spec in CLAIMS:
        assert spec.source_url.startswith("https://"), spec.id
        assert spec.blueprint_ref.startswith("blueprint.md:"), spec.id
        assert spec.recorded.strip(), spec.id


def test_every_claim_is_actually_checkable_or_says_why_not() -> None:
    """A claim with no markers and no needs-human reason would silently pass
    forever -- the exact rot this tool is supposed to detect."""
    for spec in CLAIMS:
        checkable = spec.expect_present or spec.expect_absent
        assert checkable or spec.needs_human, spec.id


def test_claim_ids_are_unique() -> None:
    ids = [spec.id for spec in CLAIMS]

    assert len(ids) == len(set(ids))


def test_the_checklist_covers_every_topic_the_blueprint_names() -> None:
    """blueprint.md:365 names the Agent SDK pause, DeepSeek rates, free-model
    rosters and promo expiries; the task adds Cerebras and Oracle."""
    topics = {spec.topic for spec in CLAIMS}

    assert {"Claude / Agent SDK", "DeepSeek", "Groq", "Cerebras", "OpenRouter"} <= topics
    assert {"Gemini (AI Studio)", "NVIDIA NIM", "Oracle Cloud"} <= topics


def test_check_all_returns_one_finding_per_claim() -> None:
    findings = check_all(CLAIMS, fetcher({}))

    assert len(findings) == len(CLAIMS)
