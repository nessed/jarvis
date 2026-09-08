"""Reading the reply-latency lines back out of a worker log."""

from __future__ import annotations

import json

import pytest

from tools.reply_latency import (
    MIN_SAMPLES_FOR_P95,
    NoSamplesError,
    main,
    parse_line,
    percentile,
    read_samples,
    render,
    summarise,
)

# The real logging format from executor/poller.py's basicConfig, so the parser
# is exercised against the prefix it will actually meet.
PREFIX = "2026-09-08 19:04:11,882 INFO executor.latency: "


def _line(job: str, **stages: int) -> str:
    fields = " ".join(f"{name}_ms={value}" for name, value in stages.items())
    return f"{PREFIX}reply-latency job={job} kind=whatsapp_webhook {fields}\n"


def _log(tmp_path, *lines: str):
    path = tmp_path / "whatsapp-worker.out.log"
    path.write_text("".join(lines), encoding="utf-8")
    return path


class TestParsing:
    def test_a_latency_line_becomes_a_record(self) -> None:
        record = parse_line(_line("abc", total=9840, queue_wait=1200, model=3900))

        assert record == {
            "job": "abc",
            "kind": "whatsapp_webhook",
            "total": 9840,
            "queue_wait": 1200,
            "model": 3900,
        }

    def test_an_ordinary_log_line_is_not_a_sample(self) -> None:
        assert parse_line(f"{PREFIX}whatsapp typing indicator sent (job=abc)\n") is None

    def test_a_line_without_a_total_is_ignored(self) -> None:
        assert parse_line(f"{PREFIX}reply-latency job=abc kind=x model_ms=10\n") is None

    def test_a_truncated_line_costs_one_sample_not_the_run(self, tmp_path) -> None:
        path = _log(
            tmp_path,
            _line("a", total=1000, model=900),
            f"{PREFIX}reply-latency job=b kind=whatsapp_webhook total_ms=notanumb",
        )

        assert [s["job"] for s in read_samples([path])] == ["a"]

    def test_a_missing_log_is_not_an_error(self, tmp_path) -> None:
        assert read_samples([tmp_path / "never-ran.log"]) == []


class TestPercentiles:
    def test_nearest_rank_returns_an_observed_value(self) -> None:
        values = [100, 200, 300, 400]

        assert percentile(values, 0.50) == 200
        assert percentile(values, 0.95) == 400

    def test_one_sample_is_its_own_percentile(self) -> None:
        assert percentile([42], 0.95) == 42

    def test_percentile_of_nothing_is_an_error_not_a_zero(self) -> None:
        with pytest.raises(ValueError):
            percentile([], 0.5)


class TestSummary:
    def test_stages_are_summarised_across_jobs(self, tmp_path) -> None:
        path = _log(
            tmp_path,
            _line("a", total=1000, model=900, recall=100),
            _line("b", total=3000, model=2800, recall=200),
            _line("c", total=2000, model=1900, recall=100),
        )

        summary = summarise(read_samples([path]))

        assert summary["jobs"] == 3
        assert summary["stages"]["total"]["p50_ms"] == 2000
        assert summary["stages"]["total"]["max_ms"] == 3000
        assert summary["stages"]["recall"]["samples"] == 3

    def test_stages_come_out_in_the_order_they_happen(self, tmp_path) -> None:
        path = _log(tmp_path, _line("a", remember=10, model=900, queue_wait=50, total=1000))

        stages = list(summarise(read_samples([path]))["stages"])

        assert stages == ["queue_wait", "model", "remember", "total"]

    def test_a_stage_only_some_jobs_have_is_counted_only_where_it_ran(self, tmp_path) -> None:
        path = _log(
            tmp_path,
            _line("text", total=1000, model=900),
            _line("voice", total=9000, model=900, stt=4000, tts=3000),
        )

        summary = summarise(read_samples([path]))

        assert summary["stages"]["stt"]["samples"] == 1
        assert summary["stages"]["model"]["samples"] == 2

    def test_last_n_windows_the_most_recent_jobs(self, tmp_path) -> None:
        path = _log(tmp_path, *[_line(str(i), total=1000 * i) for i in range(1, 6)])

        summary = summarise(read_samples([path]), last=2)

        assert summary["jobs"] == 2
        assert summary["stages"]["total"]["p50_ms"] == 4000

    def test_a_small_sample_says_its_p95_is_not_one(self, tmp_path) -> None:
        path = _log(tmp_path, _line("a", total=1000))

        summary = summarise(read_samples([path]))

        assert summary["p95_is_meaningful"] is False
        assert f"fewer than {MIN_SAMPLES_FOR_P95}" in render(summary)

    def test_enough_samples_stops_the_warning(self, tmp_path) -> None:
        path = _log(tmp_path, *[_line(str(i), total=1000) for i in range(MIN_SAMPLES_FOR_P95)])

        summary = summarise(read_samples([path]))

        assert summary["p95_is_meaningful"] is True
        assert "fewer than" not in render(summary)

    def test_no_samples_is_an_error_not_an_empty_table(self) -> None:
        with pytest.raises(NoSamplesError):
            summarise([])


class TestCommandLine:
    def test_it_prints_a_table(self, tmp_path, capsys) -> None:
        path = _log(tmp_path, _line("a", total=1000, model=900))

        assert main(["--log", str(path)]) == 0

        out = capsys.readouterr().out
        assert "1 replied job(s)" in out
        assert "model" in out
        assert "0.90s" in out

    def test_json_is_machine_readable(self, tmp_path, capsys) -> None:
        path = _log(tmp_path, _line("a", total=1234, model=900))

        assert main(["--log", str(path), "--json"]) == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["stages"]["total"]["p50_ms"] == 1234

    def test_an_empty_log_exits_nonzero_and_says_where_it_looked(self, tmp_path, capsys) -> None:
        path = tmp_path / "quiet.log"
        path.write_text("nothing here\n", encoding="utf-8")

        assert main(["--log", str(path)]) == 1
        assert "quiet.log" in capsys.readouterr().err
