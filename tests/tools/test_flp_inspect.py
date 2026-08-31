"""Offline coverage for ``tools/flp_inspect.py``.

``docs/context.md`` names this file's absence as the thing gating the FLP
*writing* half: "``tools/flp_inspect.py`` is read-only and has no tests yet --
do not build the writing half on it until it does."

Everything here runs on the default 3.12 ``.venv`` and never imports PyFLP.
That is possible because ``flp_inspect`` imports PyFLP lazily, inside
``inspect_project`` and ``_samples_by_channel`` -- so the classification rules,
the renderer and the CLI are all reachable without the 3.11 sandbox a real
``.flp`` needs. The two PyFLP-touching functions are covered by
``tests/flp/test_flp_real.py`` under the ``realflp`` marker instead.

The classifier assertions are deliberately specific about *which* rule fired,
not just the label. Every rule is a guess about Ali's own habits that he is
meant to correct by eye, so a rule silently changing which evidence it reports
is exactly the regression worth catching.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import flp_inspect as fi


def _clip(
    *,
    track_index: int = 0,
    position: int = 0,
    kind: str = "unknown",
    evidence: str = "",
    sample: str | None = None,
) -> fi.Clip:
    return fi.Clip(
        track_index=track_index,
        track_reverse_index=fi.PLAYLIST_TRACK_MAX_INDEX - track_index,
        position=position,
        length=100,
        kind=kind,
        evidence=evidence,
        sample=sample,
    )


def _report(
    *,
    path: str = "C:/projects/song.flp",
    clips: tuple[fi.Clip, ...] = (),
    samples_without_clip: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> fi.ProjectReport:
    return fi.ProjectReport(
        path=path,
        parsed=True,
        clip_count=len(clips),
        tracks_used=len({clip.track_index for clip in clips}),
        clips=clips,
        samples_without_clip=samples_without_clip,
        warnings=warnings,
    )


# --- classify ----------------------------------------------------------------


def test_an_fl_recording_stamp_is_a_vocal_take() -> None:
    kind, evidence = fi.classify("C:/song/untitled_2026-08-29 14-22-01_Insert 3.wav")

    assert kind == "vocal-take"
    assert evidence == "FL recording stamp with an Insert number"


def test_the_recording_stamp_matches_a_named_project_not_just_untitled() -> None:
    # The first version of this file keyed on the "untitled" prefix and reported
    # all 18 takes in babydon'tgetsomad.flp as unknown. The stamp is the signal.
    kind, _ = fi.classify("C:/song/babydontgetsomad_2026-08-29 14-22-01_Insert 2.wav")

    assert kind == "vocal-take"


def test_a_sample_pack_folder_names_the_kind() -> None:
    kind, evidence = fi.classify("C:/Samples/Drums/kick.wav")

    assert kind == "drums"
    assert evidence == "sample pack folder named drums/percussion"


def test_a_drum_word_in_the_filename_is_enough_without_the_folder() -> None:
    kind, evidence = fi.classify("C:/anything/hard 808 loop.wav")

    assert kind == "drums"
    assert evidence == "drum-part word in the filename"


def test_a_downloaded_file_is_an_instrumental() -> None:
    kind, evidence = fi.classify("C:/Users/Ali/Downloads/type beat.mp3")

    assert kind == "instrumental"
    assert evidence == "downloaded from outside the project"


def test_the_first_matching_rule_wins() -> None:
    # This path matches both the vocal-take stamp and the drums/ folder rule.
    # Rule order is the tie-break, and the stamp is the more specific claim.
    kind, _ = fi.classify("C:/Drums/kick_2026-08-29 14-22-01_Insert 3.wav")

    assert kind == "vocal-take"

    # Same idea one rung down: the drum-word rule precedes the Downloads rule.
    kind, evidence = fi.classify("C:/Users/Ali/Downloads/kick.wav")

    assert (kind, evidence) == ("drums", "drum-part word in the filename")


def test_a_clip_with_no_sample_path_is_unknown_and_says_why() -> None:
    assert fi.classify(None) == (
        "unknown",
        "no sample path on this clip (pattern clip, or plugin)",
    )


def test_an_unmatched_path_is_admitted_rather_than_forced_into_a_bucket() -> None:
    assert fi.classify("C:/song/mystery.wav") == ("unknown", "no rule matched this path")


# --- insert_number -----------------------------------------------------------


def test_the_mixer_insert_is_read_off_the_recording_filename() -> None:
    assert fi.insert_number("take_2026-08-29 14-22-01_Insert 12.wav") == 12


@pytest.mark.parametrize("sample", ["a_insert_7.wav", "a_Insert 7.wav", "a_Insert7.wav"])
def test_the_insert_separator_and_case_both_vary_in_real_files(sample: str) -> None:
    assert fi.insert_number(sample) == 7


def test_a_sample_with_no_insert_marker_has_no_insert_number() -> None:
    assert fi.insert_number("C:/Samples/Drums/kick.wav") is None
    assert fi.insert_number(None) is None


# --- _shorten ----------------------------------------------------------------


def test_a_missing_sample_renders_as_a_dash() -> None:
    assert fi._shorten(None) == "-"


def test_shorten_keeps_the_filename_and_drops_the_directory() -> None:
    assert fi._shorten("C:/a/very/deep/path/kick.wav") == "kick.wav"


def test_a_long_filename_is_truncated_from_the_left_to_exactly_the_width() -> None:
    # Left-truncated on purpose: the tail of an FL recording name carries the
    # timestamp and the insert number, which is the part worth reading.
    shortened = fi._shorten("C:/a/" + "x" * 80 + ".wav")

    assert len(shortened) == 52
    assert shortened.startswith("...")
    assert shortened.endswith(".wav")


def test_a_filename_exactly_at_the_width_is_left_alone() -> None:
    name = "y" * 48 + ".wav"

    assert fi._shorten("C:/a/" + name) == name


# --- render ------------------------------------------------------------------


def test_render_summarises_counts_and_layout_by_kind() -> None:
    report = _report(
        clips=(
            _clip(track_index=1, kind="instrumental", sample="C:/Downloads/beat.mp3"),
            _clip(track_index=3, kind="drums", sample="C:/Samples/Drums/kick.wav"),
            _clip(track_index=4, kind="drums", sample="C:/Samples/Drums/snare.wav"),
        )
    )

    output = fi.render(report)

    assert "3 clips across 3 playlist tracks" in output
    assert "by kind: drums=2, instrumental=1" in output
    # Layout per kind is the evidence for or against a convention.
    assert "drums         -> tracks [3, 4]" in output
    assert "instrumental  -> tracks [1]" in output


def test_render_counts_recordings_per_mixer_insert() -> None:
    report = _report(
        clips=(
            _clip(kind="vocal-take", sample="a_2026-08-29 14-22-01_Insert 2.wav"),
            _clip(kind="vocal-take", sample="b_2026-08-29 14-25-00_Insert 2.wav"),
            _clip(kind="vocal-take", sample="c_2026-08-29 14-30-00_Insert 5.wav"),
        )
    )

    assert "recordings per mixer insert: Insert 2=2, Insert 5=1" in fi.render(report)


def test_render_lists_only_the_first_ten_unpaired_samples() -> None:
    report = _report(samples_without_clip=tuple(f"sample{n}.wav" for n in range(25)))

    output = fi.render(report)

    assert "25 samples not paired to a clip" in output
    assert "sample9.wav" in output
    assert "sample10.wav" not in output


def test_render_reports_each_distinct_parser_warning_once() -> None:
    report = _report(warnings=("channel group missing", "channel group missing", "odd event"))

    output = fi.render(report)

    assert output.count("channel group missing") == 1
    assert "odd event" in output


def test_render_of_an_empty_project_still_produces_a_header() -> None:
    output = fi.render(_report())

    assert "=== song.flp ===" in output
    assert "0 clips across 0 playlist tracks" in output


def test_render_orders_clips_by_track_then_position() -> None:
    report = _report(
        clips=(
            _clip(track_index=2, position=500, sample="second-on-two.wav"),
            _clip(track_index=1, position=900, sample="only-on-one.wav"),
            _clip(track_index=2, position=100, sample="first-on-two.wav"),
        )
    )

    output = fi.render(report)
    order = [
        output.index("only-on-one.wav"),
        output.index("first-on-two.wav"),
        output.index("second-on-two.wav"),
    ]

    assert order == sorted(order)


# --- discover ----------------------------------------------------------------


def test_a_directory_is_searched_recursively(tmp_path: Path) -> None:
    (tmp_path / "one.flp").write_bytes(b"")
    nested = tmp_path / "album" / "track two"
    nested.mkdir(parents=True)
    (nested / "two.flp").write_bytes(b"")

    found = fi.discover([str(tmp_path)])

    # Sorted by full path, so a nested project sorts under its folder name
    # rather than after everything at the top level.
    assert [path.name for path in found] == ["two.flp", "one.flp"]


def test_backup_autosaves_are_skipped_so_projects_are_not_double_counted(tmp_path: Path) -> None:
    (tmp_path / "song.flp").write_bytes(b"")
    backup = tmp_path / "Backup"
    backup.mkdir()
    (backup / "song.flp").write_bytes(b"")

    found = fi.discover([str(tmp_path)])

    assert [path.name for path in found] == ["song.flp"]
    assert all("Backup" not in path.parts for path in found)


def test_an_explicit_file_is_taken_as_given(tmp_path: Path) -> None:
    target = tmp_path / "song.flp"
    target.write_bytes(b"")

    assert fi.discover([str(target)]) == [target]


def test_a_missing_path_is_reported_and_skipped_rather_than_raising(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    real = tmp_path / "song.flp"
    real.write_bytes(b"")

    found = fi.discover([str(tmp_path / "gone.flp"), str(real)])

    assert found == [real]
    assert "skipped, not found" in capsys.readouterr().err


# --- main --------------------------------------------------------------------


def test_main_fails_when_nothing_matched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert fi.main([str(tmp_path / "nothing.flp")]) == 1
    assert "no .flp files found" in capsys.readouterr().err


def test_main_emits_parseable_json_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "song.flp"
    target.write_bytes(b"")
    monkeypatch.setattr(fi, "inspect_project", lambda path: _report(clips=(_clip(kind="drums"),)))

    assert fi.main([str(target), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["clip_count"] == 1
    assert payload[0]["clips"][0]["kind"] == "drums"


def test_one_unreadable_project_does_not_abort_the_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 6 of Ali's 24 real projects fail to parse (PyFLP bugs, all loud). A batch
    # that stopped at the first one would report nothing about the other 18.
    good = tmp_path / "good.flp"
    bad = tmp_path / "bad.flp"
    good.write_bytes(b"")
    bad.write_bytes(b"")

    def explode_on_bad(path: Path) -> fi.ProjectReport:
        if path.name == "bad.flp":
            raise IndexError("list index out of range")
        return _report(path=str(path))

    monkeypatch.setattr(fi, "inspect_project", explode_on_bad)

    exit_code = fi.main([str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FAILED to read bad.flp: IndexError: list index out of range" in captured.err
    assert "=== good.flp ===" in captured.out
