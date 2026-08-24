# AGENTS rules hardening

## Scope

Harden `AGENTS.md` so an agent cannot replace a blueprint-mandated component,
claim unverified success, or make global Git configuration without an explicit
ask-first step.

## Blueprint context

Phase 1.1 requires Ollama, `nomic-embed-text`, sqlite-vec, a facts table, and
Mem0 in self-host mode wrapping those components. Mem0 remains required; this
task does not reconcile the blueprint or change implementation.

## Owned paths

- `AGENTS.md`
- `docs/tasks/agents_rules_hardening.md`

## Required changes

- Limit source verification to provider facts; preserve architecture and phase
  choices as binding decisions unless a deviation is reported before coding.
- Ban unapproved substitutions and after-the-fact deviation documentation.
- Require command/test evidence for success claims and treat missing subagent
  completion as failed verification.
- Require terse reports to say what specified work was not done.
- Require an ask-first step for global Git configuration.

## Non-goals

Do not touch the blueprint, context, code, dependencies, Git state, or commit.
