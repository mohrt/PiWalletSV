#!/usr/bin/env bash
# Sync PiWallet to a Raspberry Pi over rsync (run from your dev machine).
#
# Usage:
#   ./scripts/sync-to-pi.sh user@piwallet.local
#   ./scripts/sync-to-pi.sh user@piwallet.local --prepare
#   ./scripts/sync-to-pi.sh user@piwallet.local --bootstrap
#   ./scripts/sync-to-pi.sh user@host --path /opt/piwallet --bootstrap
#
# Options:
#   --path DIR       remote directory (default: ~/PiWallet)
#   --prepare        after sync, enable getty@tty2 on the Pi and reboot it.
#                    Use this when building a sealed image: after reboot,
#                    plug in HDMI + USB keyboard, log in on tty2, and run
#                    provision from there so radio packages purge inline
#                    without an SSH connection.
#   --bootstrap      run bootstrap-pi-dev.sh on the Pi after rsync
#   --resume         pass --resume to bootstrap (with --bootstrap)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE=""
REMOTE_PATH='~/PiWallet'
DO_BOOTSTRAP=0
DO_PREPARE=0
BOOTSTRAP_ARGS=()

usage() {
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --path)        REMOTE_PATH=${2:?}; shift ;;
        --path=*)      REMOTE_PATH=${1#--path=} ;;
        --prepare)     DO_PREPARE=1 ;;
        --bootstrap)   DO_BOOTSTRAP=1 ;;
        --resume)      BOOTSTRAP_ARGS+=(--resume) ;;
        -h|--help)     usage ;;
        -*)            echo "unknown option: $1" >&2; usage ;;
        *)
            if [[ -z "$REMOTE" ]]; then
                REMOTE=$1
            else
                echo "unexpected arg: $1" >&2
                usage
            fi
            ;;
    esac
    shift
done

[[ -n "$REMOTE" ]] || usage

CTRL=$(mktemp -u "${TMPDIR:-/tmp}/sync-to-pi.XXXX")
cleanup_ssh() {
    ssh -S "$CTRL" -O exit "$REMOTE" 2>/dev/null || true
}
trap cleanup_ssh EXIT

# One SSH login for mkdir, rsync, prune, and verify (password or key once).
ssh -M -S "$CTRL" -f -N "$REMOTE"
export SYNC_PI_SSH_SOCKET="$CTRL"
export RSYNC_RSH="ssh -S ${CTRL}"

# Resolve tilde in REMOTE_PATH once on the remote so all subsequent commands use an
# absolute path (tilde inside single/double quotes does not expand on the remote).
REMOTE_ABS=$(ssh -S "$CTRL" "$REMOTE" "eval echo \"${REMOTE_PATH}\"")

echo "rsync → ${REMOTE}:${REMOTE_ABS}/ (allowlist)"
bash "$ROOT/scripts/rsync-pi-payload.sh" "$ROOT" "${REMOTE}:${REMOTE_ABS}/"

echo "prune stale payload artifacts on Pi..."
# Root-owned .pyc files from sudo provision require sudo to remove. Use -t so sudo can
# prompt for the Pi user password if NOPASSWD is not configured.
ssh -S "$CTRL" -t "$REMOTE" "sudo bash \"${REMOTE_ABS}/scripts/clean-pi-payload-junk.sh\" \"${REMOTE_ABS}\" && sudo bash \"${REMOTE_ABS}/scripts/prune-pi-payload.sh\" \"${REMOTE_ABS}\""

echo "verify remote payload..."
ssh -S "$CTRL" "$REMOTE" "bash \"${REMOTE_ABS}/scripts/verify-pi-payload.sh\" \"${REMOTE_ABS}\""

if [[ $DO_PREPARE -eq 1 ]]; then
    echo "prepare: enabling getty@tty2 for local HDMI/keyboard provisioning..."
    ssh -S "$CTRL" -t "$REMOTE" "sudo systemctl enable getty@tty2.service"
    echo "prepare: rebooting Pi — plug in HDMI + USB keyboard, log in on tty2, then run:"
    echo "  sudo bash ~/PiWallet/deploy/provision-pi.sh --src ~/PiWallet"
    ssh -S "$CTRL" -t "$REMOTE" "sudo reboot" 2>/dev/null || true
fi

if [[ $DO_BOOTSTRAP -eq 1 ]]; then
    echo "bootstrap on Pi..."
    ssh -S "$CTRL" "$REMOTE" "cd \"${REMOTE_ABS}\" && bash scripts/bootstrap-pi-dev.sh ${BOOTSTRAP_ARGS[*]:-}"
fi
