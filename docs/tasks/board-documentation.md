# Board documentation lane

## Scope

Own `docs/plan.md` and `CLAUDE.md` only. Do not edit the claim tool, its tests,
`.gitignore`, or production code.

## Objective

Convert the work board from a hand-edited coordination note to documentation
for the atomic `tools/work_board_claim.py` workflow. Claims must cover files
and external resources, not role-owned directories. Correct reviewed stale or
unsupported statements without changing architecture.

## Required corrections

- Remove the obsolete WhatsApp memory-write job and its dependency.
- Include `memory/conversation.py` in the memory contention map.
- Mark router sequencing as proposed unless verified by the implementation.
- Require live headers/account checks for provider capacity.
- Replace “zero collision” guarantees with claim-required wording.
- Document test-workspace, pre-commit, Meta/tunnel, and staleness constraints.

## Verification

Run focused `rg` checks proving no mutable Markdown claim/request block or
obsolete WhatsApp-memory-write job remains, and that the CLI guidance and
required resource rules are present.
