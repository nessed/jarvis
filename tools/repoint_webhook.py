"""Point Meta's webhook at the current tunnel, without the dashboard.

The Cloudflare Quick Tunnel gets a new hostname every time it restarts, and
until a named tunnel lands in Phase 4 that means Meta's callback URL is stale
after every restart. Doing that through the dashboard is a browser trip per
restart — and the dashboard is exactly the surface with the known rendering
bug. The Graph API does the same job in one call:

    POST /{app-id}/subscriptions
      object=whatsapp_business_account
      callback_url=<https url>
      verify_token=<META_VERIFY_TOKEN>
      fields=messages
      access_token=<app-id>|<app-secret>

Usage
-----
    .venv\\Scripts\\python.exe tools/repoint_webhook.py               # discover URL from cloudflared log
    .venv\\Scripts\\python.exe tools/repoint_webhook.py --url https://x.trycloudflare.com
    .venv\\Scripts\\python.exe tools/repoint_webhook.py --check       # read current subscription only

Discovery reads ``tools/cloudflared.log`` (and its ``.out``/``.err`` siblings)
for the most recent ``*.trycloudflare.com`` hostname, then verifies the tunnel
actually answers before touching Meta — re-pointing at a dead tunnel is worse
than leaving the old one.

Exit codes: 0 changed or already correct, 1 usage/config error, 2 tunnel
unreachable, 3 Graph API rejected the change.

Secrets are read from ``.env`` and never printed. The app access token is
constructed in memory and never logged.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_VERSION = "v21.0"
GRAPH = "https://graph.facebook.com/" + GRAPH_VERSION
SUBSCRIBED_OBJECT = "whatsapp_business_account"
SUBSCRIBED_FIELDS = "messages"

TUNNEL_HOST = re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com")
LOG_CANDIDATES = ["cloudflared.log", "cloudflared.out.log", "cloudflared.err.log"]


def load_env() -> dict[str, str]:
    env_path = REPO_ROOT / ".env"
    values = dict(os.environ)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, raw = line.partition("=")
            values.setdefault(name.strip(), raw.strip().strip("'").strip('"'))
    return values


def discover_tunnel_url() -> str | None:
    """Most recent trycloudflare hostname across the tunnel logs."""
    newest_time = -1.0
    newest_url = None
    for name in LOG_CANDIDATES:
        path = REPO_ROOT / "tools" / name
        if not path.exists():
            continue
        matches = TUNNEL_HOST.findall(path.read_text(encoding="utf-8", errors="replace"))
        if not matches:
            continue
        mtime = path.stat().st_mtime
        if mtime > newest_time:
            newest_time, newest_url = mtime, matches[-1]
    return newest_url


def tunnel_is_live(base_url: str) -> tuple[bool, str]:
    """A tunnel that answers at all is live. /webhook without a signature is
    expected to reject (403/405) — that is proof it reached our bus, not a
    failure."""
    request = urllib.request.Request(base_url.rstrip("/") + "/webhook", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return True, "HTTP %d" % response.status
    except urllib.error.HTTPError as exc:
        return True, "HTTP %d (reached the bus)" % exc.code
    except Exception as exc:  # URLError, timeout, DNS
        return False, type(exc).__name__ + ": " + str(exc)[:200]


def graph_call(path: str, params: dict[str, str], method: str = "GET") -> dict:
    if method == "GET":
        url = GRAPH + path + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, method="GET")
    else:
        url = GRAPH + path
        request = urllib.request.Request(
            url, data=urllib.parse.urlencode(params).encode(), method="POST"
        )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"error": {"message": body[:500], "code": exc.code}}


def current_callback(app_id: str, app_token: str) -> tuple[str | None, dict]:
    payload = graph_call("/" + app_id + "/subscriptions", {"access_token": app_token})
    for entry in payload.get("data", []):
        if entry.get("object") == SUBSCRIBED_OBJECT:
            return entry.get("callback_url"), payload
    return None, payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-point Meta's WhatsApp webhook at the current tunnel via the Graph API."
    )
    parser.add_argument("--url", default=None, help="tunnel base URL; discovered from logs if omitted")
    parser.add_argument("--check", action="store_true", help="report the current subscription and exit")
    parser.add_argument("--force", action="store_true", help="re-subscribe even if the URL already matches")
    parser.add_argument("--skip-probe", action="store_true", help="do not verify the tunnel first")
    args = parser.parse_args()

    env = load_env()
    app_id = env.get("META_APP_ID")
    app_secret = env.get("META_APP_SECRET")
    verify_token = env.get("META_VERIFY_TOKEN")
    missing = [n for n, v in
               (("META_APP_ID", app_id), ("META_APP_SECRET", app_secret), ("META_VERIFY_TOKEN", verify_token))
               if not v]
    if missing:
        print("missing in .env: " + ", ".join(missing), file=sys.stderr)
        return 1

    app_token = app_id + "|" + app_secret  # app access token; never printed

    existing, raw = current_callback(app_id, app_token)
    if "error" in raw:
        print("graph error reading subscriptions: " + json.dumps(raw["error"]), file=sys.stderr)
        return 3
    print("current callback: " + (existing or "<none>"))

    if args.check:
        return 0

    base = args.url or discover_tunnel_url()
    if not base:
        print("no tunnel URL given and none found in tools/cloudflared*.log", file=sys.stderr)
        return 1
    base = base.rstrip("/")
    target = base + "/webhook"

    if not args.skip_probe:
        live, detail = tunnel_is_live(base)
        print("tunnel probe " + base + ": " + detail)
        if not live:
            print("tunnel is not answering; refusing to point Meta at a dead URL", file=sys.stderr)
            return 2

    if existing == target and not args.force:
        print("already pointed at " + target + "; nothing to do")
        return 0

    result = graph_call(
        "/" + app_id + "/subscriptions",
        {
            "object": SUBSCRIBED_OBJECT,
            "callback_url": target,
            "verify_token": verify_token,
            "fields": SUBSCRIBED_FIELDS,
            "access_token": app_token,
        },
        method="POST",
    )
    if result.get("success") is True:
        confirmed, _ = current_callback(app_id, app_token)
        print("re-pointed to " + target)
        print("confirmed by read-back: " + (confirmed or "<none>"))
        return 0 if confirmed == target else 3

    print("graph rejected the change: " + json.dumps(result), file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
