---
id: vps-harden-deploy
status: blocked
lane: AUTO
priority: 2
phase: 4
blocked-on: U7, phase4-prep
files: infra/, docs/tasks/phase4-runbook.md
resources: cloudflare-tunnel, meta-webhook (at cutover)
---

# vps-harden-deploy — execute the runbook on the real box

## Gate

U7 (Oracle account + instance exist) and `phase4-prep` (the runbook).

## Steps

Execute `docs/tasks/phase4-runbook.md` as written: provision at exactly
2 OCPU/12GB, harden (non-root, key-only SSH, ufw, fail2ban,
unattended-upgrades, Docker), deploy bus+router containers, stand up the
named tunnel, re-point the Meta webhook (claim `meta-webhook` +
`cloudflare-tunnel`), verify handshake, keep the laptop path as rollback
until a full live message round-trips through the VPS. Deviations from
the runbook get written back into it.

## Done when

A WhatsApp message round-trips through the VPS-hosted bus with the laptop
executor polling remotely (cite logs); rollback path documented; Phase 4
topology recorded in state.md.

## Log

_(empty)_
