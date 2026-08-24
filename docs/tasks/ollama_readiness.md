# Ollama readiness recovery lane

## Scope and ownership

This lane owns only this recovery brief. It inspects the Phase 1 local embedding
prerequisites in `docs/blueprint.md`, `docs/context.md`, and relevant project
configuration/code. It may run read-only environment checks. It must not modify
production files or `docs/context.md`.

## Required output

Report Ollama installation/service and model readiness, the intended embedding
model, the exact outstanding action, likely resource expectations, and whether
network installation or a user handoff is necessary.

## Relevant blueprint detail

Phase 1 uses a laptop-local embedding stack: Ollama with `nomic-embed-text`,
sqlite-vec, and local-first memory. Personal corpus ingestion is opt-in and
must only process content deliberately placed in `ingest/`.
