# Quick Tunnel hostname parsing guard

## Objective

Prevent the launcher from treating Cloudflare's Quick Tunnel provisioning API
endpoint (`api.trycloudflare.com`) in an error message as a minted public
tunnel URL.

## Scope and ownership

This lane changes only `tools/start_jarvis.py`,
`tests/tools/test_start_jarvis.py`, this brief, and the current-state records
needed to hand off the completed guard. It does not start the stack, make a
network request, re-point Meta, or alter the provider architecture.

## Required behaviour

`wait_for_tunnel_url()` must preserve valid generated Quick Tunnel URL parsing,
but must return no URL when a log contains only the failed provisioning URL
`https://api.trycloudflare.com/tunnel`.

## Verification

Run the focused launcher test module and inspect the resulting diff. Record
only the observed result before releasing the work-board claim.

## Result

The launcher now requires a hyphenated Quick Tunnel hostname label. It ignores
the `https://api.trycloudflare.com/tunnel` provisioning URL in the observed
Cloudflare failure, while retaining the valid generated hostname match.

Focused verification:

- `.venv\\Scripts\\python.exe -m pytest -q tests/tools/test_start_jarvis.py` —
  `30 passed in 0.14s`

No launcher, tunnel, worker, or Meta operation was run by this lane.
