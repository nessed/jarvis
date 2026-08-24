# Status-recovery lane

## Scope and ownership

This lane owns only this task brief. It performs read-only recovery by reading
`docs/blueprint.md` (the technical specification) and `docs/context.md` (the
current build source of truth). It must not alter implementation, configuration,
or context.

## Required report

Report the active phase, completed and verified work, current blockers, the
next actions, and discrepancies between the blueprint and recorded state.

## Relevant blueprint detail

The project is currently executing the roadmap beginning with Phase 0 (secure
bus, durable queue, router, executor) and then Phase 1 local-first memory.
Fast-moving provider facts must be verified before relying on them. Update
`docs/context.md` after a completed subtask; this read-only recovery is not a
completed implementation subtask.
