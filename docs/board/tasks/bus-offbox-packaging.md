---
id: bus-offbox-packaging
status: done
lane: AUTO
priority: 2
phase: 4
blocked-on: none for the packaging; the image build itself happens on the box (no Docker on this laptop — `docker --version` fails, 8 Sep 2026)
files: infra/docker/Dockerfile, infra/docker/compose.yaml, infra/docker/requirements-brain.txt (new), infra/docker/.dockerignore, infra/README.md, docs/tasks/phase4-runbook.md (AWS section), tests/infra/ (new, offline checks)
resources: none
---

# bus-offbox-packaging — package the brain, not just the inbox

## Why (rewritten 8 Sep 2026)

The current image ships `bus/`, `router/`, `db/` only, built for
`linux/arm64` (Oracle A1). Deploying it gives a webhook that is up with
the laptop closed and nothing that can answer (Astra §3.5, Fable §2.4).
Ali's 8 Sep answers change the target: **brain on a rented x86 server
Ali controls** (AWS, 2 GB, Mumbai — U17), conversation handled inline
(`conversation-inline-reply`), recall/lookup on that box, extraction
staying on the laptop (CLAUDE.md #3 as amended; Q17 performance note).

## Steps

1. `Dockerfile`: `linux/amd64`; copy `bus/`, `router/`, `db/`,
   `memory/`, `executor/conversation/` (and only the executor modules the
   service imports). `requirements-brain.txt` pinned to the same lines as
   `requirements.txt`; still no torch/kokoro/pywinauto/pyflp/voice. Add an
   offline test that greps the image's copied packages for those imports
   and fails if one appears.
2. `compose.yaml`: add an `ollama` sidecar (official image, CPU) with
   `nomic-embed-text` pulled at first start, reachable from the bus as
   `http://ollama:11434` — **note** the loopback guard in
   `memory/embeddings.py` must accept a compose-network hostname that is
   still "this host": make the allowed base URL explicit via
   `OLLAMA_BASE_URL` with the default unchanged (`127.0.0.1`), and keep
   the fail-closed check for anything that is not loopback or the named
   sidecar. Name the guard's tests in the Log. Volumes: `brain-state`
   for sqlite/sqlite-vec, `ollama-models`.
3. No extraction on the box: `JARVIS_DISTILL=0` in the compose
   environment, with the comment pointing at Q17's performance note.
4. Runbook: add an **AWS Lightsail/EC2** section beside the Oracle one —
   Ubuntu 24.04 x86, 2 GB, Mumbai, key-only SSH, the existing
   `infra/scripts/harden.sh`, Docker, named Cloudflare tunnel. Terraform
   for AWS is out of scope; document the console steps Ali/brother click
   and the agent steps after `public_ip` exists.
5. Offline verification only: `docker compose -f infra/docker/compose.yaml config`
   cannot run here (no Docker) — validate YAML with a Python test instead
   and say so. The real build is `vps-harden-deploy` step 1 on the box.

## Done when

Offline suite (including the new `tests/infra/`) green; runbook AWS
section written; Log names what could not be validated without Docker.

## Log

### 2026-09-09 — done (lane-1)

**Premise re-verified.** `docker --version` still fails on this laptop (no
change since 8 Sep); `conversation-inline-reply` (this session, earlier) is
done, so the target the "Why" section describes is real, not aspirational.

**Step 1 — Dockerfile and requirements-brain.txt.** Rewrote
`infra/docker/Dockerfile`: `FROM --platform=linux/amd64` (explicit, so it
does not depend on the build host's own architecture or a remembered
`buildx` flag), selective `COPY` lines for `bus/`, `router/`, `db/`,
`memory/` (whole package) and exactly the executor modules
`ConversationService` needs transitively — `executor/__init__.py`,
`executor/latency.py`, `executor/notify.py`, `executor/conversation/`,
`executor/handlers/__init__.py`, `executor/handlers/command_intent.py`,
`executor/handlers/outcome.py`, `executor/handlers/whatsapp.py`. Traced by
hand from `bus/conversation_runner.py`'s own imports (built this session)
down through `executor.conversation.service` and `memory.conversation` —
nothing in that chain reaches `executor/flp/`, `executor/system_control/` or
`executor/handlers/distill.py`, all deliberately left uncopied.
`infra/docker/requirements-brain.txt` (new) replaces
`requirements-bus.txt` (deleted): the original six lines plus `sqlite-vec`
and `mem0ai`, both required only because `memory/__init__.py` imports
`memory.mem0_wrapper` unconditionally — `import memory.conversation` cannot
succeed without `mem0ai` importable even though extraction never runs on
this box. Confirmed mem0ai's own base install (no `llms`/`vector-stores`
extras) pulls `qdrant-client`/`sqlalchemy`, not torch:
`python -c "import importlib.metadata as m; print(m.requires('mem0ai'))"`.
The `ollama` python package is *not* needed — `OllamaEmbeddingProvider`
talks to Ollama over plain `httpx`, never that client.

**The offline test the step asked for is `tests/infra/test_image_contents.py`**:
parses the Dockerfile's own `COPY` lines, then greps every file under each
source for a *module-level* `import`/`from` of `{torch, kokoro, pywinauto,
pyflp, sounddevice, voice}` — the same set the two `import`-time tests
(`test_conversation_service.py`, `test_conversation_runner.py`) already
assert against a live process. Deliberately column-zero only: an indented
import (`executor/handlers/whatsapp.py`'s lazy `voice.audio`/`voice.config`
imports inside its STT/TTS default functions) runs only if that function is
called, and the bus never calls those — only text reaches the inline path,
voice still queues. `TestTheCheckerItself` proves the regex actually
discriminates (catches a synthetic top-level `import torch`, ignores the
same import indented inside a function) rather than trusting a test that
happens to pass. `tests/infra/test_requirements_brain.py` is the matching
guard one layer down: every brain pin must equal the same line in
`requirements.txt` verbatim, and none of the banned packages may appear.

**Step 2 — compose.yaml and the loopback guard.** Added the `ollama`
sidecar (`ollama/ollama:latest`, CPU, `expose`-only — never `ports`,
so it is unreachable from outside the compose network) and a one-shot
`ollama-pull` service (`ollama pull nomic-embed-text`, `bus` depends on its
`service_completed_successfully` as well as `ollama`'s `service_healthy`, so
the first real embed does not race the pull). `memory/embeddings.py`'s
`validate_ollama_loopback_url` now accepts one additional literal hostname,
`ollama` (`COMPOSE_OLLAMA_SIDECAR_HOSTNAME`), alongside
`localhost`/`127.0.0.1`/`::1` — a fixed literal, not a pattern, and CLAUDE.md
#3's 8 Sep amendment ("a host Ali controls", not only the laptop) is why this
is not a loosening: the sidecar and the bus are the only two containers in
that network, both on the same rented box. **Guard tests named, per the
step**: `tests/memory/test_embeddings.py::test_the_compose_ollama_sidecar_hostname_is_accepted_as_this_host`
and `::test_a_lookalike_hostname_is_still_rejected` (a suffix/prefix
lookalike hostname, `ollama.example.com` / `not-ollama`, is still refused —
exact match only). `OLLAMA_BASE_URL`'s default is unchanged
(`http://127.0.0.1:11434`); compose sets it explicitly to
`http://ollama:11434` for the bus container only. `MEMORY_DB_PATH` and
`JARVIS_WEBHOOK_DEDUP_DB_PATH` both point under `/app/state`, one
`brain-state` volume for both (the pending-confirmations sqlite derives its
path from `MEMORY_DB_PATH` too, via `.with_suffix()`, so it rides along with
no separate line needed). `tests/infra/test_compose_config.py` (10 tests)
checks the shape by parsing the YAML: three services, the bus's loopback
binding, the sidecar's DNS name, both `depends_on` conditions, both volumes
declared and mounted, the model name matching between `bus` and
`ollama-pull`, and that `env_file` never points inside the repo.

**Step 3 — no extraction on the box.** `JARVIS_DISTILL: "0"` in `bus`'s
compose environment. Belt-and-suspenders rather than load-bearing: this
compose file has no worker container that could ever claim a
`distill_memory` job in the first place, so the flag has nothing to gate
today — set anyway so a container added to this file later does not
silently inherit extraction by omission. Comment points at Q17's
performance note, per the step.

**Step 4 — runbook AWS section.** `docs/tasks/phase4-runbook.md` gained an
"AWS Lightsail/EC2 — the current plan (U17)" section ahead of the Oracle
one, which is kept (not deleted) and relabeled "superseded... kept as the
named fallback." Console-click steps for both Lightsail (recommended) and
EC2, Terraform explicitly out of scope with a one-line reason (one instance,
one sitting, none of Oracle's A1-capacity-retry problem that justified
Terraform there); the agent-side steps (harden, secrets, bring the bus up,
tunnel, cutover) are referenced against the existing Oracle steps 3-7 rather
than duplicated, since nothing in them is provider-specific. Also corrected
two claims the Oracle section made that this task's own changes made false:
the `requirements-bus.txt` bullet (renamed, and why it grew past six
packages) and "the bus imports nothing laptop-specific" (it now imports
`memory/`, which does default to a loopback Ollama URL — described instead
of re-flagged, since the fix already shipped in step 2). `infra/README.md`
rewritten the same way: AWS as the plan, Oracle as the fallback, the new
`tests/infra/` layout documented in place of the old five-check paragraph.

**Step 5 — offline verification only, and the one deliberate file-path
deviation.** The task's frontmatter names `infra/docker/.dockerignore`, but
Docker's own rule (checked against current docs, not remembered) is that an
ignore file — the plain `.dockerignore` or a Dockerfile-specific
`<name>.dockerignore` — must live in the **build context root**, never
beside the Dockerfile itself, when the two differ. `compose.yaml`'s context
is `../..` (the repo root), so `infra/docker/.dockerignore` would be
silently inert — Docker would never read it, and neither `COPY memory/` nor
the exclusions below it would take effect. The repo already had exactly this
file correctly placed at `.dockerignore` (root), predating this task, with a
comment saying so ("Build context is the repo root... so this file has to
live here rather than beside the Dockerfile"). Edited that file instead:
removed the blanket `memory/` and `executor/` excludes (which would have
silently starved this task's own new `COPY` lines) and added targeted
excludes for what should still never enter the build context —
`executor/flp/`, `executor/system_control/`, `executor/app_automation/`,
`executor/heartbeat.py`, `executor/poller.py`, `executor/handlers/distill.py`.
`tests/infra/test_dockerignore.py` guards both directions: the blanket
excludes must not come back, and the targeted ones must not quietly
disappear. `docker compose -f infra/docker/compose.yaml config` cannot run
here (no Docker); `tests/infra/test_compose_config.py` parses the YAML
directly instead, as the step asked.

**What could not be validated without Docker** (the step 5 / "Done when"
citation): whether `pip install -r requirements-brain.txt` actually succeeds
inside `python:3.12-slim-bookworm` on amd64 (believed yes — every package in
it ships an amd64 wheel, unlike the arm64 question the original Oracle image
never got to answer either), and whether the `ollama` sidecar actually
answers the bus at `http://ollama:11434` once both containers are up. Both
are `vps-harden-deploy` step 1's first real proof, on the box, not something
fakeable from this laptop.

**Full offline suite.**

```
$ .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest-basetemp-lane-1
1661 passed, 10 deselected in 57.14s
```

1620 -> 1661: 39 new `tests/infra/*`, 2 new `tests/memory/test_embeddings.py`
(the compose hostname exception and its lookalike-rejection counterpart).
