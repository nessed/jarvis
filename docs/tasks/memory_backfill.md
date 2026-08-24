# Phase 1 local backfill runner

## Blueprint basis

Blueprint Phase 1.3 requires a resumable backfill from explicitly selected
notes and WhatsApp exports, with checkpoint state that identifies the source
file and offset. The existing `ingest.pipeline` only discovers, manifests, and
chunks local files; it does not yet orchestrate durable chunk processing.

## Strict ownership

Own only `ingest/backfill.py`, `tests/ingest/test_backfill.py`, and this brief.
Do not modify `ingest/pipeline.py`, package initializers, memory code, queue
code, requirements, context, or any existing tests.

## Task

Build an injected, local-only backfill runner using the existing
`IngestManifest`, `Chunk`, and `BackfillCheckpoint` contracts. It must process
only a caller-selected manifest/source, call an injected fact sink for each
chunk, and advance its serializable checkpoint only after that call succeeds.
It must support an interrupted run resuming at the supplied checkpoint and
reject a manifest mismatch or invalid/stale checkpoint without reading a
different source.

## Non-goals

Do not discover personal files beyond the supplied intake path, read an actual
corpus, call Ollama or hosted LLMs, extract facts with an LLM, enqueue jobs, or
wire the bus. Do not change the chunking/parser policy.

## Tests and dependencies

Use temporary files plus an in-memory fake sink. Cover normal order,
failure-without-advance, resume, manifest mismatch, and bounds validation.
No new dependency is expected; do not edit `requirements.txt`. If one becomes
unavoidable, append only its name and rationale to `docs/tasks/deps-memory_ingest.txt`.
