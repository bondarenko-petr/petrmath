#!/bin/bash
# One-time installation on the existing Debian 12 server, as root.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[[ $(id -u) == 0 ]] || { echo 'Run as root' >&2; exit 1; }
[[ $# == 1 && -f $1 ]] || { echo 'Usage: bash deploy/install.sh /root/prosto5-deploy.pub' >&2; exit 1; }
KEY_FILE=$(readlink -f "$1")
ssh-keygen -l -f "$KEY_FILE" >/dev/null
KEY=$(cat "$KEY_FILE")
[[ $KEY == ssh-ed25519\ * && $KEY != *$'\n'* && $KEY != *'"'* ]] || { echo 'Expected one ed25519 public key line' >&2; exit 1; }
SOURCE=$(cd -- "$(dirname -- "$0")" && pwd)
[[ -d /srv/petrmath/app/.git && -f /srv/petrmath/app/.env ]] || { echo 'Existing application installation required' >&2; exit 1; }
apt-get update
apt-get install -y sudo util-linux curl python3-venv openssh-client
id prosto5-deploy >/dev/null 2>&1 || adduser --system --group --home /var/lib/prosto5-deploy --shell /bin/bash prosto5-deploy
install -d -m 755 /usr/local/libexec /etc/petrmath-deploy/migrations
install -o root -g root -m 755 "$SOURCE/deploy.sh" /usr/local/libexec/petrmath-deploy
install -o root -g root -m 755 "$SOURCE/ssh-entry.sh" /usr/local/libexec/petrmath-deploy-entry
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
cat > "$TMP" <<'EOF'
prosto5-deploy ALL=(petrmath) NOPASSWD: /usr/local/libexec/petrmath-deploy *
petrmath ALL=(root) NOPASSWD: /usr/bin/systemctl stop petrmath.service, /usr/bin/systemctl start petrmath.service, /usr/bin/systemctl restart petrmath.service, /usr/bin/systemctl is-active --quiet petrmath.service
EOF
visudo -cf "$TMP"
install -o root -g root -m 440 "$TMP" /etc/sudoers.d/petrmath-deploy
chown root:root /var/lib/prosto5-deploy
chmod 755 /var/lib/prosto5-deploy
install -d -o root -g root -m 755 /var/lib/prosto5-deploy/.ssh
printf 'restrict,command="/usr/local/libexec/petrmath-deploy-entry" %s\n' "$KEY" > /var/lib/prosto5-deploy/.ssh/authorized_keys
chown root:root /var/lib/prosto5-deploy/.ssh/authorized_keys
chmod 644 /var/lib/prosto5-deploy/.ssh/authorized_keys
if [[ ! -e /srv/petrmath/venvs ]]; then
    install -d -o petrmath -g petrmath -m 700 /srv/petrmath/venvs
fi
printf '%s\n' 'Installed restricted deploy key and scripts. Application was not restarted.'
