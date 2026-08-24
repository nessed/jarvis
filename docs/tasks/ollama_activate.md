# Ollama activation and validation

## Scope and ownership

This lane owns only `docs/tasks/ollama_activate.md` and `docs/context.md`.
It must not alter production code, dependencies, or configuration.

## Objective

Verify the local Ollama runtime is installed and reachable on loopback. Pull
exactly `nomic-embed-text` only if absent, verify it appears in `ollama list`,
exercise the local `/api/embed` endpoint using the fixed non-personal dimension
probe, and run the relevant local memory tests.

## Safety

Never display `.env` contents or secret values. No corpus ingestion or hosted
provider calls are permitted. If Ollama/runtime/model activation fails, record
the exact non-secret blocker and stop.

## Context update

Record the activation outcome, non-secret operational details, remaining
blocker if any, and exact validation evidence in `docs/context.md`.
