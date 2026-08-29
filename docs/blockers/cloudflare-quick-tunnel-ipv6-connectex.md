# Cloudflare Quick Tunnel cannot create over IPv6

## Reproduction

From the repository root, start the stack through its required launcher:

```powershell
.venv\Scripts\python.exe tools/start_jarvis.py
```

Cloudflared starts but Quick Tunnel creation fails before a generated tunnel
hostname is received:

```
failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": dial tcp [2606:4700::6810:e684]:443: connectex: An attempt was made to access a socket in a way forbidden by its access permissions.
```

The installed `cloudflared tunnel --help` documents `TUNNEL_EDGE_IP_VERSION`.
Launching once with that variable set to `4` produced the same IPv6 API request
and the same failure, so it does not control the Quick Tunnel provisioning call.

## What was tried

1. First normal launcher run: failed as above.
2. One launcher run with `TUNNEL_EDGE_IP_VERSION=4`: failed identically.

No third attempt was made. Both partial launches exited; the final check found
no listener on `127.0.0.1:8000` or `127.0.0.1:8765` and no live worker output.
No Meta webhook re-point or subscription read-back was verified.

## Additional guard needed

The error contains `https://api.trycloudflare.com/tunnel`. The launcher's
current URL pattern can match its `https://api.trycloudflare.com` prefix as a
putative Quick Tunnel URL. Repair and test that recognition before another
rollout, so only a genuinely provisioned Quick Tunnel hostname can reach the
Meta re-point step.

## Unblock

Determine a Cloudflare-supported configuration or network change that lets the
initial Quick Tunnel provisioning call reach `api.trycloudflare.com` without
using the unusable IPv6 path. Keep Cloudflare as the specified component; do
not substitute a different tunnel provider. Then repair the URL matcher, launch
through `tools/start_jarvis.py`, run `tools/repoint_webhook.py` only after a
genuine tunnel URL is available, and confirm its read-back before phone testing.
