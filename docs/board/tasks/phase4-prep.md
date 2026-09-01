---
id: phase4-prep
status: done
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

**2 Sep 2026 — done.**

`infra/` populated, `docs/tasks/phase4-runbook.md` written. Nothing was
provisioned; there is no Oracle account yet, which is the point.

### Terraform, not the OCI CLI — and the reason is testability

Step 1 said to pick per what is testable without an account and record why.

`terraform validate` type-checks the entire configuration against the real OCI
provider schema with no tenancy, no credentials and no account — and it did,
below, today. A shell script wrapping `oci compute instance launch` gets
`shellcheck`, which proves the shell is sound and says nothing about whether
the arguments exist or the shape is expressible.

It also wins on what actually goes wrong here: A1 capacity failures mean
re-running provisioning, possibly across regions. Terraform is idempotent and
tracks what exists; a launch script re-run after a partial failure orphans VCNs
inside a tenancy with a hard resource ceiling.

### The 2/12 numbers are enforced in three places

`variables.tf` has `validation` blocks that reject anything above 2 OCPU / 12 GB
with the reason in the error message, `outputs.tf` reads the provisioned shape
back so it can be checked before walking away, and the runbook says to read
`terraform plan` before applying. Since the 18 Aug 2026 enforcement date
Oracle *terminates* over-limit instances rather than refusing them
(`docs/audit/blueprint-drift.md`), so this is not a billing guard — it is a
guard against the VPS vanishing a week later with the bus on it.

### Validated offline

```
$ terraform fmt -check -diff .
[exit 0]

$ terraform init && terraform validate
Success! The configuration is valid.

$ shellcheck --shell=bash --severity=style infra/scripts/harden.sh infra/scripts/install-cloudflared.sh
[exit 0]
```

Neither `terraform` nor `shellcheck` is installed on this machine. Both were
run as portable binaries downloaded into the session scratchpad — no system
install, no admin rights, nothing written to Ali's PATH.

### Docker could not be run, and five checks stand in for it

Docker is not installed here, and installing Docker Desktop needs admin rights
and a reboot — not something to do to Ali's machine unasked while he is
studying. So `docker build` has not run. Instead the Dockerfile's substantive
claims were each checked directly:

```
OK   compose.yaml parses; one service, loopback-bound
OK   all 6 bus pins match requirements.txt exactly
OK   bus.main + router + db.jobs import without any executor-side package
OK   every Dockerfile COPY source exists in the repo
OK   bus.main:app exists, so the uvicorn CMD resolves
```

The third is the load-bearing one. The Dockerfile installs six packages instead
of `requirements.txt` because nothing in `bus/`, `router/` or `db/` imports the
executor-side stack — that is now a checked fact, not an assumption, and torch
alone would more than double the image on a 12 GB box.

What remains genuinely unproven: whether `pip install` of those six succeeds
inside `python:3.12-slim-bookworm` on arm64. The first
`docker compose up --build` on the VPS (runbook step 5) is that proof, and it
is the cheapest place to find out — Docker is installed by step 3 and a failed
build costs one re-run, not a cutover.

### Offline suite

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-basetemp
1129 passed, 9 deselected, 2 warnings in 52.96s
```

Untouched by this task; no test was added or changed.

### A repo-level hazard, proven: two agents cannot share one basetemp

Two runs of the full suite failed here on `tests/voice/test_record_wakeword.py`
— a different test each time — while passing in isolation and on re-run. The
test is not the problem.

The traceback is the tell. pytest had created the temp directory, and it was
gone by the time the test wrote into it:

```
voice\record_wakeword.py:189: in record_session
    writer.write(path, data, sample_rate)
E   FileNotFoundError: [Errno 2] No such file or directory:
    '...\.pytest-basetemp\test_the_cli_records_through_t0\hey_jarvis_0001_close-normal.wav'
```

**Cause, reproduced deliberately rather than inferred.** A pytest session given
an explicit `--basetemp` *resets that directory* at startup — `rmtree` then
recreate — the first time anything requests `tmp_path`. Probe: drop a marker
file in the basetemp, run a second session against the same path, look again.

```
before: True
after : False
VERDICT: WIPED by the second session
```

`CLAUDE.md` documents `--basetemp=.pytest-basetemp` as *the* command, and
`.githooks/pre-commit` uses the same literal path. So while two agents work in
one checkout, either one starting a suite deletes the other's temp files
mid-run. The failure surfaces in whichever test happens to be writing at that
instant, which is why it looks like a flaky voice test and is not one.

It cost a real commit here: the pre-commit hook went red on
`test_a_run_that_would_leave_fewer_than_thirty_clips_says_so` with nothing
wrong in the tree.

Not fixed here. `CLAUDE.md` and `.githooks/pre-commit` are outside this task's
`files:`, and the fix is a decision about the documented command — a per-process
basetemp, or a lock — not a typo. Raised for `board-audit`, and it is squarely
`pytest-addopts`' territory, which the board already flags as a barrier task
for a reason nobody had written down.

### Scope note: `.dockerignore` is at the repo root

It has to be. The build context is the repo root (compose builds with
`context: ../..`), and Docker only reads `.dockerignore` from the context root.
Without it the daemon uploads `voice/whisper/` — a multi-gigabyte build tree
with the model and the FlexML runtime in it — plus Ali's wake-word recordings,
on every build. That is minutes of upload and personal audio crossing a
boundary it has no business crossing.

The task's `files:` names `infra/` and the runbook only, so this is one new
root-level file outside that list, reported rather than assumed.

### Specified but not done

- **`docs/state.md`.** Held by the `enqueue-classifier` lane for the whole of
  this task, as for the two before it. Phase 4's row still says `infra/`
  contains a single `.gitkeep`.
- **`infra/.gitkeep`** was left in place rather than deleted; removing it is a
  one-line cleanup for whoever next touches the directory.
