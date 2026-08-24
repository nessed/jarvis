# Ollama installation lane

## Scope and ownership

This lane owns `docs/tasks/ollama_install.md`, `docs/context.md`, and the
non-secret Ollama settings in the ignored local `.env` file only. It must not
modify `requirements.txt` or production code.

## Objective

Install and start Ollama for Windows through an official/package-manager route,
pull exactly `nomic-embed-text`, configure the local embedding settings when
missing, then validate a local `/api/embed` request and relevant memory tests.

## Safety and acceptance

Use the loopback endpoint only (`http://127.0.0.1:11434`). Do not print or
record `.env` values. The intended Phase 1 model is `nomic-embed-text`; no
personal corpus is to be read or ingested. Update `docs/context.md` with the
outcome, operational commands/details, and remaining blocker if any.

## Final authorized route

The user explicitly authorized one final official installation attempt via the
Windows command published by Ollama: `irm https://ollama.com/install.ps1 | iex`.
Run it with the needed elevation, then verify the local runtime, pull exactly
`nomic-embed-text`, and run the loopback embedding smoke test. If UAC or a
security policy blocks it, stop and report that specific blocker without broad
retries.

The user subsequently gave explicit, informed approval to execute that exact
elevated remote-script command after the associated remote-code risk was
explained.
