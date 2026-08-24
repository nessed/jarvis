# Webhook security verification lane

## Ownership

Own only this brief. Do not edit repository source, context, requirements, or
other task files. Do not commit.

## Task

Run a safe local verification that an unsigned POST to `/webhook` returns 403.
Use the live local listener if available; otherwise report the block. Do not
read, print, or alter any credential. Report only status/result.

## Context

Phase 0 requires an unsigned webhook request to fail with 403. The Meta tunnel
is currently unhealthy, so this check is independent of external reachability.
