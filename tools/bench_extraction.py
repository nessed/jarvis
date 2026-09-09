r"""Compare fact-extraction backends on synthetic chunks: wall time, valid-JSON
rate, facts extracted -- the numbers `extraction-model-spike` exists to
produce.

Neither backend is started by this tool. Point it at a server already
running:

    ollama serve                                          (already on by default)
    .tools\llama.cpp\llama-server.exe -m <gguf> --port 8090 --reasoning off

Then:

    .venv\Scripts\python.exe -m tools.bench_extraction --backend ollama \
        --model llama3.1:8b --base-url http://127.0.0.1:11434
    .venv\Scripts\python.exe -m tools.bench_extraction --backend ollama \
        --model llama3.1:8b --base-url http://127.0.0.1:11434 --unconstrained
    .venv\Scripts\python.exe -m tools.bench_extraction --backend llamacpp \
        --model qwen3-4b --base-url http://127.0.0.1:8090

The schema is `memory.mem0_wrapper.ExtractionResponse` -- the real one the
live path validates against
(``docs/blockers/mem0-extraction-not-schema-constrained.md``) -- not a
schema invented for this benchmark. **Synthetic chunks only.** Nothing here
reads `ingest/data/` or the memory database; the fixture text is generated
from a fixed template, never Ali's own words.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import httpx
from pydantic import ValidationError

from memory.mem0_wrapper import ExtractionResponse

DEFAULT_CHUNK_WORD_COUNTS = (96, 288, 480, 768)

# One self-contained, plausible turn, repeated and trimmed to hit an exact
# word count. Synthetic on purpose -- see the module docstring.
_TEMPLATE_SENTENCES = (
    "I moved my dentist appointment to next Tuesday afternoon because the "
    "original slot conflicted with a work call.",
    "My sister is visiting from Lahore this weekend and we are planning to "
    "cook biryani together on Saturday night.",
    "I finally finished reading the economics textbook chapter on monetary "
    "policy and found the section on inflation targeting the most useful.",
    "The new keyboard I ordered arrived a day late but the mechanical "
    "switches feel much better than my old one for long typing sessions.",
    "I decided to switch my gym schedule to early mornings starting next "
    "month since evenings keep getting interrupted by other commitments.",
    "My favorite coffee shop near campus started serving a new seasonal "
    "blend that I want to try before the semester gets too busy.",
    "I am thinking about learning basic woodworking as a weekend hobby "
    "once the current project deadline at work is out of the way.",
    "The car needs an oil change soon, probably within the next two weeks, "
    "based on the mileage since the last service.",
)


def synthetic_chunk(word_count: int, *, seed: int = 0) -> str:
    """Deterministic synthetic text of exactly ``word_count`` words.

    Sentences repeat in a fixed rotation (offset by ``seed`` so different
    chunk sizes don't all start identically), then the final sentence is
    truncated to land on the exact count -- the blocker's own reproduction
    measured specific sizes (96/288/480/768 words), and a benchmark that
    silently rounds those would stop being comparable to it.
    """
    words: list[str] = []
    index = seed
    while len(words) < word_count:
        words.extend(_TEMPLATE_SENTENCES[index % len(_TEMPLATE_SENTENCES)].split())
        index += 1
    return " ".join(words[:word_count])


EXTRACTION_SYSTEM_PROMPT = (
    "You are a Memory Extractor. Read the message below and extract every "
    "distinct, memorable fact, preference, plan, or event as a separate "
    "self-contained statement. Return ONLY valid JSON parsable by "
    'json.loads(), no other text, in exactly this structure: {"memory": '
    '[{"id": "0", "text": "...", "attributed_to": "user"}]}. "id" is a '
    'sequential string starting at "0". If nothing is worth extracting, '
    'return {"memory": []}.'
)


@dataclass(frozen=True)
class ChunkResult:
    words: int
    elapsed_seconds: float
    valid_json: bool
    facts: int
    cpu_percent_avg: float | None = None
    error: str | None = None


@dataclass
class CpuSampler:
    """Samples system-wide CPU% on a background thread while a call runs.

    ``psutil.cpu_percent(interval=...)`` blocks for ``interval`` seconds,
    so it cannot run on the same thread that is waiting on the HTTP call --
    this thread owns the sampling loop and the caller reads ``average()``
    once the call returns.
    """

    samples: list[float] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        import psutil

        def _loop() -> None:
            psutil.cpu_percent(interval=None)  # discard the meaningless first reading
            while not self._stop.is_set():
                self.samples.append(psutil.cpu_percent(interval=0.5))

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop_and_average(self) -> float | None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        return (sum(self.samples) / len(self.samples)) if self.samples else None


Call = Callable[[str], str]


def run_chunk(chunk_text: str, *, call: Call, sample_cpu: bool = True) -> ChunkResult:
    """Time one extraction call and validate its output against the real schema.

    Any exception from ``call`` (timeout, connection refused, non-2xx) is
    caught and recorded as this chunk's error rather than raised -- one
    backend failing on one size must not abort the whole comparison table.
    """
    sampler = CpuSampler() if sample_cpu else None
    if sampler is not None:
        sampler.start()

    started = time.monotonic()
    try:
        raw = call(chunk_text)
    except Exception as exc:  # noqa: BLE001 -- a benchmark must survive any backend failure
        elapsed = time.monotonic() - started
        cpu = sampler.stop_and_average() if sampler is not None else None
        return ChunkResult(
            words=len(chunk_text.split()),
            elapsed_seconds=elapsed,
            valid_json=False,
            facts=0,
            cpu_percent_avg=cpu,
            error=f"{type(exc).__name__}: {exc}",
        )
    elapsed = time.monotonic() - started
    cpu = sampler.stop_and_average() if sampler is not None else None

    try:
        parsed = ExtractionResponse.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        return ChunkResult(
            words=len(chunk_text.split()),
            elapsed_seconds=elapsed,
            valid_json=False,
            facts=0,
            cpu_percent_avg=cpu,
            error=f"invalid against ExtractionResponse: {type(exc).__name__}",
        )
    return ChunkResult(
        words=len(chunk_text.split()),
        elapsed_seconds=elapsed,
        valid_json=True,
        facts=len(parsed.memory),
        cpu_percent_avg=cpu,
    )


def _messages(chunk_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": chunk_text},
    ]


#: `ExtractionResponse.memory` has no `maxItems` -- a schema a real chunk
#: (12-15 facts, per the blocker's own reproduction) never approaches. Found
#: live during this task: an unbounded array production lets grammar-
#: constrained decoding degenerate into an arbitrarily long list of
#: near-empty items instead of stopping, so every call caps generation
#: rather than trusting the model (or the grammar) to stop on its own. 800
#: tokens comfortably covers 15 facts at the schema's own field lengths.
DEFAULT_MAX_TOKENS = 800


def ollama_call(
    base_url: str, model: str, *, constrained: bool, timeout_seconds: float, max_tokens: int = DEFAULT_MAX_TOKENS
) -> Call:
    """A ``call`` bound to Ollama's ``/api/chat``, schema-constrained or not.

    ``format`` is the Mem0/Ollama constrained-decoding lever the blueprint's
    §1.3 asks for and the live path (as of the linked blocker) does not use.
    """
    schema: dict[str, Any] | str = ExtractionResponse.model_json_schema() if constrained else "json"

    def call(chunk_text: str) -> str:
        response = httpx.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": _messages(chunk_text),
                "format": schema,
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]

    return call


def llamacpp_call(
    base_url: str, model: str, *, constrained: bool, timeout_seconds: float, max_tokens: int = DEFAULT_MAX_TOKENS
) -> Call:
    """A ``call`` bound to llama.cpp's OpenAI-compatible ``/v1/chat/completions``.

    llama.cpp turns a JSON-schema ``response_format`` into a grammar
    internally -- the "JSON-schema grammar" the task asks for -- so this is
    the schema-constrained path by construction; there is no meaningful
    "unconstrained" mode to compare against here the way Ollama's bare
    ``format="json"`` gives one, since ``constrained=False`` still asks for
    JSON, just without a schema pinning its shape.
    """
    response_format = (
        {"type": "json_schema", "json_schema": {"name": "extraction", "schema": ExtractionResponse.model_json_schema()}}
        if constrained
        else {"type": "json_object"}
    )

    def call(chunk_text: str) -> str:
        response = httpx.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            json={
                "model": model,
                "messages": _messages(chunk_text),
                "response_format": response_format,
                "stream": False,
                "max_tokens": max_tokens,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    return call


BACKENDS: dict[str, Callable[..., Call]] = {"ollama": ollama_call, "llamacpp": llamacpp_call}


def run_bench(
    *,
    call: Call,
    word_counts: Sequence[int] = DEFAULT_CHUNK_WORD_COUNTS,
    sample_cpu: bool = True,
) -> list[ChunkResult]:
    return [run_chunk(synthetic_chunk(n), call=call, sample_cpu=sample_cpu) for n in word_counts]


def render(results: Sequence[ChunkResult]) -> str:
    lines = [f"{'words':>6}{'seconds':>10}{'valid':>7}{'facts':>7}{'cpu%':>7}  error"]
    for r in results:
        cpu = f"{r.cpu_percent_avg:.0f}" if r.cpu_percent_avg is not None else "-"
        lines.append(
            f"{r.words:>6}{r.elapsed_seconds:>10.1f}{str(r.valid_json):>7}{r.facts:>7}{cpu:>7}  {r.error or ''}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", choices=sorted(BACKENDS), required=True)
    parser.add_argument("--model", required=True, help="model name as the backend's own API expects it")
    parser.add_argument("--base-url", required=True, help="e.g. http://127.0.0.1:11434 or http://127.0.0.1:8090")
    parser.add_argument("--unconstrained", action="store_true", help="skip the JSON-schema constraint")
    parser.add_argument(
        "--sizes", type=lambda s: tuple(int(x) for x in s.split(",")), default=DEFAULT_CHUNK_WORD_COUNTS
    )
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="generation cap; the schema's open-ended fact list has no maxItems, "
        "so a real run must bound this itself or risk a runaway grammar loop",
    )
    parser.add_argument("--no-cpu-sample", action="store_true", help="skip psutil sampling")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    call = BACKENDS[args.backend](
        args.base_url,
        args.model,
        constrained=not args.unconstrained,
        timeout_seconds=args.timeout_seconds,
        max_tokens=args.max_tokens,
    )
    results = run_bench(call=call, word_counts=args.sizes, sample_cpu=not args.no_cpu_sample)

    if args.json:
        print(json.dumps([vars(r) for r in results], indent=2))
    else:
        print(render(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
