# WhatsApp dedicated worker split

## Objective

Keep inbound WhatsApp replies responsive when long-running background jobs,
especially `distill_memory`, are present. The Meta webhook remains enqueue-only.

## Scope and ownership

This lane owns `executor/poller.py`, `tools/start_jarvis.py`,
`tests/executor/test_poller.py`, and this brief. No dependency or architecture
changes are authorized.

## Design

Add poller kind filtering so the WhatsApp poller claims only
`whatsapp_webhook` jobs. Start it at the existing configured responsive poll
interval. Start a separate background poller for the long-running
`distill_memory` chain; that worker owns chain seeding. This keeps those two
competing job kinds owned by exactly one worker. Preserve the existing
unfiltered CLI semantics for diagnostics and backwards compatibility.

## Verification

Add focused unit coverage for kind isolation, handler scope, and launcher
construction/lifecycle where practical. Run the focused poller test module.
Do not restart live processes or re-point Meta from this lane; hand that over
after integration.

## Result

Implemented the two-worker launch: `whatsapp-worker` uses the existing
three-second launcher interval and atomically claims only `whatsapp_webhook`.
`background-worker` exclusively claims `distill_memory` and is the sole worker
that seeds and maintains the batch heartbeat. The ordinary unfiltered poller
still has its prior handler and seed behaviour for diagnostics.

Focused verification passed:

- `.venv\\Scripts\\python.exe -m pytest -q tests/executor/test_poller.py` —
  `37 passed in 2.21s`
- `.venv\\Scripts\\python.exe -m pytest -q tests/tools/test_start_jarvis.py` —
  `28 passed in 0.10s`
- `.venv\\Scripts\\python.exe -m py_compile executor/poller.py tools/start_jarvis.py` —
  success

## Runtime recovery handoff (2026-08-29)

### Approved design and code

The user approved the dedicated WhatsApp worker. `executor/poller.py` accepts
`--kind` and passes the existing atomic `p_kind_filter` through to the queue.
`tools/start_jarvis.py` launches:

- `whatsapp-worker`: `--kind whatsapp_webhook --no-heartbeat --interval 3`.
- `background-worker`: `--kind distill_memory --interval 3`.

The background worker alone seeds the distillation chain and owns the batch
heartbeat. The webhook remains enqueue-only. `flp_sort` has no live enqueuer;
the unfiltered diagnostic poller remains backward-compatible.

Focused proof is the three commands in Result above. The required full offline
suite was not run because `test-workspace` is claimed by
`BUILD/laptop-system-control` (`81ac6360eb934a64acf8796e7243a7aa`).

### Rollout result

An earlier stale supervised stack was stopped so the new launch could bind its
singleton port. The first `tools/start_jarvis.py` launch failed while requesting
a Cloudflare Quick Tunnel:

```
dial tcp [2606:4700::6810:e684]:443: connectex: An attempt was made to access a socket in a way forbidden by its access permissions
```

Cloudflared's installed help documents `TUNNEL_EDGE_IP_VERSION`. A second
launch with `TUNNEL_EDGE_IP_VERSION=4` reached the same IPv6 initial API
request, so that setting does not control Quick Tunnel creation. Do not repeat
that launch unchanged.

The error URL is `https://api.trycloudflare.com/tunnel`. The launcher's current
regex can match its `https://api.trycloudflare.com` prefix as though it were a
real Quick Tunnel URL. The partial launch was allowed to exit; final checks
found no listener on `127.0.0.1:8000` or `127.0.0.1:8765`, and the two worker
log files were empty. Meta re-pointing and read-back were not verified, so do
not claim the callback changed or the workers are live.

### Remaining safe sequence

1. Repair and test `tools/start_jarvis.py`'s tunnel URL recognition so only an
   actual generated `*.trycloudflare.com` hostname is accepted, never the API
   error endpoint. Also determine a Cloudflare-supported way to force the
   initial Quick Tunnel API request onto a reachable address; do not substitute
   providers.
2. Claim `cloudflare-tunnel`, `meta-webhook`, `jarvis-runtime`, and
   `ollama-runtime`, then relaunch via `tools/start_jarvis.py`.
3. Once a genuine tunnel URL is logged, run the mandated
   `tools/repoint_webhook.py` and retain its subscription read-back and Meta
   handshake evidence.
4. Confirm named worker processes/logs show the `whatsapp_webhook` and
   `distill_memory` scopes, then ask the user for the single phone typing-cue
   check.

The rollout claim is `95fe9dce5877401494a623752a0c7764` for live resources and
context/state; this brief is held by `a67e4ef8815b46fea9fb74ceef9689ad` until
the handoff is complete.
