#!/usr/bin/env bash
# Push a synced ~/PiWallet checkout into /opt/piwallet without a full reprovision.
# Updates Python sources only — never deletes /opt/piwallet/.venv.
#
# Usage:
#   sudo bash ~/PiWallet/scripts/update-opt-piwallet.sh
#   sudo bash ~/PiWallet/scripts/update-opt-piwallet.sh /home/pisv/PiWallet
set -euo pipefail

if [[ -n "${1:-}" ]]; then
    SRC=$1
elif [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != root ]]; then
    SRC="/home/${SUDO_USER}/PiWallet"
else
    SRC="${HOME}/PiWallet"
fi
OPT=/opt/piwallet

[[ -d "$SRC/piwallet" ]] || {
    echo "update-opt-piwallet: missing $SRC/piwallet" >&2
    echo "usage: sudo bash $0 /home/pisv/PiWallet" >&2
    exit 1
}

echo "update-opt-piwallet: rsync allowlist $SRC -> $OPT"
bash "$SRC/scripts/rsync-pi-payload.sh" "$SRC" "$OPT/"
bash "$SRC/scripts/clean-pi-payload-junk.sh" "$OPT"

echo "update-opt-piwallet: restart piwallet-bonnet"
systemctl reset-failed piwallet-bonnet.service 2>/dev/null || true
systemctl restart piwallet-bonnet.service
echo "update-opt-piwallet: OK — bonnet running from $OPT"
