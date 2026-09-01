# infra/ — the Oracle side of Phase 4

Written before the Oracle account exists, so U7 day is execution rather than
design. **The ordered steps live in `docs/tasks/phase4-runbook.md`.** This file
is the map.

```
infra/
├── terraform/                one A1 instance at 2 OCPU / 12 GB, and the
│   ├── versions.tf           minimum network around it
│   ├── variables.tf          region, compartment, AD, SSH key — no secrets
│   ├── main.tf               VCN, subnet, IGW, route table, security list
│   ├── outputs.tf            public IP, and the shape, read back
│   └── terraform.tfvars.example
├── scripts/
│   ├── harden.sh             non-root user, key-only SSH, ufw, fail2ban,
│   │                         unattended-upgrades, Docker
│   └── install-cloudflared.sh  named tunnel as a systemd service
└── docker/
    ├── Dockerfile            bus + router, arm64
    ├── requirements-bus.txt  the six packages the bus actually imports
    └── compose.yaml          one service, bound to loopback
```

## Three things worth knowing before reading the files

**2 OCPU / 12 GB is not a default to tune.** Oracle's Always Free ceiling is
4/24 across the tenancy, and since 18 Aug 2026 over-limit instances are
*terminated*, not refused (`docs/audit/blueprint-drift.md`, Oracle entry).
`variables.tf` rejects anything larger, and `outputs.tf` reads the shape back
so it can be checked before walking away.

**Nothing listens on the public internet except SSH.** The webhook arrives
through a Cloudflare named tunnel, which dials *outward* from the VPS. Three
layers say so independently: the OCI security list opens only 22, ufw denies
inbound except 22, and compose binds the bus to `127.0.0.1:8000`.

**The image carries three packages, not the repo.** `bus/`, `router/`, `db/`
and six pip dependencies. Not torch, not Kokoro, not the multi-gigabyte whisper
build tree, not Ali's wake-word recordings. `.dockerignore` at the repo root is
the second guard.

## Validated offline, on the laptop

```
terraform fmt -check -diff .      exit 0
terraform init && terraform validate
                                  Success! The configuration is valid.
shellcheck --severity=style infra/scripts/*.sh
                                  exit 0
```

Plus five checks standing in for the `docker build` this laptop cannot run —
compose parses, the bus pins match `requirements.txt` exactly, importing
`bus.main` + `router` + `db.jobs` pulls in no executor-side package, every
`COPY` source exists, and `bus.main:app` resolves. All five in the
`phase4-prep` task Log.

## Not here, on purpose

- **The web UI container** the blueprint's Phase 4 sketch mentions. "No UI
  until UI is necessary" is the standing decision; see `PARKED.md`.
- **The executor.** It is the laptop, by definition. Phase 4 moves the bus; the
  worker stays where the files, FL Studio and the NPU are.
- **Restructuring the bus** for off-box packaging. Flagged in the runbook,
  owned by `bus-offbox-packaging`.
