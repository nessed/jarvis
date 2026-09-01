---
id: phase4-prep
status: ready
lane: AUTO
priority: 2
phase: 4
blocked-on: none
files: infra/, docs/tasks/phase4-runbook.md
resources: none (nothing live exists yet)
---

# phase4-prep — write the Oracle/VPS side before the account exists

## Goal

Phase 4's agent work (blueprint 4.2–4.3) is fully specifiable today; only
the Oracle account (U7) is missing. Write everything in advance so the day
Ali does the signup sitting, `vps-harden-deploy` is execution, not design.
`infra/` currently holds a single `.gitkeep`.

## Steps

1. Terraform (or OCI CLI script — pick per what's testable without an
   account; record the choice and why in the runbook) for exactly one A1
   instance at **2 OCPU / 12 GB**, Ubuntu, in a variable region. The 2/12
   number is load-bearing — the 27 Aug provider audit
   (`docs/audit/blueprint-drift.md`, Oracle entry) records over-limit
   instances being auto-terminated since the 18 Aug enforcement date;
   the blueprint itself only says "provision at 2/12 from day one".
2. Hardening script: non-root user, key-only SSH, ufw (tunnel + SSH only),
   fail2ban, unattended-upgrades, Docker.
3. Containerize the bus + router: Dockerfile(s) + compose file. (The
   blueprint's third container, the web UI, is deliberately excluded —
   see PARKED.md's ambient-circle entry; no UI gets built yet.) The bus
   must run off-box unchanged except env; anything laptop-assuming it does
   (paths, localhost Ollama) gets flagged in the runbook — **do not
   restructure the bus here**, that's `bus-offbox-packaging`.
4. Named-tunnel plan: cloudflared as a service on the VPS pointing at the
   bus container; document what Ali must do in the Cloudflare dashboard
   vs what's scriptable.
5. `docs/tasks/phase4-runbook.md`: the exact ordered steps for U7 day —
   what Ali clicks, what the agent runs, how the webhook gets re-pointed,
   how rollback works (laptop keeps working as today until cutover).
6. Validate what's validatable offline: `terraform validate` /
   shellcheck / `docker build` of the bus image on this machine.

## Verification

`docker build` succeeds locally for the bus image (cite); terraform/
scripts pass their static validation (cite); full offline suite untouched
and green.

## Done when

`infra/` populated, runbook written, U7's entry stays a one-sitting job.

## Log

_(empty)_
