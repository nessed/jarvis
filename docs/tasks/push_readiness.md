# Push-readiness inspection

## Scope

This lane owns only this recovery brief. It performs read-only Git inspection:
current branch, remotes, working-tree status, and recent commit identity.

## Constraints

Do not stage, commit, push, or edit any project file beyond this brief. Report
whether the configured branch/remote is unambiguous and distinguish task-related
uncommitted files from unrelated changes.
