# Phase 1 lane: corpus-safe ingestion

## Ownership

Own only `ingest/`, `tests/ingest/`, and `docs/tasks/deps-memory_ingest.txt`.
Do not edit `memory/`, `bus/`, requirements, docs, or other tests. Do not
commit.

## Task

Build a local-only ingestion foundation that accepts user-selected files only,
normalizes text, chunks deterministic note/chat input, and tracks resumable
per-file progress without ingesting anything by default. The default intake
directory may exist but must remain empty/ignored as appropriate. Define
manifest/checkpoint data safe for interrupted backfills. Add unit tests using
temporary files; do not inspect user folders or WhatsApp data.

## Phase 1 context

Blueprint section 1.2 makes user-selected notes and exported WhatsApp `.txt`
files the privacy boundary. Section 1.3 requires a resumable chunk pipeline.
No LLM fact extraction or remote uploads in this lane.
