---
id: bus-offbox-packaging
status: blocked
lane: AUTO
priority: 3
phase: 4
blocked-on: vps-harden-deploy (enqueue-classifier landed 2 Sep 2026)
files: bus/main.py (hot), bus/whatsapp_client.py (hot), other bus/ modules per runbook findings, tests/bus/
resources: none until live
---

# bus-offbox-packaging — stub

Whatever laptop-assumptions `phase4-prep` step 3 flags in the bus get
resolved here, plus the three-way enqueue-time routing from blueprint 4.4
(needs-laptop → queue; cloud-capable → Routine trigger; trivial → inline
on VPS). Not buildable earlier — plan.md's warning against inventing
scope for it stands. Whoever unblocks it expands this stub into a real
guide from the runbook's findings.

## Log

_(empty)_
