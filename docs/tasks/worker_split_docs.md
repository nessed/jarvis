# Dedicated WhatsApp worker split — documentation

## Approved decision

Ali approved separating the `whatsapp_webhook` executor path from slow
background work after a measured queue wait delayed the native WhatsApp typing
cue. The webhook remains enqueue-only.

## Documentation scope

Update only `docs/blueprint.md`, `docs/state.md`, and `docs/context.md`.
Record the architecture: a responsive worker claims only
`whatsapp_webhook`; a background worker claims every other registered kind,
including `distill_memory`, and owns distillation-chain seeding. The launcher
supervises both. Preserve the unfiltered poller CLI mode for diagnostics and
backward compatibility. Do not claim implementation is complete until its
lane verifies it.

## Out of scope

Code, tests, dependencies, process restarts, Meta configuration, and commits.
