# Phase 4 runbook — moving the brain off the laptop

Written 2 Sep 2026, before the Oracle account exists, so that U7 day was
execution rather than design. **Superseded 8 Sep 2026 (U17): the target moved
from Oracle A1 (arm64, Always Free) to a rented x86 box Ali controls — AWS
Lightsail or EC2, 2 GB, Mumbai.** The AWS section below is the current plan;
the Oracle section that follows it is kept as the named fallback (the
blueprint's other one is Hetzner CX22) rather than deleted, since nothing in
it is wrong, only superseded. `infra/docker/`'s Dockerfile and compose.yaml
now target `linux/amd64` by default — going back to Oracle would need that
platform pin changed back, which is one more reason AWS is the plan and not a
parallel option.

**Who does what.** Ali does the signup, identity and card verification, the
region choice, the Cloudflare dashboard clicks, and the final Meta webhook
save. An agent does everything else. That split is `agents.md`'s, not a
suggestion.

**Rollback is "do nothing".** The laptop keeps serving the webhook through its
Quick Tunnel the entire time. Nothing below changes how the laptop works, and
nothing is switched over until the last step. If any step fails, stop; the
system is still running where it was this morning.

---

## AWS Lightsail/EC2 — the current plan (U17)

Terraform is out of scope for AWS (`bus-offbox-packaging`, 9 Sep 2026): one
instance, stood up once by hand, does not carry Oracle's A1-capacity retry
problem that justified Terraform there (see "Terraform, not the OCI CLI"
below) — there is nothing here to re-apply against. Steps 3-7 of the Oracle
runbook below are unchanged by provider once `public_ip` exists — Ubuntu is
Ubuntu, `harden.sh` and `install-cloudflared.sh` do not know which cloud they
are on — so they are referenced rather than duplicated.

### A1. Provision — console clicks are Ali's/his brother's, per U17

**Lightsail** (recommended — simpler console, predictable price): New
instance → **Linux/Unix**, blueprint **OS Only → Ubuntu 24.04 LTS** → the
**2 GB RAM** plan (~$10-12/mo; the 1 GB/\$5 plan is too tight once memory
lives on the box, per U17) → region **ap-south-1 (Mumbai)** → attach the SSH
key pair (create one in the console if needed, or upload
`~/.ssh/id_ed25519.pub`) → create. Note the public IP once it is running.

**EC2** is the same thing with more knobs: AMI Ubuntu 24.04 LTS (x86_64,
**not** arm64/Graviton), instance type `t3.small` (2 GB), region
`ap-south-1`, a security group allowing only inbound SSH (22) from
anywhere — everything else stays closed, same as Oracle's security list —
and the existing or a new key pair.

Either way, what an agent needs at the end is exactly `public_ip` and
confirmation the key pair is the one whose private half is on the laptop.
Paste the IP into chat; it is not a secret, unlike the SSH private key, which
never leaves the laptop.

### A2. Harden, secrets, bring the bus up, tunnel, cut over — agent (Ali types secrets and clicks Cloudflare/Meta saves)

Identical to the Oracle runbook's steps 3 through 7 below, with two
substitutions: every `ubuntu@<public-ip>` / `jarvis@<public-ip>` SSH target is
this box's IP, and step 5's platform warning inverts — the shared
`infra/docker/Dockerfile` now defaults to `linux/amd64`, which is *correct*
for this box unchanged; no `--platform` override is needed building on the
box itself (x86 building x86), and none is needed building on an x86 CI
runner either. An override is only needed if someone builds on arm64
hardware (an Apple Silicon Mac, say) and pushes the image over.

`docker compose -f infra/docker/compose.yaml up -d --build` now also starts
the `ollama` sidecar and the one-shot `ollama-pull` (`bus-offbox-packaging`);
`docker compose ... ps` should show three entries, with `ollama-pull`
`exited (0)` rather than running. `docker compose ... logs ollama-pull`
confirms the model pull if that is not obvious from `ps` alone.

---

## Oracle (superseded 8 Sep 2026, kept as the named fallback)

Everything in `infra/` was validated offline on the laptop; what could not be
validated is named at the bottom.

---

## Before the sitting

Nothing to prepare but an SSH key. If `~/.ssh/id_ed25519.pub` does not exist:

```
ssh-keygen -t ed25519 -C "ali@laptop"
```

The private half never leaves the laptop — not into this repo, not into a
consult, not into a chat.

---

## 1. Oracle signup — Ali, agent assisting

The one signup that regularly fights people. A browser agent can walk the form;
identity, the card verification and the region pick are Ali's.

**Pick a region with A1 capacity.** Ampere capacity is regional and frequently
exhausted. If provisioning later says "Out of host capacity", the fix is to
change one variable and re-apply — that is why `region` is a variable and not a
constant. Nearest-first is the sensible order; latency to Pakistan matters more
than anything else on this list.

If capacity refuses for days, the blueprint's own fallback is Hetzner CX22 at
about PKR 1,240/mo. That is Ali's call to make, not an agent's.

Then, in the console: create an API key for the OCI CLI and hand the config to
the agent.

## 2. Provision — agent

```
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars     # then fill it in
terraform init
terraform plan      # read this before applying
terraform apply
```

**Read `plan` before `apply`.** The one number to check is the shape:

```
shape_config { ocpus = 2, memory_in_gbs = 12 }
```

Anything larger is over the Always Free ceiling, and since the 18 Aug 2026
enforcement date Oracle *terminates* over-limit instances rather than refusing
them (`docs/audit/blueprint-drift.md`, Oracle entry). An instance that
disappears a week later with the bus on it is the failure this guards against.
`variables.tf` also rejects it, so this is the second check, not the only one.

What gets created: one VCN, one public subnet, an internet gateway, a route
table, a security list opening **only SSH**, and one A1 instance. No load
balancer, no NAT gateway, no bastion.

Save the outputs. `public_ip` feeds the next step.

## 3. Harden — agent

```
scp infra/scripts/harden.sh ubuntu@<public-ip>:~
ssh ubuntu@<public-ip>
sudo bash harden.sh --ssh-key "$(cat ~/.ssh/id_ed25519.pub)"
```

Creates the `jarvis` user, locks SSH to key-only, sets ufw to deny-inbound
except SSH, enables fail2ban and unattended security upgrades, installs Docker.
Idempotent, so a re-run after a partial failure is safe.

**Do not close that SSH session until a new one works.**

```
ssh jarvis@<public-ip>        # in a second terminal, before quitting the first
```

This is the step that can lock everyone out. The script refuses to restart sshd
on an invalid config, but a wrong key is not an invalid config.

Automatic reboots are deliberately off. This box is the webhook; it reboots
when Ali says so, not because a kernel landed at 06:00.

## 4. Secrets — Ali types, agent does not

The bus reads the same variables it reads on the laptop. On the VPS:

```
ssh jarvis@<public-ip>
install -m 600 /dev/null ~/jarvis.env
nano ~/jarvis.env
```

Ali pastes the values. An agent never types a token, never echoes one back, and
never copies `.env` off the laptop for him. Needed: the Supabase URL and
server-only key, the Meta token, app secret and verify token, the bus bearer
token, and whichever provider keys are live.

`chmod 600` matters — `compose.yaml` reads this file directly.

## 5. Bring the bus up — agent

```
# From the repo root ON THE VPS (git clone it there, or rsync).
docker compose -f infra/docker/compose.yaml up -d --build
docker compose -f infra/docker/compose.yaml ps
docker compose -f infra/docker/compose.yaml logs --tail 50 bus
```

If the image is instead built on the laptop and pushed, it **must** be
`--platform linux/arm64`. An x86 image on an A1 fails at run time with an exec
format error, not at build time.

Confirm from the VPS itself:

```
curl -i http://127.0.0.1:8000/status      # 401 is a pass: the app is up and protected
```

A 401 is the expected answer to an unauthenticated probe, and it proves routing
works without putting a token on a command line.

## 6. Named tunnel — Ali clicks, agent installs

In the Cloudflare dashboard: **Zero Trust → Networks → Tunnels → Create a
tunnel**, name it, and map a hostname on Ali's domain to
`http://127.0.0.1:8000`. Cloudflare hands back a connector token. That is Ali's
login and Ali's final Save.

Then:

```
scp infra/scripts/install-cloudflared.sh jarvis@<public-ip>:~
ssh jarvis@<public-ip>
sudo bash install-cloudflared.sh --token "<token>" --hostname bus.<domain>
```

Confirm **from the laptop**, not from the VPS — a loopback curl proves nothing
about a tunnel:

```
curl -i https://bus.<domain>/status        # 401 again
```

## 7. Cut over — Ali's last click

Point Meta's webhook at `https://bus.<domain>/webhook` in the WhatsApp app
settings. One save, once, and the URL never moves again.

Then send one real WhatsApp message and watch it land:

```
docker compose -f infra/docker/compose.yaml logs -f bus
```

The laptop executor keeps polling the same Supabase queue and keeps replying.
Nothing about the executor changes in Phase 4 — the bus moved, the worker did
not.

**Rolling back:** re-point Meta at the laptop's Quick Tunnel with
`tools/repoint_webhook.py`. That is the whole rollback. The VPS can sit there
idle while the problem is worked out.

---

## Terraform, not the OCI CLI

Step 1 of the task said to pick per what is testable without an account, and
record why.

Terraform wins on exactly that. `terraform validate` type-checks the whole
configuration against the real OCI provider schema with no tenancy, no
credentials and no account — and it did, on this laptop, before Ali has signed
up. A shell script wrapping `oci compute instance launch` gets `shellcheck`,
which proves the *shell* is sound and says nothing about whether the arguments
exist or the shape is expressible.

It also wins on the thing that actually goes wrong here. A1 capacity failures
mean re-running provisioning repeatedly, possibly across regions. Terraform is
idempotent and tracks what already exists; a launch script re-run after a
partial failure leaves orphan VCNs behind, which is a mess in a tenancy with a
hard resource ceiling.

The cost is a state file. For one instance, local state on the laptop is fine,
and it is gitignored along with the tfvars.

## What is laptop-assuming, and is not fixed here

Flagged rather than restructured — `bus-offbox-packaging` owns that, and this
task explicitly must not do it.

- **`requirements.txt` is one flat list** covering laptop and server both.
  `infra/docker/requirements-brain.txt` is a second, hand-kept list of what
  `bus/`, `router/`, `db/`, `memory/` and the executor modules
  `executor/conversation/service.py` imports actually need, pinned to the
  same versions (`bus-offbox-packaging`, 9 Sep 2026 — grew from six packages
  to eight when `conversation-inline-reply` put memory/recall in the bus
  process). Two lists can drift. The proper fix is an extras split in one
  file.
- **The dedup sqlite path defaults to a relative filename.**
  `bus/webhook_dedup.py` defaults to `webhook.seen-messages.db` in the working
  directory. Correct on a laptop, wrong in a container, so the Dockerfile and
  compose both set `JARVIS_WEBHOOK_DEDUP_DB_PATH` to a volume. Nothing to fix,
  but it must not be forgotten: lose that volume and every Meta redelivery
  looks new, which means duplicate replies.
- **The bus now does import `memory/`, on purpose (`conversation-inline-reply`,
  `bus-offbox-packaging`).** It still contains no Windows path, but it does
  default to `127.0.0.1:11434` for Ollama (`memory/embeddings.py`) — correct
  on the laptop, wrong for a compose sidecar the bus reaches by DNS name. The
  fix already shipped rather than being flagged here: `OLLAMA_BASE_URL`
  overrides it and `validate_ollama_loopback_url` accepts one additional
  literal hostname, `ollama` (the sidecar's compose DNS name), alongside
  `localhost`/`127.0.0.1`/`::1` — never an arbitrary one. `bus/`, `router/`
  and `db/` alone still pull in no executor-side package; the handful of
  `executor/` modules the conversation service needs are a deliberate,
  named addition (this task's Dockerfile), not something that snuck in.
- **`router/providers.yaml` is read relative to the module**, so it travels
  with the copied package. No volume needed.

## What could not be validated here, and how

Docker is not installed on this laptop, and installing Docker Desktop needs
admin rights and a reboot — not something to do to Ali's machine unasked. So
`docker build` has not run, on either pass through this task. Offline checks
stand in for it — cited in each task's Log — and `docker compose -f
infra/docker/compose.yaml config` specifically cannot run here, so
`tests/infra/test_compose_config.py` parses the YAML directly instead and
says so (`bus-offbox-packaging`, 9 Sep 2026). What remains genuinely unproven
after both passes: whether `pip install` of `requirements-brain.txt` succeeds
inside `python:3.12-slim-bookworm` on **amd64** (a strictly easier bar than
the original arm64 question — every one of these packages ships an amd64
wheel; the only Ampere-specific risk this removes), and whether the `ollama`
sidecar actually pulls `nomic-embed-text` and answers the bus at the compose
DNS name `http://ollama:11434` before the bus's own healthcheck window opens.

The first `docker compose up -d --build` on the AWS box in step A2 is that
proof. It is also the cheapest possible place to find out, since Docker is
installed by `harden.sh` and a failed build or a stuck `ollama-pull` there
costs one re-run, not a cutover — Meta's webhook is not repointed until step
7, unchanged.
