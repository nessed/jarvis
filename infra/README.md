# infra/ — packaging the brain for a rented box

Written before the Oracle account existed, so U7 day was meant to be
execution rather than design. **Superseded 8 Sep 2026 (U17): the target is
now a rented x86 box Ali controls (AWS Lightsail/EC2, 2 GB, Mumbai), not
Oracle A1.** `terraform/` is kept as the Oracle fallback — nothing in it is
wrong, only not the current plan; AWS has no Terraform here on purpose (one
instance, stood up once by hand; see the runbook). **The ordered steps live
in `docs/tasks/phase4-runbook.md`.** This file is the map.

```
infra/
├── terraform/                  Oracle fallback: one A1 instance at 2 OCPU /
│   ├── versions.tf             12 GB, and the minimum network around it.
│   ├── variables.tf            No AWS equivalent — see the runbook for why.
│   ├── main.tf
│   ├── outputs.tf
│   └── terraform.tfvars.example
├── scripts/
│   ├── harden.sh                non-root user, key-only SSH, ufw, fail2ban,
│   │                            unattended-upgrades, Docker — provider-agnostic
│   └── install-cloudflared.sh   named tunnel as a systemd service — same
└── docker/
    ├── Dockerfile              the brain: bus + router + db + memory +
    │                           a named slice of executor/, linux/amd64
    ├── requirements-brain.txt  what that image imports, pinned to
    │                           requirements.txt's own versions
    └── compose.yaml            bus + an `ollama` sidecar for embeddings,
                                 both bound to loopback/the compose network
```

## Three things worth knowing before reading the files

**The Oracle numbers below describe the fallback, not the plan.** 2 OCPU /
12 GB and Oracle's Always Free ceiling (4/24 across the tenancy, over-limit
instances *terminated* since 18 Aug 2026 —
`docs/audit/blueprint-drift.md`) only matter if AWS capacity or pricing ever
sends Ali back to it. The AWS box is a plain 2 GB x86 instance with no
comparable free-tier ceiling to track.

**Nothing listens on the public internet except SSH.** The webhook arrives
through a Cloudflare named tunnel, which dials *outward* from the VPS. Layers
say so independently regardless of provider: the cloud firewall (OCI security
list or the AWS/Lightsail equivalent) opens only 22, `harden.sh`'s ufw denies
inbound except 22, and compose binds the bus to `127.0.0.1:8000` — the
`ollama` sidecar is not published to the host at all, only reachable from
`bus` on the compose network.

**The image now carries the brain, not just the inbox.** `bus/`, `router/`,
`db/`, all of `memory/`, and a named handful of `executor/` modules
(`conversation/`, `handlers/command_intent.py`, `handlers/outcome.py`,
`handlers/whatsapp.py`, `latency.py`, `notify.py`) — `conversation-inline-reply`
put recall/remember in the bus process, so the image has to carry what that
needs. Still not torch, not Kokoro, not the multi-gigabyte whisper build
tree, not Ali's wake-word recordings, not `executor/flp/` or
`executor/system_control/`. The repo-root `.dockerignore` is the second
guard, and `tests/infra/test_image_contents.py` greps every path the
Dockerfile actually copies for the banned imports so drift fails the offline
suite rather than showing up as a fat image on the box.

## Validated offline, on the laptop

```
terraform fmt -check -diff .      exit 0
terraform init && terraform validate
                                  Success! The configuration is valid.
shellcheck --severity=style infra/scripts/*.sh
                                  exit 0
```

Plus `tests/infra/`, standing in for the `docker build`/`docker compose
config` this laptop cannot run: the brain's pins match `requirements.txt`
exactly, `compose.yaml` parses and has the shape the runbook describes
(services, the loopback-bound port, the `brain-state`/`ollama-models`
volumes), importing `bus.main` + `router` + `db.jobs` + `memory.conversation`
+ the copied `executor/` slice pulls in no banned import, every Dockerfile
`COPY` source exists, and `bus.main:app` resolves. Cited in each packaging
task's Log.

## Not here, on purpose

- **The web UI container** the blueprint's Phase 4 sketch mentions. "No UI
  until UI is necessary" is the standing decision; see `PARKED.md`.
- **The executor's laptop-only halves.** Voice, FL Studio sorting, desktop
  control and batch extraction (`JARVIS_DISTILL=0` in compose) stay on the
  laptop, by definition (CLAUDE.md #3). Phase 4 moves the conversational
  reply path; those workers stay where the files, FL Studio and the NPU are.
- **An AWS Terraform module.** One instance, one sitting, console clicks —
  see the runbook's "Terraform, not the OCI CLI" section for why that
  reasoning does not carry over to AWS.
