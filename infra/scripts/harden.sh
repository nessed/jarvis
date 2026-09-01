#!/usr/bin/env bash
#
# Harden a fresh Oracle Always Free Ubuntu 24.04 ARM instance and install
# Docker. Run once, as root or with sudo, on the VPS itself -- not from the
# laptop.
#
#   sudo bash harden.sh --user jarvis --ssh-key "ssh-ed25519 AAAA... ali@laptop"
#
# Idempotent: every step checks before acting, so a re-run after a failure
# part-way through is safe. That matters more than elegance here, because the
# step most likely to fail is the one that locks SSH down, and the recovery
# path is to fix and re-run.
#
# What this deliberately does NOT do
# ----------------------------------
#
# It opens no inbound port except SSH. The WhatsApp webhook arrives through a
# Cloudflare named tunnel, which dials outward from this box, so the bus never
# listens on the public internet. See install-cloudflared.sh.
#
# It does not touch Oracle's own security list. That is Terraform's job
# (infra/terraform/main.tf); ufw here is the second layer, not the only one.

set -euo pipefail

USERNAME="jarvis"
SSH_KEY=""
SSH_PORT="22"

usage() {
    cat <<'USAGE'
Usage: harden.sh --ssh-key "<public key>" [--user NAME] [--ssh-port N]

  --ssh-key   Contents of the public key that will be allowed in. Required:
              locking down password auth without a working key first is how a
              fresh VPS becomes unreachable.
  --user      Non-root user to create (default: jarvis)
  --ssh-port  Port to leave open (default: 22)
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --user)     USERNAME="$2"; shift 2 ;;
        --ssh-key)  SSH_KEY="$2"; shift 2 ;;
        --ssh-port) SSH_PORT="$2"; shift 2 ;;
        -h|--help)  usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "error: run this with sudo." >&2
    exit 1
fi

if [ -z "$SSH_KEY" ]; then
    echo "error: --ssh-key is required. See --help for why." >&2
    exit 2
fi

log() { echo "==> $*"; }

# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------

log "updating package lists"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq

log "installing ufw, fail2ban, unattended-upgrades"
apt-get install -y -qq ufw fail2ban unattended-upgrades ca-certificates curl gnupg

# ---------------------------------------------------------------------------
# The non-root user
# ---------------------------------------------------------------------------

if id -u "$USERNAME" >/dev/null 2>&1; then
    log "user $USERNAME already exists"
else
    log "creating $USERNAME"
    adduser --disabled-password --gecos "" "$USERNAME"
fi

usermod -aG sudo "$USERNAME"

install -d -m 700 -o "$USERNAME" -g "$USERNAME" "/home/$USERNAME/.ssh"
AUTHORIZED="/home/$USERNAME/.ssh/authorized_keys"
touch "$AUTHORIZED"
if grep -qxF "$SSH_KEY" "$AUTHORIZED"; then
    log "ssh key already authorized"
else
    log "authorizing ssh key"
    echo "$SSH_KEY" >> "$AUTHORIZED"
fi
chmod 600 "$AUTHORIZED"
chown "$USERNAME:$USERNAME" "$AUTHORIZED"

# Passwordless sudo for this one user. The alternative is a password on an
# account whose whole point is that it has no password, which would mean
# unattended restarts prompting into a void.
echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$USERNAME"
chmod 440 "/etc/sudoers.d/90-$USERNAME"

# ---------------------------------------------------------------------------
# SSH
#
# Written as a drop-in rather than by editing sshd_config, so this is
# reversible by deleting one file and so a re-run cannot accumulate duplicate
# directives.
# ---------------------------------------------------------------------------

log "locking SSH down to key-only"
cat > /etc/ssh/sshd_config.d/10-jarvis-hardening.conf <<EOF
Port $SSH_PORT
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
X11Forwarding no
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
AllowUsers $USERNAME
EOF

# Refuse to restart into a broken config. Without this check, a typo above
# takes the only way in with it.
if ! sshd -t; then
    echo "error: sshd config is invalid; leaving the running config alone." >&2
    rm -f /etc/ssh/sshd_config.d/10-jarvis-hardening.conf
    exit 1
fi
systemctl restart ssh

# ---------------------------------------------------------------------------
# Firewall
#
# Oracle's Ubuntu images ship iptables rules of their own and an empty
# ufw. Setting default-deny inbound before allowing SSH would drop the
# session this script is running in, so the order here is not stylistic.
# ---------------------------------------------------------------------------

log "configuring ufw"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow "$SSH_PORT"/tcp comment "ssh"
# No rule for the bus. cloudflared connects outbound; nothing dials in.
ufw --force enable
ufw status verbose

# ---------------------------------------------------------------------------
# fail2ban and unattended upgrades
# ---------------------------------------------------------------------------

log "configuring fail2ban for sshd"
cat > /etc/fail2ban/jail.d/sshd.local <<EOF
[sshd]
enabled = true
port = $SSH_PORT
backend = systemd
maxretry = 3
findtime = 10m
bantime = 1h
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban

log "enabling unattended security upgrades"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
# Reboots are not automatic. This box is the webhook; it reboots when Ali says
# so, not at 06:00 because a kernel landed.
sed -i 's|^//\s*Unattended-Upgrade::Automatic-Reboot ".*";|Unattended-Upgrade::Automatic-Reboot "false";|' \
    /etc/apt/apt.conf.d/50unattended-upgrades

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

if command -v docker >/dev/null 2>&1; then
    log "docker already installed"
else
    log "installing docker from Docker's own apt repo"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    ARCH="$(dpkg --print-architecture)"
    # shellcheck source=/dev/null  # only exists on the target host
    CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
    echo "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $CODENAME stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
fi

usermod -aG docker "$USERNAME"
systemctl enable --now docker

log "done"
cat <<EOF

Next, and in this order:

  1. From the laptop, in a NEW terminal, confirm you can still get in:
         ssh -p $SSH_PORT $USERNAME@<public-ip>
     Do not close the session this ran in until that works.
  2. Run install-cloudflared.sh to attach the named tunnel.
  3. Bring the bus up with docker/compose.yaml.
EOF
