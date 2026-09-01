"""Tests for ``voice/listen_wakeword.py``, the live "Hey JARVIS" listener.

No microphone, no ONNX runtime, no openWakeWord model. The stream and the
model are injected; the clock is injected too, because the real one would make
a bounded run take as long as the run.

What is deliberately *not* tested here: whether the phrase actually fires when
Ali says it from across the room. That is a sensory judgement on a real
microphone and belongs to him, not to a fake that returns whatever score the
test wrote down.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from voice import listen_wakeword
from voice.config import WAKEWORD_CHANNELS, WAKEWORD_DTYPE, WAKEWORD_SAMPLE_RATE
from voice.listen_wakeword import (
    DEFAULT_THRESHOLD,
    FRAME_SAMPLES,
    MODEL_KEY,
    REFRACTORY_SECONDS,
    _bar,
    list_devices,
    listen,
    main,
)

# Real ``time.monotonic()`` returns a large number, and the refractory check is
# ``now - last_hit > REFRACTORY_SECONDS`` against ``last_hit = 0.0``. Starting a
# fake clock at zero would therefore suppress the very first detection, which is
# an artefact of the fake and not of the code.
CLOCK_START = 1000.0
FRAME_SECONDS = FRAME_SAMPLES / WAKEWORD_SAMPLE_RATE  # 0.08s, one openWakeWord frame


class FakeClock:
    def __init__(self, start: float = CLOCK_START) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class FakeStream:
    """A microphone that never existed.

    Hands back ``frames`` scripted blocks, then one extra silent block during
    which it jumps the clock past any deadline. The extra block is what ends a
    bounded run, and it is silent on purpose: jumping the clock on the last
    *scripted* frame would move that frame outside the refractory window and
    invent a detection the code did not make.
    """

    def __init__(
        self,
        clock: FakeClock,
        *,
        frames: int = 1,
        overflow_at: tuple[int, ...] = (),
        frame_seconds: float = FRAME_SECONDS,
        interrupt_after: int | None = None,
    ) -> None:
        self._clock = clock
        self._frames = frames
        self._overflow_at = set(overflow_at)
        self._frame_seconds = frame_seconds
        self._interrupt_after = interrupt_after
        self.reads = 0
        self.entered = False
        self.exited = False
        self.blocksizes: list[int] = []

    def __enter__(self) -> "FakeStream":
        self.entered = True
        return self

    def __exit__(self, *_exc) -> bool:
        self.exited = True
        return False

    def read(self, samples: int):
        if self._interrupt_after is not None and self.reads >= self._interrupt_after:
            raise KeyboardInterrupt
        overflowed = self.reads in self._overflow_at
        self.reads += 1
        self.blocksizes.append(samples)
        self._clock.now += self._frame_seconds
        if self.reads > self._frames:
            # Past any deadline the caller set, so the loop stops here.
            self._clock.now += 1_000_000.0
        return np.zeros((samples, 1), dtype="int16"), overflowed


class FakeModel:
    """openWakeWord, scripted. One score per frame, in order."""

    def __init__(self, scores, *, keys: tuple[str, ...] = (MODEL_KEY,)) -> None:
        self.models = {name: object() for name in keys}
        self._scores = list(scores)
        self.scored: list[float] = []
        self.frame_shapes: list[tuple[int, ...]] = []

    def predict(self, frame):
        self.frame_shapes.append(np.shape(frame))
        score = self._scores.pop(0) if self._scores else 0.0
        self.scored.append(score)
        return {MODEL_KEY: score}


def run_listen(
    scores,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    meter: bool = False,
    device=None,
    seconds: float | None = 30.0,
    overflow_at: tuple[int, ...] = (),
    frame_seconds: float = FRAME_SECONDS,
    interrupt_after: int | None = None,
    model: FakeModel | None = None,
):
    """Drive ``listen`` over a scripted list of per-frame scores."""
    clock = FakeClock()
    scores = list(scores)
    stream = FakeStream(
        clock,
        frames=max(len(scores), 1),
        overflow_at=overflow_at,
        frame_seconds=frame_seconds,
        interrupt_after=interrupt_after,
    )
    model = model if model is not None else FakeModel(scores)
    opened: list[object] = []

    def open_stream(dev):
        opened.append(dev)
        return stream

    code = listen(
        threshold,
        device,
        meter,
        seconds,
        load_model=lambda: model,
        open_stream=open_stream,
        clock=clock,
    )
    return code, model, stream, opened


# ---------------------------------------------------------------------------
# The threshold, which is the whole decision
# ---------------------------------------------------------------------------


def test_a_score_on_the_threshold_counts_as_a_detection(capsys: pytest.CaptureFixture[str]) -> None:
    """``>=``, not ``>``. openWakeWord's own README treats 0.5 as the decision
    point, and a score of exactly the threshold is above the line."""
    code, _model, _stream, _opened = run_listen([DEFAULT_THRESHOLD])

    out = capsys.readouterr().out
    assert code == 0
    assert "HEARD IT  #1" in out
    assert "1 detection(s)" in out


def test_a_score_just_under_the_threshold_is_not_a_detection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, _model, _stream, _opened = run_listen([DEFAULT_THRESHOLD - 0.001])

    out = capsys.readouterr().out
    assert code == 0
    assert "HEARD IT" not in out
    assert "0 detection(s)" in out


def test_a_lower_threshold_turns_the_same_audio_into_a_detection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """This is exactly what ``--threshold 0.3`` is for, and the reason the
    no-detection message suggests it."""
    quiet = 0.35
    run_listen([quiet])
    assert "HEARD IT" not in capsys.readouterr().out

    run_listen([quiet], threshold=0.3)
    assert "HEARD IT" in capsys.readouterr().out


def test_the_default_threshold_is_openwakewords_own() -> None:
    assert DEFAULT_THRESHOLD == 0.5


def test_the_highest_score_seen_is_reported_even_with_no_detection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without the peak, "nothing detected" cannot be told apart from "the
    microphone was never heard"."""
    run_listen([0.01, 0.42, 0.13])

    out = capsys.readouterr().out
    assert "Highest score seen: 0.420" in out
    assert "try --threshold 0.3" in out


def test_a_silent_run_says_what_to_check(capsys: pytest.CaptureFixture[str]) -> None:
    run_listen([0.0, 0.0])

    out = capsys.readouterr().out
    assert "Nothing detected" in out
    assert "--list-devices" in out


# ---------------------------------------------------------------------------
# The refractory window
# ---------------------------------------------------------------------------


def test_one_spoken_phrase_reports_once_not_once_per_frame(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The phrase stays in the model's window for several frames. Without the
    refractory window a single "Hey JARVIS" prints a wall of hits."""
    code, _model, _stream, _opened = run_listen([0.9] * 6)

    out = capsys.readouterr().out
    assert code == 0
    assert out.count("HEARD IT") == 1
    assert "1 detection(s)" in out


def test_a_second_phrase_after_the_window_is_a_second_detection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # One frame per second, so the gap between the two loud frames exceeds the
    # 1.5s window.
    code, _model, _stream, _opened = run_listen([0.9, 0.0, 0.0, 0.9], frame_seconds=1.0)

    out = capsys.readouterr().out
    assert out.count("HEARD IT") == 2
    assert "2 detection(s)" in out


def test_the_refractory_window_is_the_documented_one_and_a_half_seconds() -> None:
    assert REFRACTORY_SECONDS == 1.5


# ---------------------------------------------------------------------------
# --meter
# ---------------------------------------------------------------------------


def test_the_meter_changes_the_output_without_changing_detection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    scores = [0.1, 0.62, 0.2]

    plain_code, plain_model, _s, _o = run_listen(scores, meter=False)
    plain_out = capsys.readouterr().out
    metered_code, metered_model, _s2, _o2 = run_listen(scores, meter=True)
    metered_out = capsys.readouterr().out

    assert plain_code == metered_code == 0
    assert plain_model.scored == metered_model.scored
    assert plain_out.count("HEARD IT") == metered_out.count("HEARD IT") == 1
    assert "0.620" in metered_out and "#" in metered_out
    assert "0.620\r" not in plain_out and "----" not in plain_out


def test_the_bar_fills_in_proportion_to_the_score() -> None:
    assert _bar(0.0, width=10) == "-" * 10
    assert _bar(1.0, width=10) == "#" * 10
    assert _bar(0.5, width=10) == "#####-----"
    assert len(_bar(0.37)) == 32


# ---------------------------------------------------------------------------
# The stream itself
# ---------------------------------------------------------------------------


def test_the_model_is_fed_one_eighty_millisecond_frame_at_a_time() -> None:
    """1280 samples at 16 kHz. Larger delays detection, smaller wastes work."""
    _code, model, stream, _opened = run_listen([0.0, 0.0, 0.0])

    assert stream.blocksizes and set(stream.blocksizes) == {FRAME_SAMPLES}
    # np.squeeze drops the channel axis before the model sees it.
    assert model.frame_shapes and set(model.frame_shapes) == {(FRAME_SAMPLES,)}
    assert FRAME_SAMPLES / WAKEWORD_SAMPLE_RATE == pytest.approx(0.08)


def test_the_chosen_device_reaches_the_stream() -> None:
    _code, _model, _stream, opened = run_listen([0.0], device=4)
    assert opened == [4]


def test_the_default_stream_would_open_the_wakeword_capture_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model was trained on 16 kHz mono int16. Opening anything else means
    a silent format mismatch rather than a loud error."""
    captured: dict = {}

    class FakeSoundDevice:
        @staticmethod
        def InputStream(**kwargs):
            captured.update(kwargs)
            return "stream"

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)

    assert listen_wakeword._open_stream(2) == "stream"
    assert captured == {
        "samplerate": WAKEWORD_SAMPLE_RATE,
        "channels": WAKEWORD_CHANNELS,
        "dtype": WAKEWORD_DTYPE,
        "blocksize": FRAME_SAMPLES,
        "device": 2,
    }


def test_a_dropped_frame_is_announced(capsys: pytest.CaptureFixture[str]) -> None:
    """A miss during a buffer overflow says nothing about the model, so the
    user has to be told the audio was dropped."""
    run_listen([0.0, 0.0, 0.0], overflow_at=(1,))

    out = capsys.readouterr().out
    assert out.count("audio buffer overflowed") == 1


def test_the_stream_is_closed_even_on_ctrl_c() -> None:
    _code, _model, stream, _opened = run_listen([0.0] * 5, interrupt_after=2)
    assert stream.entered and stream.exited


def test_ctrl_c_still_reports_what_was_heard(capsys: pytest.CaptureFixture[str]) -> None:
    """A bounded run and an interrupted run both have to print the summary.
    ``--seconds`` used to end the loop and print nothing at all."""
    code, _model, _stream, _opened = run_listen(
        [0.9, 0.0, 0.0], seconds=None, interrupt_after=1, frame_seconds=1.0
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "1 detection(s)" in out


def test_an_unbounded_run_keeps_listening_until_it_is_interrupted() -> None:
    """``--seconds 0`` means no deadline. The clock racing past any plausible
    deadline must not end the loop."""
    _code, model, stream, _opened = run_listen(
        [0.0] * 20, seconds=None, interrupt_after=12, frame_seconds=1000.0
    )
    assert stream.reads == 12
    assert len(model.scored) == 12


def test_a_bounded_run_stops_at_its_deadline(capsys: pytest.CaptureFixture[str]) -> None:
    clock = FakeClock()
    stream = FakeStream(clock, frames=10_000, frame_seconds=1.0)
    model = FakeModel([0.0] * 10_000)

    code = listen(
        DEFAULT_THRESHOLD,
        None,
        False,
        5.0,
        load_model=lambda: model,
        open_stream=lambda _d: stream,
        clock=clock,
    )

    assert code == 0
    assert stream.reads == 5, "the 5-second deadline did not bound the run"
    assert "for 5s" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# A model that did not load
# ---------------------------------------------------------------------------


def test_a_model_without_the_wake_phrase_fails_loudly_before_the_first_frame(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Otherwise the first frame dies with a KeyError that says nothing about
    which model was actually loaded."""
    clock = FakeClock()

    def forbidden_stream(_device):
        raise AssertionError("the microphone was opened despite no model")

    code = listen(
        DEFAULT_THRESHOLD,
        None,
        False,
        1.0,
        load_model=lambda: FakeModel([], keys=("alexa_v0.1",)),
        open_stream=forbidden_stream,
        clock=clock,
    )

    captured = capsys.readouterr()
    assert code == 1
    assert MODEL_KEY in captured.err
    assert "alexa_v0.1" in captured.err


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _capture_listen(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []

    def fake_listen(*args, **kwargs):
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(listen_wakeword, "listen", fake_listen)
    return calls


def test_the_cli_passes_its_flags_straight_through(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_listen(monkeypatch)

    assert main(["--threshold", "0.3", "--device", "2", "--meter", "--seconds", "12"]) == 0
    assert calls[0][0] == (0.3, 2, True, 12.0)


def test_the_cli_defaults_match_the_documented_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_listen(monkeypatch)

    main([])
    assert calls[0][0] == (DEFAULT_THRESHOLD, None, False, 30.0)


def test_seconds_zero_means_run_until_ctrl_c(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_listen(monkeypatch)

    main(["--seconds", "0"])
    assert calls[0][0][3] is None


@pytest.mark.parametrize("bad", ["0", "-1", "1.5", "2"])
def test_an_out_of_range_threshold_is_refused_before_the_device_is_opened(
    bad: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(*_args, **_kwargs):
        raise AssertionError("the microphone was opened with a bad threshold")

    monkeypatch.setattr(listen_wakeword, "listen", explode)

    assert main(["--threshold", bad]) == 2
    assert "--threshold must be between 0 and 1" in capsys.readouterr().err


def test_a_threshold_of_exactly_one_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_listen(monkeypatch)
    assert main(["--threshold", "1.0"]) == 0
    assert calls[0][0][0] == 1.0


def test_list_devices_reports_only_inputs_and_opens_no_stream(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeSoundDevice:
        default = type("D", (), {"device": (1, 0)})()

        @staticmethod
        def query_devices():
            return [
                {"name": "Speakers", "max_input_channels": 0},
                {"name": "Microphone Array", "max_input_channels": 2},
                {"name": "USB Mic", "max_input_channels": 1},
            ]

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)
    monkeypatch.setattr(
        listen_wakeword,
        "listen",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("listened during --list-devices")),
    )

    assert main(["--list-devices"]) == 0

    out = capsys.readouterr().out
    assert "Microphone Array (default)" in out
    assert "USB Mic" in out
    assert "Speakers" not in out


def test_list_devices_can_be_called_directly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeSoundDevice:
        default = type("D", (), {"device": (0, 0)})()

        @staticmethod
        def query_devices():
            return [{"name": "Only Mic", "max_input_channels": 1}]

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)

    assert list_devices() == 0
    assert "[ 0] Only Mic (default)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Import hygiene
# ---------------------------------------------------------------------------


def test_importing_the_module_pulls_in_no_audio_stack() -> None:
    """The offline suite imports this on machines with no microphone and no
    onnxruntime, so nothing heavy may load at import time."""
    import importlib

    names = ("voice.listen_wakeword", "sounddevice", "openwakeword", "openwakeword.model")
    saved = {name: sys.modules[name] for name in names if name in sys.modules}
    for name in names:
        sys.modules.pop(name, None)
    try:
        module = importlib.import_module("voice.listen_wakeword")
        assert module.main is not None
        assert "sounddevice" not in sys.modules
        assert "openwakeword" not in sys.modules
    finally:
        sys.modules.update(saved)


def test_the_model_key_is_the_shipped_models_filename_stem() -> None:
    """Not a label we chose -- openWakeWord keys its prediction dict by the
    model filename, so a rename here silently stops every detection."""
    assert MODEL_KEY == "hey_jarvis_v0.1"
    assert Path(f"{MODEL_KEY}.onnx").stem == MODEL_KEY


# ---------------------------------------------------------------------------
# The session log
#
# U4 is the last unmeasured Phase 3 number: how often "Hey JARVIS" fires when
# Ali did not say it. The session is his; these tests cover everything around
# it, so his part is one command and one sentence afterwards.
# ---------------------------------------------------------------------------


def run_listen_with_log(
    scores,
    log_path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    seconds: float | None = 30.0,
    interrupt_after: int | None = None,
    device=None,
):
    """``run_listen``, plus a real log file under ``tmp_path``."""
    clock = FakeClock()
    scores = list(scores)
    stream = FakeStream(
        clock, frames=max(len(scores), 1), interrupt_after=interrupt_after
    )
    model = FakeModel(scores)

    stamps = iter(
        datetime(2026, 9, 2, 3, 0, i % 60, tzinfo=UTC) for i in range(1, 500)
    )

    code = listen(
        threshold,
        device,
        False,
        seconds,
        load_model=lambda: model,
        open_stream=lambda _dev: stream,
        clock=clock,
        log_path=log_path,
        open_log=lambda path: listen_wakeword.DetectionLog(path, now=lambda: next(stamps)),
    )
    return code, listen_wakeword.read_log(log_path)


def test_a_session_writes_a_header_and_a_footer(tmp_path: Path) -> None:
    log = tmp_path / "wake.jsonl"

    _code, records = run_listen_with_log([0.1], log)

    assert [r["event"] for r in records] == ["session_start", "session_end"]
    assert records[0]["threshold"] == DEFAULT_THRESHOLD
    assert records[0]["model"] == MODEL_KEY
    assert records[-1]["detections"] == 0


def test_each_detection_is_one_line_with_its_score(tmp_path: Path) -> None:
    log = tmp_path / "wake.jsonl"

    _code, records = run_listen_with_log([0.91, 0.0, 0.0], log)

    hits = [r for r in records if r["event"] == "detection"]
    assert len(hits) == 1
    assert hits[0]["score"] == 0.91
    assert "at" in hits[0] and "elapsed_seconds" in hits[0]


def test_the_log_never_contains_audio(tmp_path: Path) -> None:
    """This runs for hours in Ali's room. A log that captured sound would be a
    recording of his life; blueprint 5 is explicit that wake-word audio never
    leaves the moment."""
    log = tmp_path / "wake.jsonl"

    run_listen_with_log([0.9], log)

    body = log.read_text(encoding="utf-8")
    for banned in ("audio", "frame", "samples", "pcm", "wav"):
        assert banned not in body.lower()


def test_ctrl_c_still_writes_the_footer(tmp_path: Path) -> None:
    """The exit Ali actually uses after an evening. Without a footer there is
    no session duration, so there is no detections-per-hour."""
    log = tmp_path / "wake.jsonl"

    _code, records = run_listen_with_log([0.9, 0.0, 0.0], log, interrupt_after=2)

    assert records[-1]["event"] == "session_end"
    assert records[-1]["elapsed_seconds"] > 0


def test_appending_a_second_session_keeps_the_first(tmp_path: Path) -> None:
    log = tmp_path / "wake.jsonl"

    run_listen_with_log([0.9], log)
    _code, records = run_listen_with_log([0.9], log)

    assert [r["event"] for r in records].count("session_start") == 2
    assert len([r for r in records if r["event"] == "detection"]) == 2


def test_no_log_flag_writes_no_file(tmp_path: Path) -> None:
    run_listen([0.9])

    assert list(tmp_path.iterdir()) == []


# --- reading a log back -------------------------------------------------------


def _log_lines(*records: dict) -> str:
    return "\n".join(json.dumps(r) for r in records) + "\n"


def test_a_half_written_final_line_is_skipped_not_fatal(tmp_path: Path) -> None:
    """Expected, not exceptional: the process can be killed mid-flush. Losing
    hours of good data over one truncated line would be the wrong trade."""
    log = tmp_path / "wake.jsonl"
    log.write_text(
        _log_lines(
            {"event": "session_start", "threshold": 0.5},
            {"event": "detection", "score": 0.7},
        )
        + '{"event": "detec',
        encoding="utf-8",
    )

    records = listen_wakeword.read_log(log)

    assert [r["event"] for r in records] == ["session_start", "detection"]


def test_blank_lines_and_non_records_are_ignored(tmp_path: Path) -> None:
    log = tmp_path / "wake.jsonl"
    log.write_text(
        '\n{"event": "session_start"}\n\n[1, 2]\n{"no_event": true}\n', encoding="utf-8"
    )

    assert listen_wakeword.read_log(log) == [{"event": "session_start"}]


def test_the_summary_reports_detections_per_hour() -> None:
    records = [
        {"event": "session_start", "threshold": 0.5},
        {"event": "detection", "score": 0.6},
        {"event": "detection", "score": 0.8},
        {"event": "session_end", "elapsed_seconds": 7200.0, "detections": 2},
    ]

    summary = listen_wakeword.summarise(records)

    assert "listening     2.00 hours (7200s)" in summary
    assert "detections    2" in summary
    assert "rate          1.00 per hour" in summary


def test_two_sessions_are_summed_not_spanned() -> None:
    """A log appended to over three evenings is three sessions. Dividing by
    the wall-clock gap between the first and last would divide by the nights
    in between and report a false-positive rate near zero."""
    records = [
        {"event": "session_start", "threshold": 0.5},
        {"event": "detection", "score": 0.6},
        {"event": "session_end", "elapsed_seconds": 1800.0},
        {"event": "session_start", "threshold": 0.5},
        {"event": "session_end", "elapsed_seconds": 1800.0},
    ]

    summary = listen_wakeword.summarise(records)

    assert "sessions      2" in summary
    assert "listening     1.00 hours (3600s)" in summary
    assert "rate          1.00 per hour" in summary


def test_a_session_with_no_footer_is_counted_and_flagged() -> None:
    records = [
        {"event": "session_start", "threshold": 0.5},
        {"event": "detection", "score": 0.6},
    ]

    summary = listen_wakeword.summarise(records)

    assert "(1 with no end record)" in summary
    assert "rate          n/a" in summary


def test_the_histogram_prints_empty_buckets_too() -> None:
    """The shape of the tail is the point. Hiding empty buckets makes a
    cluster at 0.5 look identical to one at 0.9."""
    records = [
        {"event": "session_start", "threshold": 0.5},
        {"event": "detection", "score": 0.95},
        {"event": "session_end", "elapsed_seconds": 3600.0},
    ]

    summary = listen_wakeword.summarise(records)

    assert "0.0-0.1     0" in summary
    assert "0.9-1.0     1  #" in summary


def test_a_score_of_exactly_one_lands_in_the_top_bucket() -> None:
    records = [
        {"event": "session_start"},
        {"event": "detection", "score": 1.0},
        {"event": "session_end", "elapsed_seconds": 3600.0},
    ]

    assert "0.9-1.0     1  #" in listen_wakeword.summarise(records)


def test_an_empty_log_says_so_rather_than_dividing_by_zero() -> None:
    assert listen_wakeword.summarise([]) == "No session found in this log."


def test_every_threshold_used_across_sessions_is_reported() -> None:
    records = [
        {"event": "session_start", "threshold": 0.5},
        {"event": "session_end", "elapsed_seconds": 60.0},
        {"event": "session_start", "threshold": 0.3},
        {"event": "session_end", "elapsed_seconds": 60.0},
    ]

    assert "threshold     0.3, 0.5" in listen_wakeword.summarise(records)


# --- the CLI ------------------------------------------------------------------


def test_summary_reads_a_log_and_opens_no_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An agent runs this afterwards, possibly on a machine with no mic."""
    log = tmp_path / "wake.jsonl"
    log.write_text(
        _log_lines(
            {"event": "session_start", "threshold": 0.5},
            {"event": "detection", "score": 0.6},
            {"event": "session_end", "elapsed_seconds": 3600.0},
        ),
        encoding="utf-8",
    )

    def explode(*_a, **_k):  # pragma: no cover - must not run
        raise AssertionError("--summary must not touch a device")

    monkeypatch.setattr(listen_wakeword, "listen", explode)
    monkeypatch.setattr(listen_wakeword, "list_devices", explode)

    assert main(["--summary", str(log)]) == 0
    assert "rate          1.00 per hour" in capsys.readouterr().out


def test_summary_on_a_missing_log_is_an_error_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--summary", str(tmp_path / "nope.jsonl")]) == 1
    assert "no log at" in capsys.readouterr().err


def test_the_log_flag_reaches_listen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict = {}
    monkeypatch.setattr(
        listen_wakeword, "listen", lambda *a, **k: seen.update(args=a, kwargs=k) or 0
    )

    main(["--log", str(tmp_path / "w.jsonl")])

    assert seen["kwargs"]["log_path"] == tmp_path / "w.jsonl"


def test_bare_log_and_summary_flags_default_to_the_same_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--log` then `--summary` with no path must read what was just written."""
    seen: dict = {}
    monkeypatch.setattr(
        listen_wakeword, "listen", lambda *a, **k: seen.update(kwargs=k) or 0
    )
    main(["--log"])

    read: dict = {}
    monkeypatch.setattr(
        listen_wakeword, "summarise_file", lambda p: read.update(path=p) or 0
    )
    main(["--summary"])

    assert seen["kwargs"]["log_path"] == read["path"]
    assert read["path"] == listen_wakeword.DEFAULT_LOG_DIR / "wakeword.jsonl"


def test_no_log_flag_leaves_log_path_none(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(
        listen_wakeword, "listen", lambda *a, **k: seen.update(kwargs=k) or 0
    )

    main([])

    assert seen["kwargs"]["log_path"] is None
