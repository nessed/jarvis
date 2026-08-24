# Offline integration validation

## Scope

This lane owns only this brief and runs the repository's offline test suite.
It must not change production code, configuration, or `docs/context.md`.

## Validation command

Run the project virtual environment's pytest suite (`.venv\\Scripts\\python.exe
-m pytest -q`). The existing test corpus uses injected fakes/transports and
temporary local files; do not run live provider calls, Ollama checks, browser
automation, or credential-dependent diagnostics.

## Report

Return the exact command/result and identify any cross-lane regression or
environmental warning. No implementation work belongs in this lane.
