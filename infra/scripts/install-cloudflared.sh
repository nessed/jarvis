#!/usr/bin/env bash
#
# Install cloudflared on the VPS and run a *named* tunnel as a systemd service,
# pointing at the bus container.
#
#   sudo bash install-cloudflared.sh --token "<connector token>" --hostname bus.example.com
#
# Why a named tunnel and not the Quick Tunnel the laptop uses today
# -----------------------------------------------------------------
#
# The laptop runs `cloudflared tunnel --url ...`, which mints a fresh
# trycloudflare.com hostname on every restart. That is why tools/repoint_webhook.py
# exists at all: something has to walk Meta's subscription over to the new URL.
#
# A named tunnel has a stable hostname on a domain Ali controls. Once Meta is
# pointed at it, the webhook URL never changes again -- through reboots,
# redeploys, and cloudflared upgrades. Retiring the repoint dance is a good
# half of what Phase 4 buys.
#
# What is NOT scriptable
# ----------------------
#
# Creating the tunnel and mapping the hostname happen in Cloudflare's
# dashboard, under Zero Trust -> Networks -> Tunnels. Ali does that; it needs
# his login, and the last click is his by the rules in agents.md. The dashboard
# hands back a connector token, which is the one argument this script needs.
#
# The token is a credential. It is passed as an argument and written to a
# root-only file; it is never echoed, never logged, and never committed.

set -euo pipefail

TOKEN=""
HOSTNAME_FQDN=""
SERVICE_URL="http://127.0.0.1:8000"

usage() {
    cat <<'USAGE'
Usage: install-cloudflared.sh --token "<connector token>" [--hostname FQDN] [--service URL]

  --token     Connector token from the Cloudflare dashboard. Required.
  --hostname  The public hostname you mapped, for the confirmation message only.
  --service   Local service the tunnel fronts (default: http://127.0.0.1:8000)
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --token)    TOKEN="$2"; shift 2 ;;
        --hostname) HOSTNAME_FQDN="$2"; shift 2 ;;
        --service)  SERVICE_URL="$2"; shift 2 ;;
        -h|--help)  usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "error: run this with sudo." >&2
    exit 1
fi

if [ -z "$TOKEN" ]; then
    echo "error: --token is required. Create the tunnel in the Cloudflare" >&2
    echo "       dashboard first; it hands you the token." >&2
    exit 2
fi

log() { echo "==> $*"; }

if command -v cloudflared >/dev/null 2>&1; then
    log "cloudflared already installed"
else
    log "installing cloudflared from Cloudflare's apt repo"
    export DEBIAN_FRONTEND=noninteractive
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
        -o /etc/apt/keyrings/cloudflare-main.gpg
    chmod a+r /etc/apt/keyrings/cloudflare-main.gpg
    # shellcheck source=/dev/null  # only exists on the target host
    CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
    echo "deb [signed-by=/etc/apt/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $CODENAME main" \
        > /etc/apt/sources.list.d/cloudflared.list
    apt-get update -qq
    apt-get install -y -qq cloudflared
fi

# `cloudflared service install <token>` writes the token into a unit file that
# is world-readable on some builds. Writing it to a root-only environment file
# and pointing the unit at that keeps it out of `systemctl cat` for anyone who
# is not already root.
log "writing the connector token to a root-only file"
install -d -m 700 /etc/cloudflared
umask 077
printf 'TUNNEL_TOKEN=%s\n' "$TOKEN" > /etc/cloudflared/tunnel.env
chmod 600 /etc/cloudflared/tunnel.env

log "installing the systemd unit"
cat > /etc/systemd/system/cloudflared.service <<EOF
[Unit]
Description=Cloudflare named tunnel for the JARVIS bus
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=notify
EnvironmentFile=/etc/cloudflared/tunnel.env
ExecStart=/usr/bin/cloudflared --no-autoupdate tunnel run
Restart=always
RestartSec=5
User=root
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now cloudflared
systemctl restart cloudflared

log "cloudflared status"
systemctl --no-pager --lines=10 status cloudflared || true

cat <<EOF

Tunnel service installed. It fronts $SERVICE_URL.

Confirm from the laptop, not from here -- a curl to localhost proves nothing
about the tunnel:

    curl -i https://${HOSTNAME_FQDN:-<your-hostname>}/status

Then point Meta at it ONCE, in the WhatsApp app's webhook settings. After
this, tools/repoint_webhook.py is only needed for the laptop's dev tunnel;
the production URL stops moving.
EOF
