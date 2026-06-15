#!/usr/bin/env bash
# Sync PiWallet to a Raspberry Pi over rsync (run from your dev machine).
#
# Usage:
#   ./scripts/sync-to-pi.sh user@piwallet.local
#   ./scripts/sync-to-pi.sh user@piwallet.local --bootstrap
#   ./scripts/sync-to-pi.sh user@host --path /opt/piwallet --bootstrap
#
# Options:
#   --path DIR       remote directory (default: ~/PiWallet)
#   --bootstrap      run bootstrap-pi-dev.sh on the Pi after rsync
#   --resume         pass --resume to bootstrap (with --bootstrap)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE=""
REMOTE_PATH='~/PiWallet'
DO_BOOTSTRAP=0
BOOTSTRAP_ARGS=()

usage() {
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --path)        REMOTE_PATH=${2:?}; shift ;;
        --path=*)      REMOTE_PATH=${1#--path=} ;;
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

echo "rsync → ${REMOTE}:${REMOTE_PATH}/ (allowlist)"
bash "$ROOT/scripts/rsync-pi-payload.sh" "$ROOT" "${REMOTE}:${REMOTE_PATH}/"

echo "prune stale payload artifacts on Pi..."
ssh -t "$REMOTE" "sudo bash ${REMOTE_PATH}/scripts/prune-pi-payload.sh ${REMOTE_PATH}"

echo "verify remote payload..."
ssh "$REMOTE" "bash ${REMOTE_PATH}/scripts/verify-pi-payload.sh ${REMOTE_PATH}"

if [[ $DO_BOOTSTRAP -eq 1 ]]; then
    echo "bootstrap on Pi..."
    ssh "$REMOTE" "cd ${REMOTE_PATH} && bash scripts/bootstrap-pi-dev.sh ${BOOTSTRAP_ARGS[*]:-}"
fi
