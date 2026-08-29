from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from ingest.noise import (
    ExclusionPattern,
    NoisePatternError,
    filter_chunks,
    load_patterns,
    parse_pattern,
)


@dataclass(frozen=True)
class _Chunk:
    text: str
    source: str


# --- ExclusionPattern.matches ----------------------------------------------


def test_substring_pattern_matches_case_insensitively():
    pattern = ExclusionPattern(kind="substring", value="Forwarded", origin="<test>")
    assert pattern.matches(text="this was forwarded many times", source="a.txt") is True
    assert pattern.matches(text="FORWARDED", source="a.txt") is True
    assert pattern.matches(text="unrelated text", source="a.txt") is False


def test_regex_pattern_matches_via_search():
    pattern = ExclusionPattern(kind="regex", value=r"^Fwd:", origin="<test>")
    assert pattern.matches(text="Fwd: check this out", source="a.txt") is True
    assert pattern.matches(text="not a forward", source="a.txt") is False


def test_source_pattern_matches_exact_source_only():
    pattern = ExclusionPattern(kind="source", value="family_export.txt", origin="<test>")
    assert pattern.matches(text="anything", source="family_export.txt") is True
    assert pattern.matches(text="anything", source="other.txt") is False


def test_unknown_pattern_kind_raises_on_match():
    pattern = ExclusionPattern(kind="bogus", value="x", origin="<test>")
    with pytest.raises(NoisePatternError, match="unknown pattern kind"):
        pattern.matches(text="x", source="a.txt")


def test_pattern_key_is_kind_colon_value():
    pattern = ExclusionPattern(kind="substring", value="meme", origin="<test>")
    assert pattern.key == "substring:meme"


# --- load_patterns -----------------------------------------------------


def test_load_patterns_returns_empty_list_for_a_missing_file(tmp_path: Path):
    assert load_patterns(tmp_path / "missing.txt") == []


def test_load_patterns_skips_blank_lines_and_comments(tmp_path: Path):
    path = tmp_path / "patterns.txt"
    path.write_text("\n# a comment\n   \nsubstring:meme\n", encoding="utf-8")

    patterns = load_patterns(path)

    assert [p.kind for p in patterns] == ["substring"]
    assert patterns[0].value == "meme"


def test_load_patterns_parses_every_supported_kind(tmp_path: Path):
    path = tmp_path / "patterns.txt"
    path.write_text("substring:meme\nregex:^Fwd:\nsource:chat.txt\n", encoding="utf-8")

    patterns = load_patterns(path)

    assert [(p.kind, p.value) for p in patterns] == [
        ("substring", "meme"),
        ("regex", "^Fwd:"),
        ("source", "chat.txt"),
    ]


def test_load_patterns_rejects_a_line_with_no_colon(tmp_path: Path):
    path = tmp_path / "patterns.txt"
    path.write_text("not-a-valid-line\n", encoding="utf-8")

    with pytest.raises(NoisePatternError, match="expected"):
        load_patterns(path)


def test_load_patterns_rejects_an_unknown_kind(tmp_path: Path):
    path = tmp_path / "patterns.txt"
    path.write_text("bogus:value\n", encoding="utf-8")

    with pytest.raises(NoisePatternError, match="unknown pattern kind"):
        load_patterns(path)


def test_load_patterns_rejects_an_empty_value(tmp_path: Path):
    path = tmp_path / "patterns.txt"
    path.write_text("substring:\n", encoding="utf-8")

    with pytest.raises(NoisePatternError, match="must not be empty"):
        load_patterns(path)


def test_load_patterns_rejects_an_invalid_regex(tmp_path: Path):
    path = tmp_path / "patterns.txt"
    path.write_text("regex:(unclosed\n", encoding="utf-8")

    with pytest.raises(NoisePatternError, match="invalid regex"):
        load_patterns(path)


def test_load_patterns_error_message_cites_the_file_and_line_number(tmp_path: Path):
    path = tmp_path / "patterns.txt"
    path.write_text("substring:ok\nbogus:value\n", encoding="utf-8")

    with pytest.raises(NoisePatternError, match=r"patterns\.txt:2"):
        load_patterns(path)


# --- parse_pattern (single CLI-supplied spec) -------------------------------


def test_parse_pattern_parses_a_single_spec():
    pattern = parse_pattern("substring:forwarded video")
    assert pattern.kind == "substring"
    assert pattern.value == "forwarded video"


def test_parse_pattern_rejects_malformed_input():
    with pytest.raises(NoisePatternError):
        parse_pattern("not-a-valid-spec")


# --- filter_chunks -----------------------------------------------------


def test_filter_chunks_with_no_patterns_keeps_everything():
    chunks = [_Chunk("hello", "a.txt"), _Chunk("world", "b.txt")]

    outcome = filter_chunks(chunks, [])

    assert outcome.kept == chunks
    assert outcome.excluded == 0
    assert outcome.excluded_by_pattern == {}


def test_filter_chunks_drops_matching_chunks_and_counts_them():
    chunks = [
        _Chunk("this is a forwarded meme", "a.txt"),
        _Chunk("a real note", "a.txt"),
        _Chunk("another forwarded meme", "a.txt"),
    ]
    patterns = [ExclusionPattern(kind="substring", value="forwarded", origin="<test>")]

    outcome = filter_chunks(chunks, patterns)

    assert [c.text for c in outcome.kept] == ["a real note"]
    assert outcome.excluded == 2
    assert outcome.excluded_by_pattern == {"substring:forwarded": 2}


def test_filter_chunks_reports_counts_per_distinct_pattern():
    chunks = [
        _Chunk("meme text", "a.txt"),
        _Chunk("anything", "spam_export.txt"),
        _Chunk("kept text", "a.txt"),
    ]
    patterns = [
        ExclusionPattern(kind="substring", value="meme", origin="<test>"),
        ExclusionPattern(kind="source", value="spam_export.txt", origin="<test>"),
    ]

    outcome = filter_chunks(chunks, patterns)

    assert [c.text for c in outcome.kept] == ["kept text"]
    assert outcome.excluded_by_pattern == {"substring:meme": 1, "source:spam_export.txt": 1}


def test_filter_chunks_counts_a_double_match_once_against_the_first_pattern():
    chunks = [_Chunk("forwarded meme", "a.txt")]
    patterns = [
        ExclusionPattern(kind="substring", value="forwarded", origin="<test>"),
        ExclusionPattern(kind="substring", value="meme", origin="<test>"),
    ]

    outcome = filter_chunks(chunks, patterns)

    assert outcome.kept == []
    assert outcome.excluded_by_pattern == {"substring:forwarded": 1}
