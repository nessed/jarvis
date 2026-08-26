r"""Phase 1 acceptance probe.

This is the phase's actual success criterion, not a unit test: it drives the
real ``open_local_mem0_memory`` entry point against the live loopback Ollama,
performs real fact extraction, and asserts the fact comes back out of the
semantic index. It first passed by hand on 26 August 2026; this file exists so
it is re-runnable rather than a one-off transcript in ``docs/context.md``.

Run it explicitly (the default suite excludes ``live``):

    .venv\Scripts\python.exe -m pytest -q -m live tests/live

Requires: Ollama on 127.0.0.1:11434 with ``llama3.1:8b`` and
``nomic-embed-text`` pulled. No personal data is used; the probe sentence is
synthetic.
"""

from __future__ import annotations

import time

import pytest

from memory.runtime import open_local_mem0_memory

PROBE_FACT = "The generic workshop opens at nine."
PROBE_QUERY = "When does the generic workshop open?"

# Cold-start extraction measured at 35.146s on 26 August 2026 (CPU-only
# Ollama). 120s leaves headroom without letting a genuine hang run forever.
EXTRACTION_TIMEOUT_SECONDS = "120"


@pytest.mark.live
def test_remember_then_recall_round_trip(tmp_path) -> None:
    runtime = open_local_mem0_memory(
        tmp_path / "live-acceptance.db",
        environ={
            "OLLAMA_EMBEDDING_MODEL": "nomic-embed-text",
            "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
            "OLLAMA_FACT_EXTRACTION_TIMEOUT_SECONDS": EXTRACTION_TIMEOUT_SECONDS,
        },
    )
    try:
        started = time.monotonic()
        added = runtime.remember(PROBE_FACT)
        remember_seconds = time.monotonic() - started

        results = added.get("results") if isinstance(added, dict) else None
        assert results, f"remember() extracted no facts in {remember_seconds:.3f}s: {added!r}"

        recalled = runtime.recall(PROBE_QUERY)
        hits = recalled.get("results") if isinstance(recalled, dict) else None
        assert hits, f"recall() returned nothing for a fact just remembered: {recalled!r}"

        memories = " ".join(str(hit.get("memory", "")) for hit in hits).lower()
        assert "nine" in memories, f"recall() missed the remembered fact: {hits!r}"
        assert hits[0].get("score", 0) > 0.3, f"top hit scored too low to be a real match: {hits[0]!r}"
    finally:
        runtime.close()
