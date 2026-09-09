---
id: vps-harden-deploy
status: blocked
lane: AUTO
priority: 2
phase: 4
blocked-on: U17 (rented box exists) — bus-offbox-packaging landed 9 Sep 2026
files: infra/, docs/tasks/phase4-runbook.md, docs/state.md
resources: cloudflare-tunnel, meta-webhook (at cutover)
---

# vps-harden-deploy — bring the brain up on the rented box

## Gate (rewritten 8 Sep 2026)

U17: the rented server exists and the agent has SSH (AWS via Ali's
brother, 2 GB, Mumbai, per Q17-D1 — or whatever Ali actually provisions;
this task adapts, the runbook has both sections). U7 (Oracle) is
superseded, not required. And `bus-offbox-packaging`, which is what gets
deployed.

## Steps

Execute the runbook's AWS section: harden (non-root, key-only SSH, ufw,
fail2ban, unattended-upgrades, Docker), `docker compose up -d --build`
(the first real image build — the laptop has no Docker, so build failures
surface here; fix in `infra/` and write them back into the runbook),
pull `nomic-embed-text` into the sidecar, stand up the **named**
Cloudflare tunnel (claim `cloudflare-tunnel`), re-point Meta once with
`tools/repoint_webhook.py` (claim `meta-webhook`), verify. The laptop
keeps its Quick Tunnel path as rollback until a full text round-trips
through the box with `path=inline`.

## Done when

Laptop fully shut down: a text from the phone gets a reply, `reply-latency`
line on the box shows `path=inline`; a laptop-only action sent meanwhile
stays queued and is picked up when the laptop returns (cite both);
rollback documented; Phase 4 topology recorded in `docs/state.md`.

## Log

_(empty)_
