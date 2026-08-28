# Lane: board claim tool

## Scope

Own `tools/work_board_claim.py`, `tests/tools/test_work_board_claim.py`, this
brief, and a narrowly scoped `.gitignore` entry if runtime state needs one.

## Objective

Implement a Python 3.11 standard-library CLI that makes work-board claims
atomic across local processes. It must support `claim`, `list`, and `release`.
Claims record a role and work item, reject overlapping repository-relative file
paths and duplicate named resource keys, and keep transient state in ignored
`.work-board/`.

## Safety and verification

Use an exclusive lock file for every read-modify-write operation. Never read or
print environment values. Treat malformed persistent state as an error without
overwriting it. Prune only demonstrably stale claims (expired and owner PID no
longer alive). Tests must cover collision, independent claims, resource
collision, release, and stale/malformed state. No commits or dependency edits.
