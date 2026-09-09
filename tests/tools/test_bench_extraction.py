from __future__ import annotations

import json

import pytest

from tools.bench_extraction import (
    ChunkResult,
    render,
    run_bench,
    run_chunk,
    synthetic_chunk,
)


def _valid_response(n_facts: int = 2) -> str:
    return json.dumps({"memory": [{"id": str(i), "text": f"fact {i}", "attributed_to": "user"} for i in range(n_facts)]})


class TestSyntheticChunk:
    def test_produces_exactly_the_requested_word_count(self) -> None:
        for n in (1, 96, 288, 480, 768):
            assert len(synthetic_chunk(n).split()) == n

    def test_is_deterministic(self) -> None:
        assert synthetic_chunk(200) == synthetic_chunk(200)

    def test_a_different_seed_does_not_start_identically(self) -> None:
        assert synthetic_chunk(50, seed=0) != synthetic_chunk(50, seed=3)


class TestRunChunk:
    def test_a_valid_schema_conforming_response_counts_its_facts(self) -> None:
        result = run_chunk("some input", call=lambda text: _valid_response(3), sample_cpu=False)

        assert result.valid_json is True
        assert result.facts == 3
        assert result.error is None

    def test_an_empty_memory_list_is_still_valid(self) -> None:
        result = run_chunk("some input", call=lambda text: json.dumps({"memory": []}), sample_cpu=False)

        assert result.valid_json is True
        assert result.facts == 0

    def test_unparseable_json_is_recorded_not_raised(self) -> None:
        result = run_chunk("some input", call=lambda text: "not json at all", sample_cpu=False)

        assert result.valid_json is False
        assert result.facts == 0
        assert "invalid against ExtractionResponse" in result.error

    def test_json_that_does_not_match_the_schema_is_invalid(self) -> None:
        """`memory` items require `text`; an item with only the wrong field fails validation.
        (A response with an unrecognized top-level key but no `memory` list is
        NOT a case this catches -- ExtractionResponse.memory defaults to `[]`,
        and a permissive schema accepting extra junk alongside valid facts is
        the real production behaviour, not a bug this benchmark should paper
        over by tightening the schema it exists to measure.)"""
        malformed = json.dumps({"memory": [{"attributed_to": "user"}]})
        result = run_chunk("some input", call=lambda text: malformed, sample_cpu=False)

        assert result.valid_json is False

    def test_a_backend_exception_is_caught_and_recorded(self) -> None:
        def failing_call(text: str) -> str:
            raise TimeoutError("backend did not respond")

        result = run_chunk("some input", call=failing_call, sample_cpu=False)

        assert result.valid_json is False
        assert result.error.startswith("TimeoutError")

    def test_word_count_is_measured_from_the_input_not_the_output(self) -> None:
        result = run_chunk("one two three four five", call=lambda text: _valid_response(0), sample_cpu=False)

        assert result.words == 5

    def test_elapsed_seconds_is_measured_around_the_call(self) -> None:
        import time

        def slow_call(text: str) -> str:
            time.sleep(0.05)
            return _valid_response(0)

        result = run_chunk("x", call=slow_call, sample_cpu=False)

        assert result.elapsed_seconds >= 0.03  # clock granularity, not a real budget


class TestRunBench:
    def test_runs_one_chunk_per_requested_size_in_order(self) -> None:
        seen_words: list[int] = []

        def call(text: str) -> str:
            seen_words.append(len(text.split()))
            return _valid_response(1)

        results = run_bench(call=call, word_counts=(10, 20, 30), sample_cpu=False)

        assert [r.words for r in results] == [10, 20, 30]
        assert seen_words == [10, 20, 30]

    def test_a_failure_on_one_size_does_not_abort_the_rest(self) -> None:
        def call(text: str) -> str:
            if len(text.split()) == 20:
                raise ConnectionError("refused")
            return _valid_response(1)

        results = run_bench(call=call, word_counts=(10, 20, 30), sample_cpu=False)

        assert [r.valid_json for r in results] == [True, False, True]


class TestRender:
    def test_includes_every_result_and_its_error_text(self) -> None:
        results = [
            ChunkResult(words=96, elapsed_seconds=26.2, valid_json=True, facts=13),
            ChunkResult(words=288, elapsed_seconds=1.0, valid_json=False, facts=0, error="TimeoutError: x"),
        ]

        out = render(results)

        assert "96" in out and "26.2" in out and "13" in out
        assert "TimeoutError: x" in out


class TestBackendCallShapes:
    """The two backends must send what their own API actually expects --
    covered without a live server via httpx's MockTransport."""

    def test_ollama_call_sends_the_schema_under_format_when_constrained(self, monkeypatch) -> None:
        import httpx

        from tools.bench_extraction import ollama_call

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"message": {"content": _valid_response(0)}})

        monkeypatch.setattr(
            httpx, "post", lambda url, json, timeout: httpx.Client(transport=httpx.MockTransport(handler)).post(url, json=json)
        )

        call = ollama_call("http://127.0.0.1:11434", "llama3.1:8b", constrained=True, timeout_seconds=5.0)
        call("hello")

        assert isinstance(captured["payload"]["format"], dict)
        assert captured["payload"]["format"]["title"] == "ExtractionResponse"

    def test_ollama_call_sends_bare_json_format_when_unconstrained(self, monkeypatch) -> None:
        import httpx

        from tools.bench_extraction import ollama_call

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"message": {"content": _valid_response(0)}})

        monkeypatch.setattr(
            httpx, "post", lambda url, json, timeout: httpx.Client(transport=httpx.MockTransport(handler)).post(url, json=json)
        )

        call = ollama_call("http://127.0.0.1:11434", "llama3.1:8b", constrained=False, timeout_seconds=5.0)
        call("hello")

        assert captured["payload"]["format"] == "json"

    def test_llamacpp_call_sends_an_openai_style_json_schema_response_format(self, monkeypatch) -> None:
        import httpx

        from tools.bench_extraction import llamacpp_call

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": _valid_response(0)}}]})

        monkeypatch.setattr(
            httpx, "post", lambda url, json, timeout: httpx.Client(transport=httpx.MockTransport(handler)).post(url, json=json)
        )

        call = llamacpp_call("http://127.0.0.1:8090", "qwen3-4b", constrained=True, timeout_seconds=5.0)
        call("hello")

        rf = captured["payload"]["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["schema"]["title"] == "ExtractionResponse"

    def test_ollama_call_caps_generation_length(self, monkeypatch) -> None:
        """The schema's fact list has no maxItems -- found live, grammar-
        constrained decoding can degenerate into an unbounded array instead
        of stopping. Every call must bound num_predict/max_tokens itself."""
        import httpx

        from tools.bench_extraction import ollama_call

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"message": {"content": _valid_response(0)}})

        monkeypatch.setattr(
            httpx, "post", lambda url, json, timeout: httpx.Client(transport=httpx.MockTransport(handler)).post(url, json=json)
        )

        call = ollama_call("http://127.0.0.1:11434", "llama3.1:8b", constrained=True, timeout_seconds=5.0, max_tokens=42)
        call("hello")

        assert captured["payload"]["options"]["num_predict"] == 42

    def test_llamacpp_call_caps_generation_length(self, monkeypatch) -> None:
        import httpx

        from tools.bench_extraction import llamacpp_call

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": _valid_response(0)}}]})

        monkeypatch.setattr(
            httpx, "post", lambda url, json, timeout: httpx.Client(transport=httpx.MockTransport(handler)).post(url, json=json)
        )

        call = llamacpp_call("http://127.0.0.1:8090", "qwen3-4b", constrained=True, timeout_seconds=5.0, max_tokens=42)
        call("hello")

        assert captured["payload"]["max_tokens"] == 42
