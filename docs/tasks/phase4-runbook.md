# Phase 4 runbook — moving the bus to Oracle

Written 2 Sep 2026, before the Oracle account exists, so that U7 day is
execution rather than design. Everything in `infra/` was validated offline on
the laptop; what could not be validated is named at the bottom.

**Who does what.** Ali does the signup, identity and card verification, the
region choice, the Cloudflare dashboard clicks, and the final Meta webhook
save. An agent does everything else. That split is `agents.md`'s, not a
suggestion.

**Rollback is "do nothing".** The laptop keeps serving the webhook through its
Quick Tunnel the entire time. Nothing below changes how the laptop works, and
nothing is switched over until the last step. If any step fails, stop; the
system is still running where it was this morning.

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
  `infra/docker/requirements-bus.txt` is a second, hand-kept list of the six
  packages `bus/`, `router/` and `db/` actually import, pinned to the same
  versions. Two lists can drift. The proper fix is an extras split in one file.
- **The dedup sqlite path defaults to a relative filename.**
  `bus/webhook_dedup.py` defaults to `webhook.seen-messages.db` in the working
  directory. Correct on a laptop, wrong in a container, so the Dockerfile and
  compose both set `JARVIS_WEBHOOK_DEDUP_DB_PATH` to a volume. Nothing to fix,
  but it must not be forgotten: lose that volume and every Meta redelivery
  looks new, which means duplicate replies.
- **The bus imports nothing laptop-specific.** Checked, not assumed: `bus/`,
  `router/` and `db/` contain no reference to `localhost`, `127.0.0.1`, port
  11434, or a Windows path, and importing all three pulls in no executor-side
  package. That is why "runs off-box unchanged except env" holds.
- **`router/providers.yaml` is read relative to the module**, so it travels
  with the copied package. No volume needed.

## What could not be validated here, and how

Docker is not installed on this laptop, and installing Docker Desktop needs
admin rights and a reboot — not something to do to Ali's machine unasked. So
`docker build` has not run. Five offline checks stand in for it, and all five
pass; they are cited in the task's Log. What remains genuinely unproven is
whether `pip install` of those six packages succeeds inside
`python:3.12-slim-bookworm` on arm64.

The first `docker compose up --build` on the VPS in step 5 is that proof. It is
also the cheapest possible place to find out, since Docker is installed by step
3 and a failed build there costs one re-run, not a cutover.
