# Offline next-work scan

## Scope

This lane owns only this brief and performs a read-only planning scan. It reads
the blueprint, build context, code, and tests to identify independent work that
does not require Ollama, external credentials, or a user dashboard.

## Required output

Recommend two or three prioritized, safe tasks with strict disjoint file
ownership. Do not alter production files or `docs/context.md`.

## Constraints

Phase 1 local memory is blocked only on installing/pulling its local embedding
model. No personal corpus may be read or ingested. Favor deterministic tests,
offline seams, and work that preserves the local-first privacy boundary.
